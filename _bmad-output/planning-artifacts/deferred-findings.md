# Deferred findings — sCure Box refactor (2026-08-17)

Items surfaced by QA / Performance / Architect that were **deliberately not changed** in the refactor because they need an owner decision, on-device measurement, or change product behavior. None block the merge; each is small and localized when picked up.

| # | Source | Item | Why deferred | Suggested action |
|---|---|---|---|---|
| D1 | Perf P7 | `src/pages/CureProcessPage.tsx:327-354` — temperature-stall check interval restarts on every `hw.chamberTemp` change, so the 5-min stall warning is effectively unreachable. | Enabling it changes runtime UX (a blocking Continue/Abort modal during a real cure). Product decision + on-device test. | Hold `hw.chamberTemp` in a ref inside the interval; verify on the machine with a deliberately blocked heater. |
| D2 | Perf P3 | `server/app.py` `/api/network/status` spawns ~6 subprocesses every 3 s while the Network page is open. | Fix reads `/sys/class/net/eth0/*` + one `ip -j addr` — Linux-only, cannot be verified off-Pi. | Implement + verify on Pi; JSON must stay identical. |
| D3 | Perf P8 | `io_controller/io_controller.py:1154-1166` shared `_rpm_last` between `/api/state` and the 10 s heater health check → occasional 1 s blocking `measure_rpm` inside the heater loop. | Touches safety-critical driver; needs bench measurement. | Separate the tach window per caller; measure on device. |
| D4 | Perf P9 | `cure_history.json` whole-file rewrite on every telemetry flush; unbounded growth. | Design change (append-only / rotation). | Cap retained runs or move telemetry to per-run files. |
| D5 | Perf P10 | `ComponentCounters` performs a full hardware `get_state()` every 2 s (I²C reads). | Needs on-device CPU/I²C measurement. | Sample from the cached last `/api/state` snapshot instead. |
| D6 | Perf P11 | Door read = `pinctrl` subprocess (~3.5 forks/s idle). | Driver change (lgpio) — safety path. | Bench-verify lgpio edge read, then swap. |
| D7 | QA-6 | Blank Cooling temperature in CSV defaults to 25 °C, below UI `COOL_MIN_TEMP=30` (server accepts ≥20). | Product rule ambiguity. | Decide default (30?) or reject blank; then update `parseCsv` + CSV guide. |
| D8 | Architect L9 / W3 | `scripts/pi-setup.sh:15` clones `sCure-A`; `tools/build-update.sh` installs to `/opt/scure` with services `scure-api`/`scure-ui` that `pi-setup.sh`/`scure.service` never create. | Owner decision: canonical repo URL and deployment layout for field updates. | Align `build-update.sh`/`updater.py` with `scure.service` + `APP_DIR` before first field update. |
| D9 | QA-3 | SIGTERM handler added in `server/app.py __main__` so `systemctl stop` runs atexit (outputs OFF, counters flush). | Implemented, but only structurally verified off-Pi. | On device: `systemctl stop scure.service` while heating → journal shows io_bridge shutdown + `[COUNTERS]` flush. |
| D10 | Perf | `qa-tool/index.html` and on-device smoke (hwSource `io_controller`, heat → door open → abort → ack) not run in this session. | Requires the machine. | Run before release. |
| D11 | Repo | `.claude/settings.local.json` contains stale allow-list entries pointing at the sibling `sCure-A` repo; `.mcp.json` holds a live token (now gitignored). | Personal config / secret hygiene. | Clean up; rotate the token. |
