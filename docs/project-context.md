# sCure_01 — Project Context (brownfield map)

> Purpose: give the Architect, Developer and Reviewer agents a verified map of the **existing** system so every change starts from *what is already there*. This is a map, not a spec — verify a symbol before relying on it. Product requirements live in `docs/sCure_SRS.html`; UI source of truth is `design-handoff/sCure-UI.html`; the CSV data contract is `docs/CSV_Import_Guide.html`.
>
> Verified 2026-08-17 against branch `refactor/clean-architecture` (baseline `main` = 4e75eb0). Refactor plan: `_bmad-output/planning-artifacts/refactor-architecture-plan.md`.

## 1. What the product is

**sCure Box** — a post-processing enclosure for 3D-printed parts (Stratasys/Origin ecosystem). Runs a controlled **Drying → Heating → Curing (405 nm) / Bleaching (450 nm) → Cooling → N₂ purge** workflow on a Raspberry Pi with an 800×480 touch kiosk. Process state syncs (outbound-only) to a small cloud portal.

## 2. Architecture (three layers, one repo)

```
src/  (React 19 + TS 5.9 + Vite 8 + Tailwind 4 + shadcn)   — kiosk HMI, fixed 800x480, dark-only
   │  fetch + polling only (GET /api/state @1 s). No WS/SSE.
server/app.py  (Python 3, Flask 3.1)                        — REST routes + wiring only; serves dist/
   ├ server/hardware_controller.py  HardwareController facade: IOBridge (real) → built-in simulation
   ├ server/storage.py              JSON-file persistence (server/data/, SCURE_DATA_DIR), CureFileStore, ComponentCounters
   ├ server/cloud_sync.py           CloudSync outbound agent (deps injected by app.py)
   ├ server/db.py (optional PostgreSQL), server/updater.py (signed USB updates)
server/io_bridge.py  (IOBridge, StatusLeds)                 — maps API ops → io_controller, door watchdog, RGB status
io_controller/  (Python 3)                                  — IOController → SystemController → TemperatureController / CoolingController
   │  smbus2 / gpiozero / lgpio / pinctrl / neopixel; all tuning in io_controller/components.json
hardware: PCA9685 (PWM: fans, heater, LEDs), TCA6424A (motors/valves/door magnet), ADS1115 + NTC (temps),
          servo damper, fan tachs, RGB strip, door sensor GPIO27, UV SSRs GPIO16/20 + routing GPIO17
```

Also: `cloud/portal.py` (Flask + SQLite portal, Fly.io), `qa-tool/index.html` (browser QA harness, ~200 declarative tests against the running server), `tools/*.mjs` (build/screenshot/diagram/SBOM helpers), `scripts/` (Pi setup/start/kiosk, systemd unit, Windows launcher).

**Hardware resolution in `server/hardware_controller.py` `HardwareController`:** `IOBridge` (real board) → built-in thermal **simulation** (`hwSource: 'simulation'`). Off-Pi the whole stack runs in simulation; the UI additionally simulates ramps/cooling when `!hw.apiConnected`.

## 3. Where things are (frontend `src/`)

