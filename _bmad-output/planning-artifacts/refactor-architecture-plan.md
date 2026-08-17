# sCure Box — Refactor / Cleanup Architecture Plan

Branch `refactor/clean-architecture`, baseline commit `4e75eb0`. Verified against the working tree on 2026-08-17 (every claim below carries a `file:line` or a grep result). Scope: reorganize, de-duplicate, park legacy/unused code under `Not_Relevant/`, prepare a production-quality kiosk codebase. **No new features. Safety behavior unchanged.**

Read first: `docs/project-context.md` (system map), `AGENTS.md` (policy). This plan does not repeat them.

---

## 1. System summary & main flows

Three layers in one repo (see `docs/project-context.md` §2, §5):

- `src/` React 19 + TS + Vite kiosk HMI (800×480, dark) → polls `GET /api/state` at 1 s; all commands through `src/services/hardware-api.ts`.
- `server/app.py` Flask API (routes + `HardwareController` facade/simulation + JSON-file store + `ComponentCounters` + `CloudSync` + updater glue) → `server/io_bridge.py` (`IOBridge`, `StatusLeds` door watchdog) → `io_controller/` (`IOController`/`SystemController`, `TemperatureController`, `CoolingController`, `system_log`, tuning in `components.json`).
- `cloud/portal.py` outbound-only portal (separate deployable, Fly.io).

Deployment: `scripts/pi-setup.sh` → venv + `npm run build` + `scripts/scure.service` (runs `server/app.py` from `APP_DIR`) + `scripts/pi-kiosk.sh` (Chromium kiosk). Windows: `scripts/win-start.bat` → `server/desktop.py`. Update packages: `tools/build-update.sh` → `.scu` → `server/updater.py`.

Main flows to keep intact: Boot, Start-cure (`CureProcessPage.commandPhase()` → `/api/cure/*` → `IOBridge` → `SystemController`), Safety (door open → `IOBridge.door_abort()` / `StatusLeds` watchdog / UI 6016 / `POST /api/door-abort/ack`; heater `enable_heater` pre-flight + `heater_health_check`), Programs/CSV (`parseCsv`/`stepsToCsv` in `MaterialContext`), Update, Cloud sync.

---

## 2. Findings (evidence)

### 2.1 Duplicated logic

| # | What | Where (evidence) |
|---|---|---|
| D1 | API base URL defined 8 times; 3 contexts hardcode `http://localhost:3001` (root, no `/api`) and ignore `VITE_HW_API_URL` | `src/services/hardware-api.ts:13`; `src/components/VersionsModal.tsx:10`; `src/pages/NetworkPage.tsx:14`; `src/context/HardwareContext.tsx:130` (inside `useEffect`); `src/context/SystemConfigContext.tsx:75` (inside async fn); **root-only:** `src/context/CureHistoryContext.tsx:37`, `MaterialContext.tsx:45`, `PrintHistoryContext.tsx:24` |
| D2 | Step-type unions duplicated | `MaterialContext.tsx:4-6` (`TimerMode/UvStartMode/CoolingMode`) + `CureStep.process` inline union `:10`; `StepCard.tsx:5-9` re-declares all four incl. `ProcessType`; `CsvBuilderModal.tsx:29` declares its own local `ProcessType` |
| D3 | `HEAT_MIN_TEMP = 30` defined 3 times, `NO_HEAT_MIN_TEMP = 25` twice, `COOL_MIN_TEMP = 30` once, cooling max 75 / heat max 80 / time caps 120·720 / UV 10–100 scattered | `CureProcessPage.tsx:55`; `StepModal.tsx:40-41`; `CsvBuilderModal.tsx:125-129,152,446,482,509`; `MaterialContext.tsx` `parseCsv` (`[30,75]/[15,80]`, `720:120`) at lines ~110-141 |
| D4 | `formatDate` twice (differs only by `second:'2-digit'`) | `PrintHistoryModal.tsx:38`, `CureHistoryPage.tsx:26` — page-local helper convention; **leave** |
| D5 | Local `Card` wrappers in `NetworkPage.tsx:313` and `SettingsPage.tsx:425` while shadcn `components/ui/card.tsx` is unused | keep local wrappers (they are 3-line styled divs); park `ui/card.tsx` |
| D6 | Server validation limits vs UI limits differ intentionally (server = hardware limits `HEAT_TARGET_MIN=30, TEMP_MAX=80, COOL_TARGET_MIN=20, UV_INTENSITY_MIN=10` `server/app.py:1198-1201`; UI = product rules 30–75 cooling) | **leave**, document in `src/lib/limits.ts` header |

### 2.2 Legacy / superseded

