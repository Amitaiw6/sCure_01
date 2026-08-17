# sCure Box — Performance & Code-Efficiency Review

Branch `refactor/clean-architecture`, reviewed 2026-08-17 against the working tree. Scope: active code only (`src/`, `server/`, `io_controller/{io_controller,temperature_control,cooling_mode,system_log}.py`). Target: Raspberry Pi CM5, Chromium kiosk 800x480, Flask API (`app.run`, threaded dev server), Python hardware threads.

Every claim below was verified by reading the code (file:line given). Nothing in the application code was modified by this review.

Categories: **A** = safe, clearly beneficial, small — implement now. **B** = beneficial but riskier / needs on-device measurement — defer, rationale given. **C** = looked suspicious, is fine — documented so nobody re-investigates.

Safety timings (door watchdog 1 s, heater health 10 s, temperature loop 50 ms, UI cure tick 250 ms) are **not** proposed to change anywhere in this document.

---

## 0. Steady-state budget (what actually runs per second on the device)

Measured by reading the code paths, not on hardware:

| Source | Cadence | Work per tick |
|---|---|---|
| UI `HardwareContext` poll `GET /api/state` (`src/context/HardwareContext.tsx:139,200`) — the **only** `/api/state` poller in `src/` (grep) | 1 Hz | Flask request → `IOBridge.get_state()` |
| `IOBridge.get_state()` (`server/io_bridge.py:352-429`) | per call | 5 ADS1115 reads (chamber + 4 LED thermistors, ~10 ms each: single-shot @128 SPS polled every 2 ms, `io_controller.py:412-425`) + **1 `pinctrl get` subprocess** for the door (`io_controller.py:986-996 → 609-615 → 569-574`) + 3 non-blocking tach deltas |
| `ComponentCounters._run` (`server/storage.py:270-282`, `TICK = 2.0`) | 0.5 Hz | full `hw.get_state()` again (same 5 ADS reads + 1 subprocess) |
| `StatusLeds.run` (`server/io_bridge.py:232-275`) | 8.3 Hz (`chase_sec` 0.12) | pure Python; every `status_sec`=1 s calls `_evaluate()` → **`door_open()` twice** (`:194` and again in `_mode()` `:169`) = 2 `pinctrl` subprocesses/s; paints the strip only on change (idle) or every tick (busy comet) |
| `StatusLeds._net_watch` (`:133-155`) | every 5 s | 1–2 TCP connects, own thread |
| `IOBridge._damper_watch` (`:500-518`) | 1 Hz | dict reads only |
| `CloudSync._run` (`server/cloud_sync.py:117-143`) | every 10 s **only if `server/data/cloud.json` exists** | `get_state()` + reads programs/prints/cures + HTTPS POST |
| `TemperatureController._loop` (`io_controller/temperature_control.py:179-228`) | 20 Hz while heating | 1 ADS read (+ `_chamber_corrected` least-squares over ~1000 pts) + at most 1 PCA write when the delta-sigma output flips |
| `CoolingController._loop` (`cooling_mode.py:159-176`) | 1 Hz while cooling | 1 ADS read |
| Werkzeug access log (`app.run`, `server/app.py:904`) | 1 line per request ≥ 1 Hz | stderr → journald (Pi) / `scure-desktop.log` (Windows, `server/desktop.py:18-22`) |
| `NetworkPage` poll `GET /api/network/status` (`src/pages/NetworkPage.tsx:62-88`) | every 3 s **while the page is open** | **6 `subprocess.run(shell=True)`** = 12 processes per call (`server/app.py:121-149`) |
| UI cure page tick (`CureProcessPage.tsx:569-579`) | 4 Hz while running | `setPhaseElapsed` bails out when the second did not change (`:318`) |
| UI telemetry (`CureProcessPage.tsx:589-622`) | every 5 s while running | 1 POST + React state append |

Idle machine total: ~1.5 hardware state reads/s (~75 ms of I²C bus time), ~3.5 `pinctrl` forks/s, ~1 log line/s, one 8 Hz Python loop. This is well within a CM5. The findings below are the places where cost is paid for nothing.

---

## 1. Summary table