| Area | File | Notes / reusable exports |
|---|---|---|
| Entry / providers / 800×480 scaling | `src/main.tsx` | `DESIGN_W/H`, `fitToScreen()`, HashRouter on `file:` |
| Gates + routes | `src/App.tsx` | order: loading → asleep(WakeScreen) → booting(BootScreen) → setup → screensaver; routes `/`, `/cure-process`, `/settings`, `/network`, `/alerts`, `/cure-history` |
| Theme / kiosk CSS | `src/index.css` | CSS vars under `:root` + `@theme inline`; no tailwind.config |
| **All hardware/system HTTP calls** | `src/services/hardware-api.ts` | one function per endpoint; dev fallback `{ok:true,'Simulated in dev mode'}`; `DEV_BLOCKED` list; `UpdatePackage`, `fetchUpdatePackage` |
| Live hardware state (1 s poll) | `src/context/HardwareContext.tsx` | `useHardware()`, `HardwareState`, `HardwareFaults` |
| Alerts / error registry | `src/context/AlertsContext.tsx` | `useAlerts()`, `triggerAlert`; cross-layer bus: `window.dispatchEvent(new CustomEvent('scure-alert',{detail:{code}}))`; registry `public/config/errors.json` |
| Programs (presets + user), CSV | `src/context/MaterialContext.tsx` | `useMaterials()`, pure `parseCsv()`, `stepsToCsv()`, `CsvParseResult`; types `Material`, `CureStep`, `TimerMode`, `UvStartMode`, `CoolingMode`; favorites in localStorage |
| Cure runs / telemetry | `src/context/CureHistoryContext.tsx` | `useCureHistory()`: `startCure/completeCure/abortCure/errorCure/recordTelemetry`; `CureLog`, `TelemetrySample` |
| Print jobs | `src/context/PrintHistoryContext.tsx` | `usePrintHistory()`, `recentLogs`, `removeLogs` |
| Device config / org / setup flag | `src/context/SystemConfigContext.tsx` | `useSystemConfig()`, `completeSetup`, `resetSetup` |
| **Cure state machine** | `src/pages/CureProcessPage.tsx` | `commandPhase()`, 250 ms `tick()`, ramp/N₂/cooling sim, door-abort, stall detection, telemetry every 5 s |
| Home / start cure | `src/pages/HomePage.tsx` | `handleStartCure()` |
| Settings (manual hardware, update, org, sleep) | `src/pages/SettingsPage.tsx` | uses `UpdateModal`, `VersionsModal`, `ComplianceModal` |
| Network | `src/pages/NetworkPage.tsx` | 3 s poll of `/api/network/status` |
| History / reports | `src/pages/CureHistoryPage.tsx` + `src/lib/cure-report.ts` | `generateCureReport(log)` (HTML report → DB + USB, browser fallback) |
| Setup wizard | `src/pages/SetupPage.tsx` | name via `OnScreenKeyboard`, org UUID from CSV on USB |
| Compliance / SHA-256 | `src/lib/compliance.ts` | `sha256Hex`, `verifyUpdatePackage`, `COMPLIANCE_*` tables |
| `cn()` | `src/lib/utils.ts` | |
| Reusable components | `src/components/` | `CircularGauge`, `PhaseCard`, `OnScreenKeyboard` (portal), `AbortModal`, `MaterialItem`, `TopBar`, `WakeScreen`, `BootScreen`, `SCureLogo`, modals `CsvBuilderModal`, `ImportCsvModal`, `PrintHistoryModal`, `UpdateModal`, `VersionsModal`, `ComplianceModal` |
| shadcn primitives | `src/components/ui/` | `button`, `badge`, `dialog`, `select`, `input`, `progress`, `switch`, custom touch input `touch-number.tsx` (`TouchNumber`) |
| **Process limits (single source)** | `src/lib/limits.ts` | `HEAT_MIN_TEMP`, `NO_HEAT_MIN_TEMP`, `HEAT_MAX_TEMP`, `COOL_MIN/MAX_TEMP`, `NO_HEAT_FLOOR`, `UV_MIN/MAX`, `TIME_MAX_MIN(_BLEACH)`, `isHeatType()`, `isUvProcess()` — used by `parseCsv`, `CsvBuilderModal`, `CureProcessPage`. Server-side hardware limits differ by design (`server/app.py` validation constants). |
| Offline demo data | `src/data/demo-data.ts` | `DEMO_PRESETS`, `DEMO_USER_PROGRAMS`, `DEMO_PRINTS` |
| Static config | `public/config/{system,errors,versions}.json`, `public/materials/`, `public/compliance/sbom.json` | |

