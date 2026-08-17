# sCure Box

Control software for the **sCure Box** — a post-processing enclosure for 3D-printed parts
(Drying → Heating → UV Cure 405 nm / Bleaching 450 nm → Cooling → N₂ purge) running on a
Raspberry Pi with an 800×480 touch kiosk. Requirements: [docs/sCure_SRS.html](docs/sCure_SRS.html).

## Repository layout

| Path | What it is |
|---|---|
| `src/` | Kiosk UI — React 19 + TypeScript + Vite + Tailwind. All HTTP calls in `src/services/hardware-api.ts`; process limits in `src/lib/limits.ts`; cure state machine in `src/pages/CureProcessPage.tsx`. |
| `server/` | Flask API (`app.py` routes + wiring, `hardware_controller.py` real/simulated facade, `storage.py` JSON-file persistence, `cloud_sync.py` outbound cloud agent, `io_bridge.py` API→hardware mapping + door watchdog, `updater.py` signed USB updates, `db.py` optional PostgreSQL). |
| `io_controller/` | Hardware drivers and safety policy: `io_controller.py` (`IOController`, `SystemController`), `temperature_control.py`, `cooling_mode.py`, `system_log.py`; all tuning in `components.json`. |
| `cloud/` | Cloud portal (Flask + SQLite), separately deployed (Fly.io). |
| `scripts/` | Pi setup/start/kiosk scripts, `scure.service`, Windows launcher. |
| `tools/` | Dev tooling: update-package builder, SBOM, screenshot/diagram helpers, error-registry editor. |
| `public/config/` | `errors.json` (error registry), `versions.json` (release notes), `system.json`. |
| `qa-tool/` | Browser QA harness (~200 checks) run against a live server. |
| `docs/`, `design-handoff/` | SRS, CSV import guide, diagrams; designer package (single-file UI build). |

## Running

- **Windows (dev/demo, simulation):** double-click `scripts\win-start.bat` — creates the venv, builds the UI once, opens the app fullscreen (Flask in-process). Alt+F4 closes.
- **Raspberry Pi (the machine):** once `bash scripts/pi-setup.sh`; afterwards every boot starts `scure.service` (API on :3001) and the Chromium kiosk. Manual: `bash scripts/pi-start.sh`.
- **Developer loop:** `python server/app.py` (simulation off the Pi) + `npm run dev` (Vite on :5173, calls `http://localhost:3001/api`; override with `VITE_HW_API_URL`).

Off the Pi the whole stack runs in simulation (`GET /api/state` → `hwSource: "simulation"`); the UI additionally simulates ramps when the API is unreachable. Simulated success is not hardware verification.

## Build, verify, release

```
npm run build        # tsc -b + vite build → dist/  (served by Flask)
npm run lint         # eslint
npm test             # vitest (frontend pure logic)
python -m pytest server/tests io_controller/tests   # backend in simulation
python -m py_compile server/*.py io_controller/*.py
```
Then open `qa-tool/index.html` against a running server for the end-to-end checks.

Release: bump `VERSION` (single source of truth, read by `GET /api/system/version`) **and** add an entry to `public/config/versions.json`; `npm run sbom` refreshes `public/compliance/sbom.json`; `tools/build-update.sh <version>` builds a signed `.scu` update package (signing key in `keys/`, never committed).

## Configuration & data

- Hardware tuning: `io_controller/components.json` (re-read on every activation, no restart).
- Machine data (programs, print/cure history, reports, counters): `server/data/*.json` (gitignored; override with `SCURE_DATA_DIR`), or PostgreSQL when `DATABASE_URL` is set (`server/db/schema.sql`).
- Cloud agent: `server/data/cloud.json` (written by `POST /api/cloud/config`).
- Logging: per-request access log is off by default (1 Hz polling would flood journald); set `SCURE_ACCESS_LOG=1` to enable.
- Error codes: `public/config/errors.json` — add codes there, never inline.

## Safety notes

All interlocks live in `SystemController` (`io_controller/io_controller.py`): door interlock and 10 s door-abort watchdog (`server/io_bridge.py` `StatusLeds`), heater pre-flight (door closed, heater fan RPM verified, thermistor valid) and 10 s health check, verified actuator writes (`set_and_verify`), fan run-on after heating. Process modules and the server never write PCA/GPIO directly. Do not change these paths without on-device verification.

## For contributors / AI agents

Read `AGENTS.md` (policy + workflow) and `docs/project-context.md` (architecture and reuse map). Development follows the BMAD workflow: analyse → plan → implement → simplify → test → review.