| # | Cat | Where | Finding | Cost | Change |
|---|---|---|---|---|---|
| P1 | **A** | `server/app.py:904` (+ `server/desktop.py:47`) | Werkzeug logs every request; `/api/state` alone = 86,400 lines/day into journald / `scure-desktop.log` (unbounded, append) | disk/journal churn, log noise | silence `werkzeug` logger to WARNING unless `SCURE_ACCESS_LOG=1` |
| P2 | **A** | `server/io_bridge.py:184-215` | Door watchdog reads the door twice per evaluation (`_evaluate` `:194`, then `_mode` `:169`) — each read is a `pinctrl` subprocess | 1 needless fork/s, forever | read once, pass into `_mode(door)` |
| P3 | **A** | `server/app.py:107-177` | `/api/network/status` spawns 6 shell subprocesses (12 processes) every 3 s while Network page is open; two are `cat` of `/sys` files, two `ip -j addr` calls read the same data | ~4 forks/s while on that page | read `/sys/class/net/eth0/{carrier,address}` with `open()`, parse eth0 from the single `ip -j addr show` result → 2 subprocesses |
| P4 | **A** | `package.json:24` | `recharts` (8.3 MB in node_modules) is imported nowhere in `src/`, `tools/`, `index.html`; not in the built bundle | install time, SBOM noise | `npm uninstall recharts`, then `npm run sbom` |
| P5 | **A** | `server/io_bridge.py:389-390` and `:399-400` | duplicate `'internetOk'` key in the `get_state()` dict literal (second wins; first is dead code with a different `None` fallback) | none (correctness/readability) | delete lines 387-390 |
| P6 | **A** | `server/storage.py:95-98` | `CureFileStore` docstring says telemetry is "one sample per second"; the UI samples every 5 s (`CureProcessPage.tsx:620`), so the 15-sample flush = every 75 s | none — misleading comment only | fix comment |
| P7 | **B** | `src/pages/CureProcessPage.tsx:327-354` | Stall-check effect has `hw.chamberTemp` in its deps → the 5-min `setInterval` is torn down and re-created (and `lastCheckTemp` reset) on **every** temperature change (≈ every 1 s poll). The stall warning can only fire if the reading stays bit-identical for 5 min. Also timer churn. | 1 interval churn/s during ramps; latent functional defect (stall detection effectively disabled) | read `hw.chamberTemp` through a ref (same pattern the telemetry effect already uses at `:586-588`) and drop it from deps. **B** because making the check work is a behavior change the owner must accept (warnings that never appeared can now appear). |
| P8 | **B** | `io_controller/io_controller.py:1154-1166` + `:1270-1272` + `server/io_bridge.py:368-370` | `SystemController.read_rpm()` keeps ONE `_rpm_last` per fan shared by all callers. `IOBridge.get_state()` (1 Hz UI + 0.5 Hz counters) resets the window for `FAN_HEATER`; the 10-s `heater_health_check` then measures over whatever tiny `dt` elapsed since the last `/api/state` (can be 10–50 ms → 0 pulses → RPM 0) and falls into the blocking 1-s `measure_rpm()` confirm inside the 50-ms heater loop | occasional 1-s stall of the PI/delta-sigma loop (heater element frozen in last state) — the docstring at `:1259-1265` already describes the symptom | in `read_rpm`, if `dt < 0.5 s` return the last computed value instead of recomputing (store it in `_rpm_last`). Needs a bench check with the real tach; do not change the 10-s health cadence |
| P9 | **B** | `server/storage.py:115-116,147-157` | `_flush_runs()` rewrites the **entire** `cure_history.json` (all runs, all telemetry) with fsync every 15 samples and on every start/finish. File grows without bound (a 2-h run ≈ 1,400 samples ≈ 150 KB); after ~200 runs that is a 30 MB atomic rewrite every 75 s during a cure. `GET /api/cure-history` also ships the whole thing to the UI at boot (`CureHistoryContext.tsx:61-63`) | growing SSD write amplification + boot-time JSON parse in Chromium | cap retained runs / move telemetry to per-run files. Design change → defer to a spec |
| P10 | **B** | `server/storage.py:247-248` + `server/hardware_controller.py:69-73` | `ComponentCounters` triggers a full hardware `get_state()` (5 ADS reads + 1 fork) every 2 s just to learn 5 booleans that are already in bridge memory | ~40 ms I²C + 1 fork every 2 s | share the last `/api/state` snapshot or add a ~0.5 s TTL cache in `HardwareController.get_state`. Cheap but touches the "every reading ≤ 1 s old" HSI rule → measure first |
| P11 | **B** | `io_controller/io_controller.py:569-574, 609-615, 986-996` | Door state is read by spawning `pinctrl` (fork+exec) — the only per-second subprocess in the system (~3.5/s idle) | ~1–2 % of a core, latency jitter | read GPIO27 via `lgpio` (already a dependency for the servo/tach) with bias disabled, or cache `door_open()` for 200 ms. Touches the door interlock read path → bench-verify polarity/pull before merging |
| P12 | **C** | `src/context/HardwareContext.tsx:155-183, 224-228` | New `state` object every poll → `TopBar` + the mounted page re-render at 1 Hz even when nothing changed; provider `value` object recreated per render | a few ms per second on an 800x480 tree | fine — the callbacks are `useCallback`-stable, siblings (`AlertsProvider`…) are element-stable so only consumers re-render; a shallow-equal bail-out would save little because `chamberTemp` jitters anyway |
| P13 | **C** | `src/pages/CureProcessPage.tsx:237-323, 569-579` | `tick` depends on `hw.chamberTemp` → the 250 ms interval is cleared/re-created after every poll during ramps | negligible; elapsed values come from `performance.now()` anchors so no drift | leave; documented so no one "fixes" it |
| P14 | **C** | `src/pages/CureProcessPage.tsx:410-459` | phase-entry effect re-runs every poll (`commandPhase`, `hw.chamberTemp` in deps) | guarded by `commandedPhaseRef` → no re-command | leave |
| P15 | **C** | `io_controller/io_controller.py:716-749` | `_chamber_corrected` least-squares over a 45-s deque (~1,000 pts at 20 Hz + 1.5 Hz) on every chamber read | measured 0.19 ms/call on a desktop → ~0.5–1 ms on CM5 × 21.6/s ≈ 1–2 % of one core | leave; O(1) running sums would change the estimate's numerics |
| P16 | **C** | `server/io_bridge.py:232-275` | RGB loop at 8.3 Hz | pure Python; strip write only on change when idle; comet paints 16–21 px at 8 Hz while a process runs — by design | leave |
| P17 | **C** | `server/app.py:98-104` | `/api/state` handler | `counters.hours()` and `cloud_sync.status()` are dict copies; cost is entirely `IOBridge.get_state()` (see P10/P11) | leave |
| P18 | **C** | `io_controller/io_controller.py:1208-1237` | `enable_heater()` sleeps 2 s + blocks 1 s (`measure_rpm`) inside the Flask request thread | intended pre-flight; Flask dev server is threaded so `/api/state` keeps flowing; UI `apiCall` timeout is 5 s (`hardware-api.ts:30`) | leave |
| P19 | **C** | `src/pages/SettingsPage.tsx:98-116` | slider debounce timeouts are not cleared on unmount | they call the API (not `setState`); worst case one late fan/temperature write ≤ 400 ms after leaving the page — same command the user requested | leave |
| P20 | **C** | `src/App.tsx:30-51` | `pointermove` listener resets a timeout on every move | trivial | leave |
| P21 | **C** | `package.json` deps | `shadcn` (used as `@import "shadcn/tailwind.css"` in `src/index.css:3`), `tw-animate-css` (`index.css:2`), `class-variance-authority` (`ui/badge.tsx`, `ui/button.tsx`), `qrcode.react` (`AlertsPage.tsx:3`), `radix-ui` (6 `ui/*` files), `@fontsource-variable/geist` (`index.css:4`) are all really imported. `puppeteer-core` and `vite-plugin-singlefile` are correctly devDependencies (`tools/*.mjs`, `vite.config.singlefile.ts`); `vitest` is used by two `*.test.ts` files | — | keep |
| P22 | **C** | `server/cloud_sync.py:70-85` | every 10 s reads all programs/prints/cures and posts them | agent is off unless `cloud.json` exists; `CureFileStore.list()` is an in-memory list copy; telemetry is stripped before sending | leave |
| P23 | **C** | `src/context/HardwareContext.tsx:139` | 1 Hz `fetch` with `AbortSignal.timeout(3000)`; `setInterval` does not wait for the previous request | at most 3 requests in flight if the server stalls; each `/api/state` is ~60–80 ms server-side | leave |