| # | What | Evidence |
|---|---|---|
| L1 | `server/hardware/` C++ pybind11 driver (`hw_driver.cpp` 339 lines, `temperature_control.hpp`, `build.sh`) is tier-2 in `HardwareController` | `server/app.py:37-42` import; used at `:143,177,192,200,207,227,235,245,346,353,1547`. No `.so` in tree; `pi-setup.sh` never builds it; only `tools/build-update.sh:79,140-144` copies/rebuilds it. `qa-tool/index.html` checks only `hwSource === 'io_controller'` (`:1920`). Superseded by `io_bridge` (`hwSource:'io_controller'` `server/io_bridge.py:428`) |
| L2 | `io_controller/` standalone drivers & Tk dashboards | rg over repo (excluding node_modules/dist/.venv/_bmad/.claude): the only importers of `pca9685, tca6424a, analog_read, temp_monitor, servo, gpio_control, gpio_manager, pinctrl(.py), toggle_gpio, write_gpio_example, config` are each other (`dashboard.py:12-13`, `pinctrl.py:5-6`, `toggle_gpio.py:10`, `write_gpio_example.py:4`). Live modules import only each other: `io_controller.py:39,1292,1700`, `temperature_control.py:48,374,387`, `cooling_mode.py:34,247`, `server/io_bridge.py:118,307,309,324,694`. `control_dashboard.py:33`, `control_dashboard1.py:30`, `fan_control.py:23` import the **live** `io_controller` (bench tools built on it, not part of the kiosk). |
| L3 | `io_controller/README.md` describes the legacy Tk GPIO dashboard (`dashboard.py`, `gpio_manager.py`, `RPi.GPIO`, Hebrew) — not the live driver | `io_controller/README.md:6-7,18` |
| L4 | `io_controller/requirements.txt` = `RPi.GPIO, smbus2` (legacy). Live deps are in `server/requirements.txt` (`smbus2, gpiozero, neopixel`) which `pi-setup.sh:44` installs | `io_controller/requirements.txt`, `server/requirements.txt:7-9` |
| L5 | `io_controller/io_controller.cpp` (C++ twin), `HSI sCure (3)*.xlsx`, `IO BOARD SCURE.pdf`, `curebox-flow-diagram.html` — hardware reference/spec artifacts, not code | referenced by nothing (rg) |
| L6 | `scripts/*.py` bench-analysis tools (`calibrate_scure_temp, live_temp_graph, compare_delta_live, uv_led_experiment, uv_experiment_viewer, picolog_report, scure_temp_correction`) | not referenced by `pi-setup.sh`, `pi-start.sh`, `pi-kiosk.sh`, `scure.service`, `win-start.bat`, `build-update.sh`, or any `.py/.mjs`. Only cross-refs among themselves and a doc comment `io_controller/io_controller.py:128` ("scripts/calibrate_scure_temp.py"). `pi_kiosk3.py` does **not** exist in this repo (only in `.claude/settings.local.json:54` pointing at sCure-A). |
| L7 | `updates/scure-update-1.0.0.scu` tracked build artifact; version tag inconsistent with `VERSION` = 0.4.9 | `git ls-files` |
| L8 | `.claude/settings.local.json` lines 20-23,54,61 reference the sibling `sCure-A` repo (stale allow-list) — **note only, no action** | |
| L9 | `scripts/pi-setup.sh:15` `REPO_URL="https://github.com/Amitaiw6/sCure-A.git"` — clones the *other* repo when run outside a checkout | needs owner decision (see WP-R4) |

### 2.3 Unused