Cleaned up in the 2026-08 refactor: step-type unions come from `MaterialContext` (`ProcessType` exported), limits from `src/lib/limits.ts`, one `API_BASE` exported from `hardware-api.ts`; the unreachable `/material-editor` page (`MaterialEditorPage`/`StepCard`/`StepModal`), `StartCureButton`, `SectionHeader`, unused shadcn primitives and `src/assets/*` were removed (recoverable from git commit `32997e0`, folder `Not_Relevant/`). Demo user programs / prints load only in `import.meta.env.DEV`; `DEMO_PRESETS` remains the production preset fallback (no-DB deployments get 503 from `/api/materials/presets`).

## 4. Where things are (backend)

| Area | File | Reusable symbols |
|---|---|---|
| Flask app, all routes + wiring | `server/app.py` (~900 lines) | routes, `run()`, IOBridge probe, `_hw_result`, `_valid_heat_temp/_valid_cool_temp/_valid_intensity`, `_on_device()`, `_db_on`, `_make_cloud_sync()`, atexit registrations |
| Hardware facade + simulation | `server/hardware_controller.py` | `HardwareController` (tiers: IOBridge → simulation), `SIM_*` constants, `COOLING_MODE_PWMS` |
| JSON persistence | `server/storage.py` | `DATA_DIR` (env `SCURE_DATA_DIR`), `load_json_file/save_json_file` (atomic tmp+fsync+replace), `load_user_materials/save_user_materials`, `CureFileStore`, `ComponentCounters(path, get_state)` |
| Cloud agent | `server/cloud_sync.py` | `CloudSync(data_dir, get_state, counters, get_programs, put_programs, get_prints, put_prints, list_cures)` |
| API ↔ hardware bridge | `server/io_bridge.py` | `IOBridge` (heat/dry/cure/cool/nitrogen/bofa/stop_all/door_abort/shutdown, fan-group mapping `led_cooling`/`chamber_intake`/`chamber_heating`), `StatusLeds` (RGB status thread = door watchdog 10 s + internet probe) |
| PostgreSQL layer (optional) | `server/db.py`, `server/db/schema.sql`, `seed_*.sql` | `available()`, `get_materials`, `replace_user_materials`, `get_print_history`, `replace_print_history`, `get_cure_history`, `start_cure_run`, `finish_cure_run`, `record_telemetry`, `save_report`, `get_report` |
| USB update | `server/updater.py` | `find_usb_mount` (also used by CSV/report/log export), `find_update_package`, `verify_signature` (RSA-SHA256 vs `/opt/scure/keys/scure-update.pub`), `extract_and_verify`, `install_update`, `run_update` |
| Windows desktop wrapper | `server/desktop.py` | Flask thread + pywebview |
| Raw devices + safety policy | `io_controller/io_controller.py` | `PCA9685`, `TCA6424A`, `ADS1115`, `Servo`, `FanTach`, `RGBLeds`, `IOController` (`read_temp`, `snapshot`, `_chamber_corrected`), `SystemController` (`startup_safe`, `enable_heater`/`disable_heater`, `heater_health_check`, `door_open`, `door_interlock`, `set_door_magnet`, `select_mode`, `set_led_brightness`, `all_leds_off`, `read_rpm`, `start_cooling/stop_cooling`), verification primitives `set_and_verify`, `verify_each`, `VerificationError`; GPIO helpers `set_gpio_level`, `gpio_set_signal[_verified]`, `door_is_open`; NTC math `ntc_voltage_to_resistance`, `ntc_resistance_to_temp`; `load_component_config` |
| Heater control loop | `io_controller/temperature_control.py` | `TemperatureController` (PI + delta-sigma @50 ms, `start/set_target/stop/shutdown/status`, fan run-on) |
| Cooling | `io_controller/cooling_mode.py` | `CoolingController` (fast/medium/slow fixed duties, auto-stop at target) |
| Structured log | `io_controller/system_log.py` | `log`, `recent(n)`, `export(dest)`, `clear()` |
| Tuning (no code change needed) | `io_controller/components.json` | re-read on each activation |
| Cloud portal | `cloud/portal.py` | Flask+SQLite, `POST /api/agent/sync` (machine key), data-only commands |
| Removed (git history only) | `git show 32997e0:Not_Relevant/` | legacy standalone drivers/dashboards, C++ driver, bench-analysis scripts, UI prototypes — deleted 2026-08-18; recover from history if ever needed |