---

## 2. Details

### P1 (A) — Werkzeug per-request access log
`server/app.py:904` `app.run(host='0.0.0.0', port=port, debug=False)`. Werkzeug's `_log()` attaches a `StreamHandler` at INFO on first use (verified in the installed werkzeug source), so every request prints `127.0.0.1 - - [..] "GET /api/state HTTP/1.1" 200 -` to stderr. With the UI's 1 Hz poll that is ≥ 86,400 lines/day into journald on the Pi and into `scure-desktop.log` on Windows (`server/desktop.py:18-22`, opened in append mode, never rotated). No code reads these lines. `io_controller/system_log.py` already provides the real, rotated machine log.

Change (behavior-preserving for the API; loses only the access log, re-enable with an env var):
```python
# server/app.py, next to the other imports
import logging
if not os.environ.get('SCURE_ACCESS_LOG'):
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
```
Risk: none functionally; developers who want request tracing set `SCURE_ACCESS_LOG=1`. `desktop.py` imports `app`, so it inherits the setting.

### P2 (A) — Door read twice per watchdog tick
`server/io_bridge.py:184-215`: `_evaluate()` calls `b.sys.door_open()` (`:194`) and then `return self._mode()` where `_mode()` calls `b.sys.door_open()` again (`:169`). Both go through `SystemController.door_open()` → `read_gpio_level()` → `_pinctrl("get", pin)` = one `subprocess.run` each (`io_controller.py:569-574`). `_mode()` has no other caller (grep). Also `cooling_status()` is computed in both, but that is a dict copy.

