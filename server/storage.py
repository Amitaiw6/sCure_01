"""
Durable JSON-file storage for the sCure API (no-Postgres deployment).

Everything the UI records - user work programs, received prints, cure runs
(with telemetry), cure reports, phase timings and the component ON-hour
counters - lives under DATA_DIR (server/data/, gitignored, so `git pull`
never deletes it; override with the SCURE_DATA_DIR env var, e.g. for tests).
Every writer uses the atomic idiom (tmp -> flush -> fsync -> os.replace) so a
power cut mid-write cannot corrupt an existing file. When Postgres IS
configured (server/db.py) it stays authoritative and these files are not
touched - that gate lives in app.py.

Extracted verbatim from server/app.py (2026-08 refactor).
"""

import os
import json
import threading
import time

# --- Persistent user-program store (JSON file on the SSD) ------------------
# Durable no-Postgres store for user work programs (browser localStorage alone
# is fragile: per-browser, cleared on profile reset); see module docstring.
DATA_DIR = (os.environ.get('SCURE_DATA_DIR')
            or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
USER_MATERIALS_FILE = os.path.join(DATA_DIR, 'user_materials.json')


def load_user_materials():
    try:
        with open(USER_MATERIALS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001 - corrupt/unreadable: start empty, don't crash
        print(f"[DATA] user programs read failed: {e}")
        return []


def save_user_materials(materials):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = USER_MATERIALS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(materials, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())          # force the bytes to the SSD before rename
    os.replace(tmp, USER_MATERIALS_FILE)   # atomic swap


# --- Durable file store for histories (no-Postgres fallback) ---------------
# Received prints, cure runs (with telemetry) and cure reports; same
# durability contract as the user-program file (see module docstring).
PRINT_HISTORY_FILE = os.path.join(DATA_DIR, 'print_history.json')
CURE_HISTORY_FILE = os.path.join(DATA_DIR, 'cure_history.json')
CURE_REPORTS_FILE = os.path.join(DATA_DIR, 'cure_reports.json')
history_lock = threading.Lock()          # serializes read-modify-write cycles
TELEMETRY_FLUSH_EVERY = 15               # samples between telemetry flushes
PHASE_TIMINGS_FILE = os.path.join(DATA_DIR, 'phase_timings.json')   # real phase-timing analytics (app.py)


def load_json_file(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except FileNotFoundError:
        return default
    except Exception as e:  # noqa: BLE001 - corrupt file: start empty, don't crash
        print(f"[DATA] read failed ({os.path.basename(path)}): {e}")
        return default


def save_json_file(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class CureFileStore:
    """Cure runs + telemetry + reports in server/data/*.json.

    Start/finish/report writes flush immediately; telemetry (the UI posts one
    sample every 5 s during a run, CureProcessPage.tsx) flushes every
    TELEMETRY_FLUSH_EVERY samples (= every 75 s) so the SSD is not rewritten
    on every sample - a power cut loses at most the last ~minute of the
    graph, never the run itself.
    """

    def __init__(self):
        with history_lock:
            self.runs = load_json_file(CURE_HISTORY_FILE, [])
            self.reports = load_json_file(CURE_REPORTS_FILE, {})
            self._unflushed = 0
            # a run left 'running' by a power cut can never finish - mark it
            changed = False
            for r in self.runs:
                if r.get('status') == 'running':
                    r['status'] = 'error'
                    changed = True
            if changed:
                self._flush_runs()

    def _flush_runs(self):
        save_json_file(CURE_HISTORY_FILE, self.runs)

    def list(self):
        with history_lock:
            return list(self.runs)

    def _find(self, ext_id):
        for r in self.runs:
            if r.get('id') == ext_id:
                return r
        return None

    def start(self, ext_id, d):
        with history_lock:
            if self._find(ext_id) is None:
                self.runs.insert(0, {
                    'id': ext_id,
                    'materialName': d.get('materialName'),
                    'steps': d.get('steps'),
                    'stepsCompleted': 0,
                    'startedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'endedAt': None,
                    'duration': None,
                    'status': 'running',
                    'phases': d.get('phases') or [],
                    'targetTemp': d.get('targetTemp'),
                    'serialNumber': d.get('serialNumber'),
                    'telemetry': [],
                })
            self._flush_runs()

    def telemetry(self, ext_id, sample):
        with history_lock:
            r = self._find(ext_id)
            if r is None:
                return False
            r.setdefault('telemetry', []).append(sample)
            self._unflushed += 1
            if self._unflushed >= TELEMETRY_FLUSH_EVERY:
                self._flush_runs()
                self._unflushed = 0
            return True

    def finish(self, ext_id, status, steps_completed):
        with history_lock:
            r = self._find(ext_id)
            if r is None:
                return False
            r['status'] = status
            r['endedAt'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            if steps_completed is not None:
                r['stepsCompleted'] = steps_completed
            try:
                t0 = time.mktime(time.strptime(r['startedAt'], '%Y-%m-%dT%H:%M:%S'))
                r['duration'] = int(time.time() - t0)
            except Exception:  # noqa: BLE001 - unparsable start: leave duration
                pass
            self._flush_runs()
            return True

    def save_report(self, ext_id, d):
        with history_lock:
            self.reports[ext_id] = {'content': d.get('content'),
                                    'summary': d.get('summary'),
                                    'format': d.get('format', 'html')}
            save_json_file(CURE_REPORTS_FILE, self.reports)
        return ext_id

    def get_report(self, ext_id):
        with history_lock:
            return self.reports.get(ext_id)


# ============================================================
# Component runtime counters (real ON-hours, persisted)
# ============================================================
class ComponentCounters:
    """Accumulates the real ON-time of the wear components and persists it.

    Samples the authoritative hardware state every TICK seconds:
      led405 / led450 - UV on at that wavelength
      heater          - heater element actually energized (heaterOut: the
                        instantaneous delta-sigma ON/OFF output, not merely
                        "heating mode" - the PI controller streams the
                        element ON and OFF; fallback: heaterPwm > 0)
      heaterFan       - measured tach RPM (fallback: commanded duty)
      coolingFan      - measured tach RPM (fallback: commanded duty)

    Seconds are flushed atomically (tmp + os.replace) to a JSON file every
    FLUSH_SEC while something is running, and once more on process exit, so
    the totals survive reboots and power cuts (worst case: the last minute).
    """

    KEYS = ('led405', 'led450', 'coolingFan', 'heater', 'heaterFan')
    TICK = 2.0
    FLUSH_SEC = 60.0

    def __init__(self, path, get_state):
        self.path = path
        self._get_state = get_state     # callable -> authoritative hw state dict
        self._lock = threading.Lock()
        self._dirty = False
        self.seconds = {k: 0.0 for k in self.KEYS}
        try:
            with open(self.path, encoding='utf-8') as f:
                saved = json.load(f)
            for k in self.KEYS:
                self.seconds[k] = max(0.0, float(saved.get(k, 0.0)))
            print(f"[COUNTERS] loaded: " +
                  ', '.join(f'{k}={v/3600:.1f}h' for k, v in self.seconds.items()))
        except FileNotFoundError:
            print("[COUNTERS] no saved counters - starting from zero")
        except Exception as e:  # noqa: BLE001 - corrupt file: keep zeros, will rewrite
            print(f"[COUNTERS] load failed ({e}) - starting from zero")
        threading.Thread(target=self._run, daemon=True,
                         name='component-counters').start()

    def hours(self):
        """Current totals in hours (1 decimal), for /api/state."""
        with self._lock:
            return {k: round(v / 3600.0, 1) for k, v in self.seconds.items()}

    def flush(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._lock:
            payload = {k: round(v, 1) for k, v in self.seconds.items()}
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _sample(self):
        s = self._get_state()
        rpm = s.get('fanRpm') or {}
        duty = s.get('fans') or {}
        heater_pwm = s.get('heaterPwm')
        heater_out = s.get('heaterOut')
        return {
            'led405': bool(s.get('uvOn')) and s.get('uvWavelength') == 405,
            'led450': bool(s.get('uvOn')) and s.get('uvWavelength') == 450,
            # Guarded by isHeating: the element can only be energized while
            # the heating loop is active — a stale heaterOut/heaterPwm after
            # a stop must never count (this is how heater hours once ran past
            # the heater-fan hours, which is physically impossible).
            'heater': bool(s.get('isHeating')) and (
                bool(heater_out) if heater_out is not None
                else (heater_pwm > 0) if heater_pwm is not None
                else True),
            'heaterFan': rpm.get('chamber_heating', 0) > 0
                         or duty.get('chamber_heating', 0) > 0,
            'coolingFan': rpm.get('chamber_intake', 0) > 0
                          or duty.get('chamber_intake', 0) > 0,
        }

    def _run(self):
        last_flush = time.monotonic()
        while True:
            time.sleep(self.TICK)
            try:
                on = self._sample()
            except Exception:  # noqa: BLE001 - state read failed: skip the tick
                continue
            with self._lock:
                for k, active in on.items():
                    if active:
                        self.seconds[k] += self.TICK
                        self._dirty = True
            if self._dirty and time.monotonic() - last_flush >= self.FLUSH_SEC:
                try:
                    self.flush()
                    self._dirty = False
                    last_flush = time.monotonic()
                except Exception as e:  # noqa: BLE001 - disk hiccup: retry next round
                    print(f"[COUNTERS] flush failed: {e}")