| # | What | Evidence |
|---|---|---|
| U1 | `src/components/StartCureButton.tsx` (13 lines) | 0 importers (import graph scan) |
| U2 | `src/assets/{hero.png,react.svg,vite.svg}` | rg `assets/` in `src/`, `index.html`: no hits |
| U3 | `src/pages/MaterialEditorPage.tsx` + `src/components/StepCard.tsx` + `src/components/StepModal.tsx` — dead cluster | route only at `src/App.tsx:7,90`; no `navigate('/material-editor')`/link anywhere (`navigate(` targets: `/`, `/alerts`, `/cure-history`, `/cure-process`, `/network`, `/settings`); `StepCard` imported only by `StepModal.tsx:2` + `MaterialEditorPage.tsx:3,9`; `StepModal` only by `MaterialEditorPage.tsx:4`; not in `docs/sCure_SRS.html` (no "editor" hits besides the doc's own in-page editor), not in `qa-tool/index.html`. Live program editor is `CsvBuilderModal` (`HomePage.tsx:4,242`). Only external ref: `tools/shoot.mjs:97` (screenshot list) and `docs/screenshots/material-editor.png`. |
| U4 | `src/components/SectionHeader.tsx` | 0 importers |
| U5 | shadcn `src/components/ui/{card,separator,touch-spinner}.tsx` | 0 importers (`badge 2, button 16, dialog 9, input 2, progress 2, select 3, switch 1, touch-number 3`) |
| U6 | `hardware-api.ts` `systemShutdown` export unused (SLEEP button uses `sessionStorage` `SettingsPage.tsx:152-155`) — **keep** (endpoint exists, one-function-per-endpoint convention, qa-tool) | |
| U7 | `src/data/demo-data.ts:1` header cites `tools/_gen-demo.mjs`, which does not exist | fix comment |
| U8 | Root/tooling clutter: `render.html`, `render-dump.html` (gitignored, regenerated by `tools/drawio-to-svg.mjs:21,32`), `scure-desktop.log`, `vite-dev.log` (gitignored), `sCure-design-handoff.zip` (tracked, duplicate of `design-handoff/`), `docs/sCure_SRS.zip` (tracked 3.6 MB), `docs/Screenshot 2026-08-05 150951.png` (unreferenced), `tools/_bold-survey.json` (one-off survey output; unreferenced) | rg: no references except `.gitignore:8-9` |

### 2.4 Weaknesses / risks found (fix only where marked)

| # | Issue | Evidence | Action |
|---|---|---|---|
| W1 | **Demo data can overwrite real machine data.** If the API is unreachable at UI start (server still booting), `loadUserMaterials()` returns `DEMO_USER_PROGRAMS` and `loadPrintHistory()` returns `DEMO_PRINTS`; the first user edit then `POST`s the demo set over `server/data/user_materials.json` / `print_history.json`. | `MaterialContext.tsx:290-296,352-360`; `PrintHistoryContext.tsx:30-36,64-69` | Fix in WP-F4: production fallback = `[]`; demo only when `import.meta.env.DEV`. **Presets are different**: on the default JSON-file deployment `/api/materials/presets` returns 503 (`server/app.py:653-658`) so `DEMO_PRESETS` *is* the production preset list — keep that fallback unconditional. |
| W2 | `hardware-api.ts:5` header says "→ C++ driver (pybind11)" — stale | update comment (WP-B1) |
| W3 | `tools/build-update.sh` install script copies only `server/app.py` + `requirements.txt` (`:74-79,131-133`), rebuilds the C++ driver (`:140-144`), targets `/opt/scure` and services `scure-api`/`scure-ui` (`:118-146`) — none of which `pi-setup.sh`/`scure.service` create (they run from `APP_DIR` as `scure.service`). The updater path is not consistent with the deployed layout today. | `tools/build-update.sh`, `server/updater.py:18-19`, `scripts/scure.service` | In scope: drop C++ block, stage whole `server/*.py` + `io_controller/{*.py,components.json}` (WP-R2). **Out of scope / flag to owner:** `/opt/scure` vs `APP_DIR` mismatch. |
| W4 | `public/compliance/sbom.json` metadata `name: scure-a-temp, version: 0.0.0` (stale); `tools/gen-sbom.mjs:29` reads `pkg.name/pkg.version`; `package.json` = `scure-a-temp@0.1.0` vs `VERSION`=0.4.9 (declared single source of truth in `server/app.py:1410-1413`, `public/config/versions.json:2`) | fix WP-R3 |
| W5 | `_DATA_DIR` hardcoded (`server/app.py:627`, `:470-472`) — no env override → tests would write into `server/data/` | add `SCURE_DATA_DIR` env override in WP-B2 (tiny, behavior-neutral) |
| W6 | `server/app.py` 1556 lines mixes 6 responsibilities (see §3) | WP-B2 split |
| W7 | ESLint `globalIgnores(['dist'])` only (`eslint.config.js:9`) — parked `.tsx` under `Not_Relevant/` would be linted | add `Not_Relevant` to ignores (WP-N0) |

---

## 3. Target architecture

### 3.1 Final layout of active code

```
sCure_01/
├─ src/                          (unchanged structure)
│  ├─ App.tsx  main.tsx  index.css
│  ├─ components/  (minus StartCureButton, StepCard, StepModal, SectionHeader; ui/ minus card, separator, touch-spinner)
│  ├─ context/    (6 contexts, unchanged names)
│  ├─ data/demo-data.ts
│  ├─ lib/  compliance.ts  cure-report.ts  utils.ts  + limits.ts  (NEW, ~25 lines: process limits + ProcessType re-export)
│  ├─ pages/      (minus MaterialEditorPage)
│  └─ services/hardware-api.ts   (exports API_BASE — the single API base)
├─ server/
│  ├─ app.py                 Flask routes + wiring only (~1000 lines)
│  ├─ hardware_controller.py NEW: SIM_* constants + HardwareController (IOBridge → simulation; C++ tier removed)
│  ├─ storage.py             NEW: DATA_DIR (+SCURE_DATA_DIR), atomic JSON helpers, user-materials/print-history files, CureFileStore, ComponentCounters
│  ├─ cloud_sync.py          NEW: CloudSync (deps injected)
│  ├─ io_bridge.py  updater.py  db.py  db/*.sql  desktop.py  requirements.txt  (unchanged)
│  └─ tests/                 (QA, §6)
├─ io_controller/
│  ├─ io_controller.py  temperature_control.py  cooling_mode.py  system_log.py  components.json  .gitignore
│  └─ README.md              rewritten (short: what the 4 live modules are, CLIs, components.json)
├─ cloud/                        (unchanged)
├─ scripts/  pi-setup.sh pi-start.sh pi-kiosk.sh scure.service win-start.bat   (python bench tools moved out)
├─ tools/    *.mjs build-update.sh error-editor.html   (_bold-survey.json moved out)
├─ qa-tool/  docs/  design-handoff/  public/  keys/ (pub only)  updates/ (gitignored, empty)
├─ Not_Relevant/  legacy/ unused/ prototypes/ development-tools/ old-implementations/   (+ README.md index)
└─ README.md (real), VERSION, package.json (scure-box), configs
```

### 3.2 Decisions (accept / reject / amend)

| ID | Decision | Rationale / evidence |
|---|---|---|
| A1 | **Accept.** Single API base = `export const API_BASE` in `src/services/hardware-api.ts:13` (value unchanged: `import.meta.env.VITE_HW_API_URL \|\| 'http://localhost:3001/api'`). All 7 other sites import it. Contexts that used the root URL switch their paths from `${API_BASE}/api/x` to `${API_BASE}/x`. | `hardware-api.ts` is already "all hardware/system HTTP calls" (project-context §3); it imports only `lib/compliance` → no cycle. No new file. |
| A2 | **Amend.** Create `src/lib/limits.ts` (pure constants, no React): `HEAT_MIN_TEMP=30, NO_HEAT_MIN_TEMP=25, HEAT_MAX_TEMP=80, COOL_MIN_TEMP=30, COOL_MAX_TEMP=75, NO_HEAT_FLOOR=15, UV_MIN=10, UV_MAX=100, TIME_MAX_MIN=120, TIME_MAX_MIN_BLEACH=720`, plus `isHeatType()/isUvProcess()` helpers currently local in `CsvBuilderModal.tsx:130-131`. Export `ProcessType` from `MaterialContext.tsx` (make `CureStep.process: ProcessType`) and delete the local unions in `CsvBuilderModal` (StepCard/StepModal are parked, see A3). `parseCsv` uses the constants. | A constants file in `lib/` is not a layer; it is testable by vitest and keeps `MaterialContext` a context. Values do not change → behavior preserved. |
| A3 | **Accept + amend.** Park `StartCureButton.tsx`, `src/assets/*`, `SectionHeader.tsx`, `ui/{card,separator,touch-spinner}.tsx` → `Not_Relevant/unused/`. Park `MaterialEditorPage.tsx` + `StepCard.tsx` + `StepModal.tsx` → `Not_Relevant/prototypes/material-editor/`, remove the route (`App.tsx:7,90`), remove `tools/shoot.mjs:97`, move `docs/screenshots/material-editor.png` alongside. | Dead-end route with no entry point, not in SRS/qa-tool; live editor is `CsvBuilderModal`. Removing it also removes duplication D2/D3 at the source. |
| A4 | **Accept (conservative).** Fix W1 (demo fallback), W2 (comment), U7 (comment). Do **not** split `CureProcessPage.tsx` (996 lines; state machine). Do not touch page-local `formatDate`/`Card` helpers (convention). | |
| B5 | **Accept.** Move `server/hardware/` → `Not_Relevant/old-implementations/server-hardware-cpp/`. Remove the `hw_driver` tier from `HardwareController` (becomes IOBridge → simulation). Files to touch: `server/app.py` (`:37-42` import block; `HW_AVAILABLE`/`hw_driver` at `:143-144,177-178,192-193,200-201,207-208,227-228,235-236,245-246,346-347,353-354,1547`), `tools/build-update.sh:79,140-144`, `src/services/hardware-api.ts:5`, `docs/project-context.md:25,27,73`, `AGENTS.md:10`. | Never built on the Pi (`pi-setup.sh`), no `.so` in tree, superseded by `io_bridge` for every op; simulation branch is the real fallback. |
| B6 | **Accept.** Legacy `io_controller/*` → `Not_Relevant/legacy/io_controller/` (drivers, dashboards, `.cpp`, `requirements.txt`, old README); hardware reference artifacts (`*.xlsx`, `*.pdf`, `curebox-flow-diagram.html`) → `Not_Relevant/legacy/io_controller/hardware-reference/`; `control_dashboard.py` + `fan_control.py` (bench tools on the live driver) → `Not_Relevant/development-tools/io_controller/` with a 2-line `sys.path` shim so they still run; `control_dashboard1.py` → `Not_Relevant/old-implementations/`. New short `io_controller/README.md`. | Evidence L2–L5. |
| B7 | **Accept a 3-file split** (app.py stays the routes/wiring file): `server/hardware_controller.py`, `server/storage.py`, `server/cloud_sync.py`. Symbol map in WP-B2. Globals/threads/atexit remain owned by `app.py` (it constructs `hw`, `counters`, `_cure_files`, `cloud_sync` and registers atexit), so import-time behavior is unchanged. | Reduces app.py to routes; each new module is import-safe off-Pi and unit-testable; no new abstraction — same classes, moved. |
| B8 | **Accept.** All 7 `scripts/*.py` → `Not_Relevant/development-tools/bench-analysis/`. Update the comment at `io_controller/io_controller.py:128`. Shell/bat/service files stay. | Evidence L6. |
| B9 | **Keep** `server/db.py` + `server/db/*.sql` (documented optional PostgreSQL deployment, SRS §10; `_db_on()` gate `server/app.py:612`, `desktop.py:47`). No change. | Conservative. |
| B10 | **Keep** `cloud/` unchanged (all 6 defs/routes used; `Dockerfile` copies only `portal.py`). | |
| C11 | Move to `Not_Relevant/development-tools/`: `sCure-design-handoff.zip`, `docs/sCure_SRS.zip`, `docs/Screenshot 2026-08-05 150951.png`, `tools/_bold-survey.json`, `updates/scure-update-1.0.0.scu`. Delete local gitignored temp: `render.html`, `render-dump.html`, `scure-desktop.log`, `vite-dev.log`. Keep `tools/error-editor.html` (live editor for `public/config/errors.json`). Add `updates/` to `.gitignore`. | Evidence U8, L7. |
| C12 | **Accept.** Rewrite `README.md` (structure in WP-R1). | |
| C13 | **Accept.** `package.json` name → `scure-box`, version → `0.4.9`; `tools/gen-sbom.mjs` reads `VERSION` for the version (keeps VERSION the single source of truth); regenerate `public/compliance/sbom.json` via `npm run sbom`. | Only reader of `pkg.version` is `gen-sbom.mjs:29`; nothing reads `pkg.name` elsewhere (rg `scure-a-temp` → only `package.json`, `sbom.json`, `design-handoff/*/sbom.json`). |
| C14 | Note only: `.claude/settings.local.json` stale sCure-A entries. No action. | |

---

## 4. Not_Relevant/ move list

Create `Not_Relevant/README.md` (one paragraph: "parked, not built, not deployed; each subfolder has the original path in a `ORIGIN.txt`"). Use `git mv` for tracked files so history follows.

| Source | Destination | Verification (nothing active references it) | References to update |
|---|---|---|---|
| `server/hardware/` (build.sh, hw_driver.cpp, temperature_control.hpp) | `Not_Relevant/old-implementations/server-hardware-cpp/` | only `server/app.py:37-42,…` (removed in WP-B1), `tools/build-update.sh:79,140-144` | app.py, build-update.sh, hardware-api.ts:5, docs/project-context.md, AGENTS.md |
| `io_controller/{pca9685,tca6424a,analog_read,temp_monitor,servo,gpio_control,gpio_manager,pinctrl,toggle_gpio,write_gpio_example,config,dashboard}.py` | `Not_Relevant/legacy/io_controller/` | rg: importers are only each other (L2) | AGENTS.md:10, project-context.md:73 |
| `io_controller/io_controller.cpp`, `io_controller/requirements.txt`, `io_controller/README.md` (old) | `Not_Relevant/legacy/io_controller/` | not referenced by scripts (`pi-setup.sh:44` installs `server/requirements.txt`) | new README written |
| `io_controller/HSI sCure (3).xlsx`, `HSI sCure (3) - backup before code-sync.xlsx`, `IO BOARD SCURE.pdf`, `curebox-flow-diagram.html` | `Not_Relevant/legacy/io_controller/hardware-reference/` | rg: none | — |
| `io_controller/control_dashboard.py`, `io_controller/fan_control.py` | `Not_Relevant/development-tools/io_controller/` (+ add at top: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'io_controller'))`) | rg: none besides `curebox-flow-diagram.html:242` (also parked) | — |
| `io_controller/control_dashboard1.py` | `Not_Relevant/old-implementations/` | rg: none | — |
| `scripts/{calibrate_scure_temp,live_temp_graph,compare_delta_live,uv_led_experiment,uv_experiment_viewer,picolog_report,scure_temp_correction}.py` | `Not_Relevant/development-tools/bench-analysis/` | rg: none in scripts/service/bat/build; only inter-refs and doc comment `io_controller/io_controller.py:128` | update comment path |
| `src/components/StartCureButton.tsx`, `src/components/SectionHeader.tsx`, `src/components/ui/{card,separator,touch-spinner}.tsx`, `src/assets/` | `Not_Relevant/unused/src/...` | import graph: 0 importers | — |
| `src/pages/MaterialEditorPage.tsx`, `src/components/StepCard.tsx`, `src/components/StepModal.tsx`, `docs/screenshots/material-editor.png` | `Not_Relevant/prototypes/material-editor/` | U3 | `src/App.tsx:7,90`, `tools/shoot.mjs:97`, project-context.md:34,51 |
| `sCure-design-handoff.zip`, `docs/sCure_SRS.zip`, `docs/Screenshot 2026-08-05 150951.png`, `tools/_bold-survey.json`, `updates/scure-update-1.0.0.scu` | `Not_Relevant/development-tools/artifacts/` | rg: none | `.gitignore` add `updates/` |
| (delete, gitignored) `render.html`, `render-dump.html`, `scure-desktop.log`, `vite-dev.log` | — | regenerated by tools/desktop.py | — |

---

## 5. Implementation work packages (ordered)

Run order: **WP-N0 → WP-F → WP-B → WP-N → WP-R**. Each WP ends with its verification command; the whole set ends with `npm run build && npm run lint && python -m py_compile server/*.py io_controller/*.py`.

### WP-N0 — tooling guard (do first)
- `eslint.config.js:9` → `globalIgnores(['dist', 'Not_Relevant'])`.
- `.gitignore`: add `updates/`.
- Create `Not_Relevant/{legacy,unused,prototypes,development-tools,old-implementations}/` + `Not_Relevant/README.md`.
- Risk: none. Verify: `npm run lint`.

### WP-F1 — single API base
- `src/services/hardware-api.ts:13`: `export const API_BASE = ...` (same value).
- Replace local definitions with `import { API_BASE } from '@/services/hardware-api'` in: `VersionsModal.tsx:10`, `NetworkPage.tsx:14`, `HardwareContext.tsx:130` (delete the const inside the effect), `SystemConfigContext.tsx:75` (same), and in `CureHistoryContext.tsx:37`, `MaterialContext.tsx:45`, `PrintHistoryContext.tsx:24` — for these three also change every `${API_BASE}/api/…` → `${API_BASE}/…` (`CureHistoryContext.tsx:42` and the `apiPost` call sites `:84,95,104` — `/api/cure-runs/...` → `/cure-runs/...`, `MaterialContext.tsx:292,300,310`, `PrintHistoryContext.tsx:32,40`).
- Risk: low; behavior identical when `VITE_HW_API_URL` unset. Verify: `npm run build`; `npm run dev` + server running → Home lists programs, cure history loads (network tab shows `/api/...` once, no `/api/api/`).

### WP-F2 — limits + ProcessType single source
- New `src/lib/limits.ts` (values in A2, header comment noting server limits differ by design: `server/app.py:1198-1201`).
- `MaterialContext.tsx`: `export type ProcessType = 'Heating'|'Drying'|'Cure'|'Cooling'|'Bleacher'|'Nitrogen'`; `CureStep.process: ProcessType`; `parseCsv` uses `TIME_MAX_MIN(_BLEACH)`, `COOL_MIN/MAX_TEMP`, `NO_HEAT_FLOOR`, `HEAT_MAX_TEMP` — same numbers, same messages.
- `CsvBuilderModal.tsx:29` delete local `ProcessType` (import from MaterialContext); `:125-131` delete `HEAT_MIN_TEMP/NO_HEAT_MIN_TEMP/COOL_MIN_TEMP/isUvProcess/isHeatType` → import from `@/lib/limits`; literals `75` (`:152`), `80` (`:446`), `120/720` (`:482`), `10/100` (`:509`) → constants.
- `CureProcessPage.tsx:55` → import `HEAT_MIN_TEMP`.
- Risk: low (typing only + identical numbers). Verify: `npm run build`; qa-tool CSV tests `hwc_csv_heat_min`, `hwc_csv_cool_drop` still pass; QA vitest on `parseCsv` (§6).

### WP-F3 — remove dead frontend cluster
- `git mv` per §4 (StartCureButton, SectionHeader, ui/card, ui/separator, ui/touch-spinner, assets/, MaterialEditorPage, StepCard, StepModal, screenshot).
- `src/App.tsx`: delete line 7 import and line 90 route.
- `tools/shoot.mjs:97`: delete the material-editor line.
- Risk: none at runtime (unreachable code). Verify: `npm run build && npm run lint`; `grep -rn "StepCard\|StepModal\|MaterialEditor\|StartCureButton\|SectionHeader\|touch-spinner\|ui/card\|ui/separator" src tools` → 0 hits.

### WP-F4 — demo data must not leak into production (W1)
- `MaterialContext.tsx:290-296` `loadUserMaterials`: on failure `return import.meta.env.DEV ? DEMO_USER_PROGRAMS : []`. `loadPresets` keeps `DEMO_PRESETS` unconditionally (see W1).
- `PrintHistoryContext.tsx:30-36` `loadPrintHistory`: on failure `return import.meta.env.DEV ? DEMO_PRINTS : []`.
- Update `src/data/demo-data.ts:1-3` header (remove `tools/_gen-demo.mjs`, state: presets = production fallback; user programs/prints = dev only).
- Risk: low; only affects the API-unreachable path in the production build (kiosk waits for API in `pi-kiosk.sh:7-10` anyway). Verify: `npm run build`; `npm run dev` without server still shows demo data; `npx vite preview` without server shows presets only and empty prints.

### WP-B1 — remove C++ tier
- `server/app.py`: delete lines 37-42 (`try: from hardware import hw_driver ... HW_AVAILABLE`); delete every `if HW_AVAILABLE ...` branch listed in B5 (each is a 2-line block that precedes the simulation fallback — keep the simulation lines that follow); `:1547` print → `"Hardware driver: SIMULATION"`. Header docstring: remove C++ mentions.
- `git mv server/hardware Not_Relevant/old-implementations/server-hardware-cpp`.
- `tools/build-update.sh`: delete `:79` and `:140-144`.
- `src/services/hardware-api.ts:3-8` header → "React UI → Flask API (port 3001) → io_bridge → io_controller".
- Risk: none on the Pi (`IOBridge` tier first) and none off-Pi (simulation). Verify: `python -m py_compile server/app.py`; `python server/app.py` → `GET /api/state` `hwSource:'simulation'`; on Pi `hwSource:'io_controller'`.

### WP-B2 — split `server/app.py` (behavior-preserving)
Create three modules; app.py keeps all `@app.route`s, `run()`, network helpers, `_db_on/_require_db`, validation constants/helpers (`:1198-1222`), `_on_device`, updater routes, `serve_ui`, `__main__`.

1. `server/hardware_controller.py` ← lines 84-362: `SIM_AMBIENT, SIM_HEAT_RATE, SIM_COOL_RATES, SIM_IDLE_RATE, COOLING_MODE_PWMS, class HardwareController` (post-WP-B1). No imports besides `time`. app.py: `from hardware_controller import HardwareController` and keeps `hw = HardwareController(io_bridge)` (`:365`) and the IOBridge probe (`:61-76`).
2. `server/storage.py` ← `DATA_DIR = os.environ.get('SCURE_DATA_DIR') or <server>/data` (replaces `_DATA_DIR` `:627` and the inline path at `:470-472`), `USER_MATERIALS_FILE, PRINT_HISTORY_FILE, CURE_HISTORY_FILE, CURE_REPORTS_FILE, PHASE_TIMINGS_FILE`, `history_lock`, `TELEMETRY_FLUSH_EVERY`, `load_json_file/save_json_file` (`:696-716`), `load_user_materials/save_user_materials` (`:631-651`, keep the atomic idiom), `class CureFileStore` (`:718-813`), `class ComponentCounters` (`:371-468`) with signature `ComponentCounters(path, get_state)` and `_sample()` calling `self._get_state()` instead of the global `hw.get_state()`. app.py: `counters = ComponentCounters(os.path.join(storage.DATA_DIR, 'component_counters.json'), hw.get_state)`; `atexit.register(counters.flush)` stays in app.py; `_cure_files = CureFileStore()` stays in app.py. Route bodies keep using the same names via `from storage import ...` (rename underscore-prefixed names to public: `load_json_file`, etc. — update call sites `:1001,1012,1089,1113` and the phase-timings routes).
3. `server/cloud_sync.py` ← `class CloudSync` (`:821-965`) with `__init__(self, data_dir, get_state, counters, get_programs, put_programs, get_prints, put_prints, list_cures)`; the four static accessors become the injected callables. app.py builds it once after the stores exist:
   `cloud_sync = CloudSync(storage.DATA_DIR, hw.get_state, counters, get_programs=lambda: db.get_materials(presets_only=False) if _db_on() else load_user_materials(), put_programs=..., get_prints=..., put_prints=..., list_cures=lambda: db.get_cure_history() if _db_on() else _cure_files.list())` (bodies copied verbatim from `:866-889,900`).
- Order in app.py must remain: Flask app → IOBridge probe → `hw` → `counters` → stores → `cloud_sync` → routes (same as today; threads start at construction as before).
- `server/desktop.py:26` `import app as scure` unaffected. `tools/build-update.sh` staging must copy `server/*.py` (WP-R2) — mandatory once this WP lands.
- Risk: medium (module globals). Mitigation: pure move + injection; no logic edits. Verify: `python -m py_compile server/*.py`; `python server/app.py` off-Pi and hit `GET /api/state` (has `counters`, `cloudSync`), `POST /api/cure/heat?target=50`, `GET/POST /api/materials/user`, `/api/print-history`, `/api/cure-runs/x/start|finish`, `GET /api/cure-history`; run `qa-tool/index.html` against it; on Pi: journal shows `[COUNTERS] loaded`, `[CLOUD] sync agent ON` (if configured), `hwSource:'io_controller'`; `SCURE_DATA_DIR=/tmp/x python server/app.py` writes there.

### WP-B3 — io_controller housekeeping
- `git mv` per §4 (legacy drivers, dashboards, cpp, xlsx/pdf/html, requirements.txt, README.md).
- Add the `sys.path` shim to the two moved bench tools (`control_dashboard.py`, `fan_control.py`).
- New `io_controller/README.md` (≤40 lines): live modules and roles, CLIs (`python3 io_controller.py --help`, `temperature_control.py <target>`, `cooling_mode.py`), `components.json` is re-read per activation, deps come from `server/requirements.txt`.
- `io_controller/io_controller.py:128` comment → `Not_Relevant/development-tools/bench-analysis/calibrate_scure_temp.py`.
- Risk: none (no live import touches moved files — verified L2). Verify: `python -c "import sys; sys.path.insert(0,'io_controller'); import io_controller, temperature_control, cooling_mode, system_log"`; `python -m py_compile server/io_bridge.py`.

### WP-N — remaining moves
- `scripts/*.py` → `Not_Relevant/development-tools/bench-analysis/`; artifacts per §4 (`git mv` tracked ones; plain move for untracked `sCure-design-handoff.zip`? — it is tracked: `git mv`); delete `render.html`, `render-dump.html`, `scure-desktop.log`, `vite-dev.log`.
- Verify: `git status` shows only renames/deletes; `bash -n scripts/*.sh tools/build-update.sh`.

### WP-R1 — README.md (structure)
1. What sCure Box is (2 lines) · 2. Repository layout (src / server / io_controller / cloud / scripts / tools / docs / qa-tool / design-handoff / Not_Relevant) · 3. Run: Windows (`scripts\win-start.bat`), Pi (`pi-setup.sh`, `pi-start.sh`, service), dev (`npm run dev` + `python server/app.py`, simulation note) · 4. Build & release: `npm run build`, `VERSION` + `public/config/versions.json` bump, `npm run sbom`, `tools/build-update.sh` · 5. Verify: `npm run build`, `npm run lint`, `py_compile`, tests (§6), qa-tool · 6. Configuration: `io_controller/components.json`, `public/config/*.json`, `server/data/`, `DATABASE_URL`, `SCURE_DATA_DIR`, `server/data/cloud.json` · 7. Safety notes (interlocks live in `SystemController`; process modules own no hardware) · 8. Docs pointers (SRS, CSV guide, project-context, AGENTS.md). Delete the Vite template text.

### WP-R2 — build-update.sh consistency (minimal)
- Stage `cp server/*.py` and `server/requirements.txt`, and `io_controller/*.py io_controller/components.json` (new `server/` and `io_controller/` staging dirs); install script copies those dirs; remove the C++ block. Add a header comment: "install paths (`/opt/scure`, `scure-api`/`scure-ui`) predate `scripts/scure.service`; align before first field use" — owner decision.
- Verify: `bash -n tools/build-update.sh`; `tools/build-update.sh 0.4.9-test` produces a `.scu` whose tar lists `server/io_bridge.py`.

### WP-R3 — package identity / SBOM
- `package.json`: `"name": "scure-box"`, `"version": "0.4.9"`. `tools/gen-sbom.mjs:29`: `version: readFileSync('VERSION','utf8').trim()`. Run `npm run sbom` → `public/compliance/sbom.json` metadata updated. Verify: `node tools/gen-sbom.mjs && git diff --stat public/compliance/sbom.json`.

### WP-R4 — docs/config touch-ups
- `docs/project-context.md`: remove C++ tier (`:25,27`), legacy row (`:73`) → point to `Not_Relevant/`, routes list (`:34`), components list (`:51`), backend table (new modules). `AGENTS.md:10` same. Add `Not_Relevant/` to "do not extend".
- `scripts/pi-setup.sh:15` `REPO_URL` — **ask owner** which GitHub repo is canonical (sCure-A vs sCure_01); do not change silently.
- Note (no action): `.claude/settings.local.json` stale sCure-A entries.

---

## 6. Test plan for QA

Frontend (add devDeps `vitest`, `@vitest/coverage-v8` optional; script `"test": "vitest run"`; `vitest.config.ts` with `resolve.alias '@' → ./src`, `test.environment: 'node'`, `include: ['src/**/*.test.ts']`; add `src/**/*.test.ts` exclusion to `tsconfig.app.json` `exclude` or keep them type-checked — either is fine):
- `src/lib/limits.test.ts` — constants sanity (`HEAT_MIN_TEMP===30`, `COOL_MAX_TEMP===75`, helpers `isHeatType/isUvProcess`).
- `src/context/MaterialContext.test.ts` — `parseCsv` (importable without React rendering): valid 5-col legacy CSV, 9-col CSV; rejects heat < 30 (message), cooling outside 30–75, cooling not ≥5 °C below previous, time > 120 / Bleacher ≤ 720, UV < 10; `stepsToCsv(parseCsv(x).steps)` round-trip stable; Nitrogen/Cooling blank fields.