Change:
```python
def _mode(self, door=None):
    ...
    if door is True:                    # was: b.sys.door_open() is True
        return 'door'
    ...
def _evaluate(self):
    b = self.bridge
    door = None
    try:
        door = b.sys.door_open()
        outputs_on = False
        if door is True:
            ...
    except Exception: pass
    return self._mode(door)
```
Risk: none — same value, same 1-s cadence, one read instead of two. Do not touch `door_abort_sec` / `status_sec`.

### P3 (A) — `/api/network/status` subprocess storm
`server/app.py:121-149` runs, per request: `ip -4 -j addr show eth0`, (`ip link show eth0` fallback), `cat /sys/class/net/eth0/carrier`, `cat /sys/class/net/eth0/address || echo`, `ip route | grep | awk`, `ip -j addr show`. Each `run()` is `subprocess.run(shell=True)` → `/bin/sh` + tool. `NetworkPage.tsx:44,86` polls this every 3 s while open. Six of these per 3 s is ~4 process spawns/s while the operator is on that page.

Change (identical JSON output):
```python
def _sysfs(p):
    try:
        with open(p) as f: return f.read().strip()
    except OSError: return ''
carrier = _sysfs('/sys/class/net/eth0/carrier')
info['mac'] = _sysfs('/sys/class/net/eth0/address') or '00:00:00:00:00:00'
ifaces_json = run("ip -j addr show 2>/dev/null")      # one call
# derive eth0's inet from the same parsed list instead of a second `ip -4 -j addr show eth0`
```
Risk: low; the `ip link show eth0` existence fallback for dev laptops stays as is. Off-Pi both `open()` and `ip` fail exactly as `cat`/`ip` do now.

### P4 (A) — Unused dependency `recharts`
`package.json:24` `"recharts": "^3.8.1"`. Grep over `src/`, `index.html`, `tools/`, `vite.config*.ts`, `eslint.config.js`: no import. Not present in `dist/assets/index-*.js` (0 matches). It only appears in the generated SBOMs (`public/compliance/sbom.json:160`, `dist/…`, `design-handoff/…`).
Change: `npm uninstall recharts` then `npm run sbom` (regenerates `public/compliance/sbom.json`). Risk: none.