**API surface (all JSON, error shape `{ok, code, message}`)** — state `GET /api/state`; cure steps `POST /api/cure/{heat,dry,cure-405,cure-450,cool,nitrogen,stop}`; manual `POST /api/chamber/temperature|stop`, `/api/fans/<fan>`, `/api/damper/open|close`, `/api/uv`, `/api/bofa`, `/api/rgb`, `/api/door/open`, `/api/door-abort/ack`; diagnostics `POST /api/diagnostics/fan-test|led-test`; data `GET/POST /api/materials/user`, `GET /api/materials/presets`, `GET/POST /api/print-history`, `GET /api/cure-history`, `POST /api/cure-runs/<id>/{start,telemetry,finish,report,phase}`, `GET /api/phase-timings`; system `GET /api/system/version`, `POST /api/system/{reboot,shutdown,datetime,update,export-logs,export-csv,export-report}`, `GET /api/system/update/{manifest,package}`; network `GET /api/network/status`, `POST /api/network/{static,diagnostics}`; cloud `POST /api/cloud/config`. Full list with semantics: read `server/app.py` route decorators.

**Persistence:** default JSON files under `server/data/` (gitignored, atomic writes): `user_materials.json`, `print_history.json`, `cure_history.json`, `cure_reports.json`, `phase_timings.json`, `component_counters.json`, `cloud.json`. PostgreSQL when `DATABASE_URL` is set (schema in `server/db/schema.sql`).

**Error codes** are centralized in `public/config/errors.json` (UI) and used by the server: 6015 command refused, 6016 door abort, 7001–7005 thermal/params, 9080–9089 USB/system/API (9081 no USB, 9082 write failed, 9089 API unreachable). Add new codes there, never inline.

## 5. Main execution flows (trace these before changing anything nearby)

1. **Boot (Pi):** `scripts/scure.service` → `server/app.py` → `IOBridge` → `SystemController.startup_safe()` → threads (`StatusLeds`, damper watch, `ComponentCounters`, `CloudSync`) → Flask :3001 serves `dist/`; `scripts/pi-kiosk.sh` opens Chromium kiosk. Windows: `scripts/win-start.bat` → `server/desktop.py`. Frontend: `main.tsx` providers → `App.tsx` gates → `BootScreen` → `SetupPage` (first run) → `HomePage`.
2. **Start cure:** `HomePage.handleStartCure()` (or `PrintHistoryModal`) → `navigate('/cure-process')` → `CureProcessPage` auto-start → `startCure()` (`POST /api/cure-runs/<id>/start`) → per phase `commandPhase()` → `hardware-api.ts` → `/api/cure/*` → `HardwareController` → `IOBridge` → `SystemController`/`TemperatureController`/`CoolingController` → 1 s state poll drives the UI; telemetry every 5 s; `reportPhaseEnd()`; end → `stopCureOutputs()` → `/api/cure/stop` → `completeCure()` → report via `generateCureReport`.
3. **Safety:** door open → UI 10 s grace + server `StatusLeds` watchdog → `IOBridge.door_abort()` (all outputs off, `doorAborted:true`) → UI alert 6016 → `POST /api/door-abort/ack`. Heater pre-flight (`enable_heater`) and 10 s `heater_health_check`. Temperature-stall check in UI (5 min × 5).
4. **Programs / CSV:** `CsvBuilderModal` / `ImportCsvModal` → `parseCsv()`/`stepsToCsv()` (`MaterialContext`) → `POST /api/materials/user` (full replace) → `server/data/user_materials.json` or Postgres. Format rules: `docs/CSV_Import_Guide.html`.
5. **Update:** `tools/build-update.sh <ver>` (signs with `keys/scure-update.key`) → `.scu` on USB → `UpdateModal` (`verifyUpdatePackage` SHA-256) → `POST /api/system/update` → `updater.run_update()` (verify sig → `install.sh --pre/--post`, rollback on failure).
6. **Cloud:** `CloudSync` thread POSTs snapshots to `cloud/portal.py` `/api/agent/sync`; applies data-only commands. Never actuates hardware from the cloud.