Backend (`pip install pytest`; `server/tests/conftest.py` sets `os.environ['SCURE_DATA_DIR'] = tmp_path_factory.mktemp('data')` **before** `import app`, inserts `server/` and `io_controller/` on `sys.path`, yields `app.app.test_client()`; note `import app` starts the `ComponentCounters` daemon thread — harmless):
- `server/tests/test_api_simulation.py` — `GET /api/state` → 200, `hwSource=='simulation'`, keys `counters`, `cloudSync`; validation: `POST /api/cure/heat?target=200` → `ok:false, code 7001`; `/api/cure/cool?target=10&mode=fast` → 7001/7003 per `_valid_cool_temp`; `/api/cure/cure-405?intensity=5` → 7002; sequence heat(50) → state `isHeating` → `/api/cure/stop` → not heating; door: `/api/door/open` → `doorClosed:false` then re-closes ≤5 s (sim); `/api/door-abort/ack` → `ok:true`; materials `POST/GET /api/materials/user` round-trip and file exists under `SCURE_DATA_DIR`; `/api/print-history` round-trip; cure runs `start → telemetry → finish → GET /api/cure-history` contains the run; `POST/GET /api/cure-runs/<id>/report`; `/api/materials/presets` → 503 without DB.
- `server/tests/test_storage.py` — `save_json_file/load_json_file` atomic (no `.tmp` left, corrupt file → default), `CureFileStore` start/telemetry/finish flush semantics, `ComponentCounters(path, get_state)` `_sample()` mapping (heater only when `isHeating`), `flush()/hours()`.
- `io_controller/tests/test_pure.py` — `ntc_resistance_to_temp(10000)==25.0`, `ntc_voltage_to_resistance`, monotonicity; `load_component_config()` finds `components.json` and has keys `heating, cooling, heater, door_sensor`; `CoolingController._slope_c_per_min` (`[(0,50),(30,49),(60,48)]` → 2.0; <3 samples → None); `parse_rgb_color`; `set_and_verify` retries then raises `VerificationError` (with lambdas, no hardware).
Verified off-Pi already: `import io_controller, cooling_mode` works and returns those values (Python 3.14 in `.venv`).