Verdicts on the other names asked about: `qrcode.react` — used (`src/pages/AlertsPage.tsx:3` `QRCodeSVG`); `shadcn` — used at runtime as CSS (`src/index.css:3` `@import "shadcn/tailwind.css"`; the 5.3 MB CLI JS is not bundled); `tw-animate-css` — used (`src/index.css:2`); `class-variance-authority` — used (`src/components/ui/badge.tsx`, `button.tsx`); `puppeteer-core` — devDependency, used only by `tools/open-app.mjs`, `tools/shoot.mjs`, `tools/srs-to-word.mjs` (correct placement).

### P5 (A) — Duplicate dict key in `IOBridge.get_state()`
`server/io_bridge.py:389-390` sets `'internetOk': (bool(...) if self.status_leds else None)` and `:399-400` sets `'internetOk': (self.status_leds._internet_ok if self.status_leds else True)`. Python keeps the last one, so the first is dead and its `None`-when-no-thread fallback (which the comment at `:387-388` documents) never applies. Delete `:387-390` (keeps current behavior exactly) — or keep the first and delete the second if the `None` semantics were the intent; either way one line, no runtime cost, but it removes a trap.

### P6 (A) — Stale comment
`server/storage.py:95-98`: "telemetry (one sample per second during a run) flushes every TELEMETRY_FLUSH_EVERY samples so the SSD is not rewritten every second". The UI samples every 5 s (`CureProcessPage.tsx:620`), so the flush is every 75 s. Fix the comment so nobody tunes `TELEMETRY_FLUSH_EVERY` against a wrong assumption.

### P7 (B) — Stall-check interval is reset by every poll
`src/pages/CureProcessPage.tsx:327-354`:
```ts
useEffect(() => {
  ...
  lastCheckTemp.current = hw.chamberTemp
  stallCheckRef.current = setInterval(() => { ... hw.chamberTemp ... }, STALL_CHECK_INTERVAL)
  return () => { clearInterval(...) }
}, [isInTempPhase, showTempWarning, hw.chamberTemp, activePhase, phases])
```
`hw.chamberTemp` changes at nearly every 1-s poll during a ramp/cool (0.1 °C resolution), so the 5-min timer restarts every second and `lastCheckTemp` is reset to "now". The 5-min callback can only run when the reading is bit-identical for 300 s. Result: the stall warning is effectively unreachable on real hardware, and there is 1 interval teardown/creation per second. The telemetry effect right below (`:581-588`) already documents and solves the same trap with a snapshot ref.

Change (≤ 10 lines): keep `hw.chamberTemp` in a ref (`tempRef.current = hw.chamberTemp` on every render), remove it (and `phases`/`activePhase` via a ref for the cooling flag) from the deps, read `tempRef.current` inside the interval. **Category B**: performance gain is trivial; the real effect is that the stall warning starts working, which is a user-visible behavior change that needs owner sign-off (and MAX_TEMP_RETRIES/interval values may then need tuning against real ramp rates).

### P8 (B) — Shared tach delta window between `/api/state` and the heater health check
`io_controller/io_controller.py:1154-1166` `read_rpm(fan)` computes RPM from `(count - prev_count) / (now - prev_time)` and overwrites `_rpm_last[fan]` on every call, whoever the caller is. `IOBridge.get_state()` (`server/io_bridge.py:368-370`) calls it for `FAN_LEFT`, `FAN_COOLING`, `FAN_HEATER` at ~1.5 Hz (UI + counters). `heater_health_check()` (`:1270`) then calls `read_rpm(FAN_HEATER)` every 10 s: its `dt` is "time since the last `/api/state`", uniformly anywhere in 0–~0.7 s. With 2 pulses/rev at ~2,800 rpm (~93 pulses/s), a `dt` of 20 ms has a ~15 % chance of 0 pulses → RPM 0 < `min_fan_rpm` 100 → the code takes the blocking `measure_rpm()` 1-s confirm (`:1272`) inside the 50-ms control loop. Rough integrated probability ≈ 1–2 % per check → about once per 10 min of heating, the PI/delta-sigma loop freezes for 1 s with the element in its last state. The docstring at `:1259-1265` describes exactly this glitch and its mitigation, so the confirm step must stay.