## 6. Conventions that matter

- **Frontend:** function components + hooks; contexts named `XContext.tsx` exporting `XProvider` + `useX()` (throws outside provider); `@/` alias; `import type`; props interface `<Component>Props` above the component; page-local helpers at the bottom of the page file; modals controlled by `isOpen/onClose`; every interactive element `touch-manipulation`; sizes tuned for 800×480 (`text-[10px]`, `h-7`, 44–48 px touch targets); dense "why" comments — keep them. Every network call: `try/catch` + `AbortSignal.timeout(...)`, degrade to `{ok:false,message}`/demo data — never throw to the UI. User-visible errors go through the alert registry codes. English only, no i18n by design (`translate="no"`).
- **Backend:** PEP 8, no type hints (docstrings carry contracts), hardware ops return `(ok, reason)` tuples, HTTP returns `{ok, code, message}`; API JSON keys camelCase, Python/SQL snake_case (convert at bridge/db boundary); broad `except Exception:  # noqa: BLE001` only with a justification comment; daemon threads + `threading.Event`, `sys.lock` for the shared I²C bus; atomic file writes idiom; configuration over code (`components.json`, defaults dicts merged, `_`-prefixed keys are comments); **process modules own no hardware — act only through `SystemController` verified functions**; every actuator write is read back (`set_and_verify`).
- **Logging:** `print('[TAG] ...')` to stdout/journald in server; `system_log.log()` in io_controller.

## 7. Verification available

- Frontend: `npm run build` (= `tsc -b && vite build`, typecheck included), `npm run lint`, and `npm test` (vitest: `src/**/*.test.ts` — pure logic: limits, parseCsv/stepsToCsv) are the gates. Manual: `npm run dev` (simulation), `tools/open-app.mjs`, `tools/shoot.mjs` (screenshots).
- Backend: `python -m pytest` (`server/tests/`, `io_controller/tests/` — Flask test client in simulation with `SCURE_DATA_DIR` temp dir, storage, pure io_controller functions); `python -m py_compile server/*.py io_controller/*.py`; run `python server/app.py` off-Pi (simulation mode) and hit endpoints; `qa-tool/index.html` against `http://localhost:3001`; on-device CLIs `python3 io_controller/io_controller.py status|safe|...`, `temperature_control.py <target>`, `cooling_mode.py`; in-app diagnostics `/api/diagnostics/fan-test|led-test`.
- Design/single-file build: `npx vite build --config vite.config.singlefile.ts` → `design-handoff/_singlefile/`.

## 8. Repository state (important)

- `main` = baseline commit `4e75eb0` (import of the working software); earlier commits are an unrelated prototype. Refactor work is on `refactor/clean-architecture`.
- **Secrets in the working tree (gitignored, never commit):** `keys/scure-update.key` (RSA-4096 update signing private key) and `.mcp.json` (contains a live OAuth token — rotate it).
- Not committed by design: `server/data/`, `cloud/portal_config.json`, `cloud/data/`, `dist/`, `node_modules/`, `_bmad/render/`, `*.user.toml`.
- Windows dev Python is 3.14 (`C:\Python314`); Pi uses system python3 with `--system-site-packages` venv; cloud container is 3.12.
