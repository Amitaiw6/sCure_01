"""
Cloud sync agent: connects the machine OUT to the sCure Cloud portal
(cloud/portal.py). Outbound-only, data-only commands - see CloudSync.

Extracted verbatim from server/app.py (2026-08 refactor); the data accessors
are injected by app.py so this module has no dependency on the Flask app,
the hardware controller or the DB gate.
"""

import os
import json
import threading
import time


class CloudSync:
    """Connects the machine OUT to the sCure Cloud portal.

    Enabled by server/data/cloud.json:
        {"url": "https://portal.example.com", "key": "<machine secret>",
         "name": "CureBox-1", "interval": 10}
    Every `interval` seconds it POSTs a snapshot (state, counters, programs,
    prints, cure summaries) to /api/agent/sync and applies the returned
    DATA-ONLY commands:
        upsert_program / delete_program - work programs (work points)
        send_print                      - simulated received print
    There is deliberately no command that actuates hardware - heater/UV can
    only be started at the machine. Outbound-only: no inbound ports needed,
    works behind any NAT/firewall. Applied command ids are acked on the
    next sync so a command is never applied twice.
    """

    def __init__(self, data_dir, get_state, counters, get_programs,
                 put_programs, get_prints, put_prints, list_cures):
        """data_dir: folder holding cloud.json; get_state: callable -> hw state
        dict; counters: ComponentCounters; the remaining callables read/write
        the same stores the API routes use (Postgres or the JSON files)."""
        self._data_dir = data_dir
        self._get_state = get_state
        self._counters = counters
        self._get_programs = get_programs
        self._put_programs = put_programs
        self._get_prints = get_prints
        self._put_prints = put_prints
        self._list_cures = list_cures
        self.enabled = False
        self.last_ok = None           # epoch of the last successful sync
        self.error = None
        self.cfg = {}
        try:
            with open(os.path.join(self._data_dir, 'cloud.json'), encoding='utf-8') as f:
                self.cfg = json.load(f)
        except FileNotFoundError:
            return                    # not configured - agent stays off
        except Exception as e:        # noqa: BLE001 - unreadable config
            self.error = f'bad cloud.json: {e}'
            return
        if not (self.cfg.get('url') and self.cfg.get('key')):
            self.error = 'cloud.json needs "url" and "key"'
            return
        self.enabled = True
        self._ack = []
        threading.Thread(target=self._run, daemon=True, name='cloud-sync').start()
        print(f"[CLOUD] sync agent ON -> {self.cfg['url']}")

    def status(self):
        return {'enabled': self.enabled, 'lastSyncOk': self.last_ok,
                'error': self.error}

    def _snapshot(self):
        try:
            s = self._get_state()
            state = {k: s.get(k) for k in ('chamberTemp', 'doorClosed',
                                           'isHeating', 'isCooling', 'uvOn',
                                           'internetOk')}
            state['counters'] = self._counters.hours()
        except Exception:             # noqa: BLE001 - snapshot must never die
            state = {}
        cures = self._list_cures()
        cures = [{k: v for k, v in c.items() if k != 'telemetry'}
                 for c in cures[:10]]
        return {'name': self.cfg.get('name', 'CureBox'), 'state': state,
                'programs': self._get_programs(),
                'prints': self._get_prints()[:20], 'cures': cures,
                'ackIds': self._ack}

    def _apply(self, cmd):
        ctype, p = cmd.get('type'), cmd.get('payload') or {}
        if ctype == 'upsert_program':
            mats = [m for m in self._get_programs() if m.get('id') != p.get('id')]
            self._put_programs(mats + [p])
            print(f"[CLOUD] program saved from portal: {p.get('name')}")
        elif ctype == 'delete_program':
            self._put_programs([m for m in self._get_programs()
                                if m.get('id') != p.get('id')])
            print(f"[CLOUD] program deleted from portal: {p.get('id')}")
        elif ctype == 'send_print':
            prog = next((m for m in self._get_programs()
                         if m.get('name') == p.get('materialName')), None)
            log = {'id': f'cloud-{int(time.time() * 1000)}',
                   'printName': p.get('printName') or 'Job',
                   'materialName': p.get('materialName') or '',
                   'printerName': p.get('printerName') or 'CLOUD',
                   'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
                   'duration': int(p.get('duration')
                                   or (prog or {}).get('totalDuration') or 20),
                   'status': 'completed',
                   'steps': len((prog or {}).get('steps') or []) or int(p.get('steps') or 0),
                   'csvFile': p.get('csvFile') or ''}
            self._put_prints([log] + self._get_prints())
            print(f"[CLOUD] simulated print received: {log['printName']} "
                  f"({log['printerName']})")
        else:
            return False
        return True

    def _run(self):
        import urllib.request
        interval = max(3.0, float(self.cfg.get('interval', 10)))
        url = self.cfg['url'].rstrip('/') + '/api/agent/sync'
        while True:
            try:
                req = urllib.request.Request(
                    url, data=json.dumps(self._snapshot()).encode('utf-8'),
                    method='POST',
                    headers={'Content-Type': 'application/json',
                             'X-Machine-Key': self.cfg['key']})
                with urllib.request.urlopen(req, timeout=10) as r:
                    resp = json.load(r)
                self.last_ok = time.time()
                self.error = None
                acked = []
                for cmd in resp.get('commands') or []:
                    try:
                        if self._apply(cmd):
                            acked.append(cmd.get('id'))
                    except Exception as e:  # noqa: BLE001 - one bad command
                        print(f"[CLOUD] command {cmd.get('type')} failed: {e}")
                        acked.append(cmd.get('id'))   # ack anyway: don't loop
                self._ack = acked
            except Exception as e:    # noqa: BLE001 - portal unreachable
                self.error = str(e)
            time.sleep(interval)