Change (measurement-quality only, cadence untouched):
```python
def read_rpm(self, fan):
    ...
    dc, dt = cnt - prev[0], now - prev[1]
    if dt < 0.5 and len(prev) > 2:      # window too short: reuse last value
        self._rpm_last[fan] = prev
        return prev[2]
    rpm = (dc / PCA_PULSES_PER_REV) * (60.0 / dt) if dt > 0 else None
    self._rpm_last[fan] = (cnt, now, rpm)
    return rpm
```
Risk: touches the heater health path (not its timing). Verify on the bench that a stopped fan is still caught within one 10-s check (it is: after 0.5 s the delta is recomputed and reads 0). Defer until it can be exercised on the device.

### P9 (B) — Whole-history rewrite and unbounded growth
`server/storage.py:115-116` `_flush_runs()` = `save_json_file(CURE_HISTORY_FILE, self.runs)` (tmp + fsync + replace of everything). Called on start, finish, and every 15 telemetry samples (`:154-156`). Nothing prunes `self.runs`, so both the on-disk file and the boot-time `GET /api/cure-history` payload (`CureHistoryContext.tsx:61-63` loads it into React state; `CureHistoryPage`/`cure-report.ts` need telemetry for reports) grow with every run. Today (fresh `server/data/`) it is empty; after a year of daily runs it is tens of MB rewritten every 75 s during a cure and parsed by Chromium at every boot. Defer to a small spec: retention cap (e.g. keep N runs / M days) and/or per-run telemetry files. Not urgent; flagged so it is planned before field deployment.

### P10 (B) — `ComponentCounters` does its own hardware read
`server/storage.py:247-248` `_sample()` → `self._get_state()` = `HardwareController.get_state()` → `IOBridge.get_state()` (5 ADS reads + 1 `pinctrl` fork) every 2 s, only to derive 5 booleans (`uvOn`, `uvWavelength`, `isHeating`, `heaterOut/heaterPwm`, fan RPM/duty) that are already in bridge memory or in the last `/api/state`. Combined with the UI poll this makes ~1.5 full reads/s. Options: (a) 0.5-s TTL memo in `HardwareController.get_state()`; (b) counters sample a lightweight `bridge.flags()` instead. (a) risks serving up-to-0.5-s-old data to the UI (still within the 1-s HSI rule) — measure the I²C bus occupancy first; the current cost (~40 ms/2 s) is small.

### P11 (B) — `pinctrl` subprocess for every door read
`io_controller/io_controller.py:569-574` `_pinctrl()` = `subprocess.run(["pinctrl", ...], capture_output=True)`. `door_open()` (`:986-996`) is called by `get_state()` (1.5 Hz), `StatusLeds` (2 Hz, 1 Hz after P2), and on every heater/LED enable. It is the only recurring fork in the system. `lgpio` is already used for the servo (`:476-481`) and `gpiozero` for the tachs, so a claim-input read with `lgpio.SET_BIAS_DISABLE` (matching `pinctrl set <pin> ip pn`, `:651`) would replace it. Because this is the interlock sensor, polarity/pull behavior must be confirmed on the bench (`open_level`, external pull-up R46 per `:642-647`) — defer.

### P12–P23 (C) — investigated, fine
See the table. Two worth restating so nobody re-opens them:
- React tree: `main.tsx` nests six providers; `HardwareProvider`'s 1-Hz `setState` re-renders only `HardwareContext` consumers (`TopBar` + mounted page); sibling providers receive an identical `children` element and bail out. `AlertsProvider` recomputes its `value` per render, but it only renders when alerts change. No `useMemo` needed.
- Frontend timers/listeners are all cleaned up in effect returns (`HardwareContext.tsx:208-212`, `NetworkPage.tsx:87`, `CureProcessPage.tsx:353,388,576-578,621`, `AlertsContext.tsx:137`, `App.tsx:47-50`, `TopBar.tsx:41`, `BootScreen.tsx`). No `AbortController` leaks: all fetches use `AbortSignal.timeout`.

---

## 3. Suggested order
1. P1, P2, P5, P6 (server, ~10 lines total, no behavior change).
2. P4 (`npm uninstall recharts && npm run sbom`) + P3 (network status) — verify with `npm run build`, `python -m py_compile server/app.py server/io_bridge.py`, run `server/app.py` off-Pi and open the Network page.
3. Schedule P7 and P8 for the next on-device session (both are latent defects more than performance items).
4. Put P9 (history retention) and P11 (lgpio door read) on the backlog as small specs; revisit P10 only if I²C bus contention is observed.