---

## 7. Safety invariants (must hold after refactor)

- [ ] `server/app.py` never calls PCA/GPIO directly; every hardware op still flows `route → hw (HardwareController) → IOBridge → SystemController` (grep `io_bridge`/`SystemController` only in `io_bridge.py`).
- [ ] `HardwareController` order of tiers is `bridge → simulation` only; on the Pi `GET /api/state.hwSource == 'io_controller'`.
- [ ] Door: `StatusLeds` watchdog + `IOBridge.door_abort()` untouched (`server/io_bridge.py:621`), UI 6016 alert and `POST /api/door-abort/ack` path unchanged; `CureProcessPage` door grace/abort logic not edited.
- [ ] Heater: `SystemController.enable_heater` pre-flight (`io_controller.py:1208`) and `heater_health_check` (`:1255`) unchanged; `TemperatureController` fan run-on unchanged (`temperature_control.py` not touched).
- [ ] All actuator writes still go through `set_and_verify`/`verify_each` (`io_controller.py:180,198`); no file in `io_controller/{io_controller,temperature_control,cooling_mode,system_log}.py` changes except the one comment at `:128`.
- [ ] `atexit` still registers `io_bridge.shutdown` (everything OFF on exit) and `counters.flush` in `app.py`.
- [ ] Server validation limits unchanged (`HEAT_TARGET_MIN=30, TEMP_MAX=80, COOL_TARGET_MIN=20, UV_INTENSITY_MIN=10`) and UI limits unchanged in value (`limits.ts` = 30/25/80/30/75/15/10/100/120/720).
- [ ] Atomic write idiom preserved for every `server/data/*.json` writer (tmp → flush → fsync → replace).
- [ ] Demo user programs / prints can no longer be POSTed over real machine data (WP-F4); presets fallback still available offline.
- [ ] `npm run build`, `npm run lint`, `python -m py_compile server/*.py io_controller/*.py`, qa-tool green in simulation; on-device smoke: boot → heat 50 °C → door open → abort → ack.
