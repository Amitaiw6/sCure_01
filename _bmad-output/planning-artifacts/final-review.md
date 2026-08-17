# sCure Box refactor — Final Review

Branch `refactor/clean-architecture` (working tree, no commits yet) vs baseline `main` = `4e75eb0`. Reviewed 2026-08-17 by reading every diff and running every gate. Nothing in application code was modified by this review.

## Verdict: **APPROVE** (with 4 required non-code changes before commit, listed at the end)

The refactor is what the Architect's plan says it is: file moves, three verbatim class extractions with dependency injection, one constants module, one exported `API_BASE`, and the approved list of small fixes. I found **no logic change outside the plan / approved fix list**, all safety invariants hold, and all gates are green. The required items are git hygiene and three stale doc sentences.

---

## 1. Architecture is clean and understandable

Active tree (verified with `find`, excluding node_modules/__pycache__/data):

```
src/            55 files: App.tsx main.tsx index.css, components/ (14 + ui/ 8), context/ (6 + 1 test),
                data/demo-data.ts, lib/ (compliance, cure-report, utils, limits + limits.test), pages/ (7),
                services/hardware-api.ts
server/         app.py 919 | hardware_controller.py 273 | storage.py 292 | cloud_sync.py 143 | io_bridge.py 828
                updater.py db.py db/*.sql desktop.py requirements.txt tests/ (conftest + 2 files)
io_controller/  io_controller.py temperature_control.py cooling_mode.py system_log.py components.json
                README.md .gitignore tests/ (conftest + test_pure.py)   [logs/, .claude/ are gitignored]
cloud/          portal.py Dockerfile fly.toml stratasys_logo.png (+ gitignored portal_config.json / secrets)
scripts/        pi-setup.sh pi-start.sh pi-kiosk.sh scure.service win-start.bat   (no .py left)
tools/          11 *.mjs, build-update.sh, error-editor.html                        (_bold-survey.json gone)
Not_Relevant/   README.md + legacy/ unused/ prototypes/ development-tools/ old-implementations/, each with a README
```

- `Not_Relevant/` matches the plan's §4 move list exactly (checked file-by-file against `git status`); every subfolder has a README naming the original path. No `ORIGIN.txt` files exist — the top README mentions them (nit N6).
- `grep -rn Not_Relevant src server io_controller cloud scripts tools qa-tool *.ts *.json` → only `io_controller/io_controller.py:128` (comment), `io_controller/README.md:35,37` (prose), `eslint.config.js:9` (ignore). **Nothing active imports from `Not_Relevant/`.**
- No new abstractions beyond the plan: `hardware_controller.py`, `storage.py`, `cloud_sync.py`, `src/lib/limits.ts` — same classes moved, no new base classes/interfaces/registries. `app.py` went 1556 → 919 lines and is now routes + wiring only.
- Stray files: `server/data/component_counters.json` (gitignored, from a local run), `.chrometmp/`, `dist/` — all ignored. `updates/` is empty and now ignored.

## 2. Required functionality preserved (diff read in full)

`git diff main --stat`: 85 files, +801/−1331; 60 of them pure renames. Non-rename source changes: `server/app.py`, `server/io_bridge.py`, `io_controller/io_controller.py` (comment), 13 files under `src/`, `tools/{build-update.sh,gen-sbom.mjs,shoot.mjs}`, `eslint.config.js`, `package.json`, `.gitignore`, docs.

Verbatim-move proof (mechanical diffs of baseline line ranges vs new modules):

| Block | Baseline `app.py` | New location | Diff result |
|---|---|---|---|
| `SIM_*`, `COOLING_MODE_PWMS`, `HardwareController` | 84–362 | `hardware_controller.py:12–273` | identical after dropping the `HW_AVAILABLE`/`hw_driver` blocks (incl. the `return True, None` inside the `open_door` HW branch); one comment shortened |
| `ComponentCounters` | 371–468 | `storage.py:176–292` | identical except `__init__(path, get_state)`, `self._get_state()` instead of global `hw.get_state()`, and `f.flush(); os.fsync()` added in `flush()` (approved "counters fsync") |
| `_DATA_DIR`, materials file helpers, `_load/_save_json_file`, constants | 617–716 | `storage.py:20–90` | identical after `_`-prefix rename; `DATA_DIR` gains `SCURE_DATA_DIR` env override (approved W5) |
| `_CureFileStore` | 718–813 | `storage.py:93–188` | identical except docstring (P6 comment fix) |
| `CloudSync` | 821–965 | `cloud_sync.py:16–143` | identical except the 4 `@staticmethod` accessors → injected callables; `_DATA_DIR`→`self._data_dir`; `hw.get_state()`→`self._get_state()`; `counters`→`self._counters` |

`app.py` remaining hunks, all on the approved list: header docstring; imports (`signal`, `logging`; `json/threading/time` no longer needed); C++ import block removed; werkzeug logger → WARNING unless `SCURE_ACCESS_LOG`; `_cloud_*` accessors + `_make_cloud_sync()` (bodies = the old staticmethods, verbatim); `/api/cloud/config` writes `cloud.json` via `save_json_file` (atomic; only cosmetic difference: no `indent=2`); `serve_ui` returns JSON 404 for unknown `api/*`; `__main__` installs `SIGTERM → sys.exit(0)`; SIMULATION print string. Route bodies otherwise byte-identical apart from `_x`→`x` renames.

`src/` hunks, all on the approved list: `App.tsx` route/import removal; `API_BASE` exported from `hardware-api.ts:13` (same value) and imported in 7 files, the three root-URL contexts now use `${API_BASE}/x` (no `/api/api/`, grep confirms); `ProcessType` exported from `MaterialContext.tsx:9`, `CureStep.process: ProcessType`; `limits.ts` constants replace the literals in `CsvBuilderModal`, `MaterialContext.parseCsv`, `CureProcessPage` (same numbers, same messages — vitest `parseCsv` tests assert the messages); `loadUserMaterials`/`loadPrintHistory` return `[]` in prod / demo in `import.meta.env.DEV`; presets fallback unchanged; `demo-data.ts` header; `hardware-api.ts` header; dead `{false && …}` intensity JSX removed; 3 `eslint-disable-next-line react-hooks/set-state-in-effect` comments; `CureProcessPage` comment "StepModal" → "CsvBuilderModal".

Behavior deltas that ARE approved but worth stating explicitly for the owner:
- `CureHistoryContext`, `MaterialContext`, `PrintHistoryContext` now honour `VITE_HW_API_URL` (they hardcoded `http://localhost:3001` before). Plan D1/A1.
- `recharts` removed from `package.json` (perf P4), SBOM regenerated (`scure-box@0.4.9`, no recharts entry).
- `eslint.config.js`: `react-refresh/only-export-components` turned off (comment explains) and `globalIgnores` extended to `.venv design-handoff qa-tool` (plan asked only for `Not_Relevant`; the extras are non-source dirs — harmless).

**No unplanned logic change found.**

## 3. Safety preserved — plan §7 checklist

| Invariant | Evidence | Status |
|---|---|---|
| Server never touches PCA/GPIO; every op `route → hw → IOBridge → SystemController` | `grep SystemController\|IOBridge server/*.py` → only `app.py` (probe lines 68–82, `_make_cloud_sync` no), `hardware_controller.py` (docstring/comments; all calls go `self.bridge.*`), `io_bridge.py` | ✅ |
| Tier order `bridge → simulation` only | `hardware_controller.py:69–74,109–115…` — every method: `if self.bridge: return self.bridge.x(...)` then sim; no third tier; `hwSource:'simulation'` (test `test_state_simulation`) | ✅ |
| Door watchdog / `door_abort()` / UI 6016 / ack path untouched | `git diff main -- server/io_bridge.py`: only `_mode(self, door=None)` + `_evaluate` reads `door` once and passes it; `door_abort_sec`, `status_sec`, `door_abort()`, `/api/door-abort/ack` unchanged; `CureProcessPage.tsx` diff = 3 hunks (import, comment, comment) — grace/abort logic untouched | ✅ (note: `_mode` no longer re-reads the sensor, so a raise inside `door_open()` can no longer escape `_evaluate` — strictly more robust, same displayed mode) |
| Heater pre-flight / health check / `TemperatureController` unchanged | `git diff main -- io_controller/temperature_control.py cooling_mode.py system_log.py components.json` → empty; `io_controller.py` diff = the one comment at :128 | ✅ |
| All actuator writes through `set_and_verify`/`verify_each`; live driver files unchanged | as above; `test_verify_constants_unchanged` | ✅ |
| `atexit` registers `io_bridge.shutdown` and `counters.flush` in `app.py` | `app.py:82`, `:97` (+ SIGTERM→SystemExit in `__main__` :906 so systemd stop reaches them) | ✅ |
| Server validation limits unchanged | `app.py:552–555` `HEAT_TARGET_MIN=30 TEMP_MAX=80 COOL_TARGET_MIN=20 UV_INTENSITY_MIN=10`; UI `limits.ts` = 30/25/80/30/75/15/10/100/120/720 (`limits.test.ts`) | ✅ |
| Atomic write idiom for every `server/data/*.json` writer | `storage.py:44–51` (materials), `:82–89` (`save_json_file`, used by cure history/reports/phase timings/print history/cloud.json), `:240–247` (counters, now with fsync); `grep "open(.*'w'" server/` shows the only other writers are USB exports (not `server/data`) | ✅ |
| Demo data cannot be POSTed over machine data; presets offline | `MaterialContext.tsx:299`, `PrintHistoryContext.tsx:37`, `loadPresets` unconditional | ✅ |
| Gates green | see §9 | ✅ (on-device smoke still pending — deferred D9/D10) |

## 4. Duplication removed — leftover greps

| Grep | Result |
|---|---|
| `localhost:3001` in `src/` | only `src/services/hardware-api.ts:13` |
| `HEAT_MIN_TEMP =` in `src/` | only `src/lib/limits.ts:13` (and `NO_HEAT_MIN_TEMP` :15) |
| `type ProcessType` | only `src/context/MaterialContext.tsx:9` |
| `hw_driver\|HW_AVAILABLE` in active code + docs | none |
| `/api/api/` | none |
| `StepCard\|StepModal\|MaterialEditor\|StartCureButton\|SectionHeader\|touch-spinner\|ui/card\|ui/separator` in `src tools` | none |
| references to moved paths (`scripts/calibrate…`, `server/hardware/`, `material-editor`) in `docs qa-tool scripts tools src server public` | none (only prose in `project-context.md`/`io_controller/README.md`, both pointing to the new location) |

## 5. Complexity check (read `app.py` wiring, `storage.py`, `hardware_controller.py`, `cloud_sync.py`, `limits.ts`)

Overall: appropriate. Concrete observations:

- `_make_cloud_sync()` + five `_cloud_*` module functions (`app.py:274–307`) is the simplest way to satisfy "CloudSync has no dependency on Flask/db/hw" while `/api/cloud/config` can re-create the agent. Fine. **But** the five accessor bodies duplicate the bodies of the routes `get_user_materials`, `save_all_user_materials`, `get_print_history`, `save_print_history`, `cure_history_list` (same `if _db_on(): db.x() else file` branches). Optional simplification (behavior-neutral): make the routes call the helpers — e.g. `get_user_materials`: `return jsonify(_cloud_get_programs())`; `save_all_user_materials`: `_cloud_put_programs(request.json or [])`; same for prints and cure history — and rename the helpers to `_programs()/_save_programs()/_prints()/_save_prints()/_cures()`. Removes ~15 lines and gives each store one access point. Not required (the plan explicitly asked for verbatim bodies).
- `import atexit` appears twice (`app.py:81` inside the `if io_bridge` block and `:96` top-level; pre-existing) and `atexit.register(lambda: counters.flush())` can be `atexit.register(counters.flush)`. Nit.
- `storage.py`: the durability story is told three times (module docstring, the "Persistent user-program store" comment `:20–27`, the "Durable file store" comment `:54–60`) — verbatim moves; could be trimmed to the docstring. Nit.
- `hardware_controller.py`: verbatim, nothing to simplify.
- `limits.ts`: 30 lines, pure; header says "no imports" but it has `import type { ProcessType }` (type-only, erased; the type-only cycle with `MaterialContext` is safe). Fix the sentence or move `ProcessType` here and re-export from `MaterialContext` as the plan §3.1 wording suggested — either is fine. Nit.
- Nothing is more complicated than the plan; no wrapper layers, no config indirection added.

## 6. Maintainability / docs — 8 spot-checks

| Claim | Where | Verified |
|---|---|---|
| `npm test` = vitest, `python -m pytest server/tests io_controller/tests`, `py_compile` gates | README §Build; AGENTS §Running | ✅ `package.json` scripts, `pytest.ini testpaths` |
| `SCURE_DATA_DIR` override | README §Configuration, project-context §2/§4 | ✅ `storage.py:28`, `test_data_dir_respects_env` |
| Routes list `/`, `/cure-process`, `/settings`, `/network`, `/alerts`, `/cure-history` | project-context §3 | ✅ `App.tsx` |
| shadcn primitives = button badge dialog select input progress switch touch-number | project-context §3 | ✅ tree |
| `ComponentCounters(path, get_state)`, `CloudSync(data_dir, get_state, counters, get_programs, put_programs, get_prints, put_prints, list_cures)` | project-context §4 | ✅ signatures |
| `updater.verify_signature` vs `/opt/scure/keys/scure-update.pub` | project-context §4 | ✅ `updater.py:18` |
| io_controller CLIs `cooling_mode.py <fan_pwm> [--target C]`, `temperature_control.py <target>` `--off` | `io_controller/README.md` | ✅ argparse at `cooling_mode.py:284–285`, `temperature_control.py:436–439` |
| `keys/*.key`, `.mcp.json`, `server/data/`, `cloud/portal_config.json` gitignored | AGENTS Policy | ✅ `git check-ignore -v` hits `.gitignore:41,43,33,36` |

Stale sentences found (required fixes R2–R4 below): AGENTS.md "atomic write idiom … already used in `server/app.py`" (now `storage.py`); project-context §7 heading "(no unit-test suite exists)"; project-context §8 "`keys/scure-update.key` … NOT gitignored" (it is, `.gitignore:41`). `SCURE_ACCESS_LOG` is not mentioned in README/docs (nit N1). `io_controller/README.md` and `Not_Relevant/README.md` are accurate and short.

## 7. QA & performance findings — resolved or deferred?

Performance review (all items accounted for):
- A-items done: P1 werkzeug (`app.py:49–50`), P2 door read once (`io_bridge.py:157,190–216`), P4 recharts + SBOM, P5 dead `internetOk` key (`io_bridge.py`), P6 comment (`storage.py:95–99`). P3 (network subprocesses) → deferred D2 with reason (Linux-only, JSON must stay identical). ✅
- B-items: P7→D1, P8→D3, P9→D4, P10→D5, P11→D6 — each with "why" and a next step. C-items documented as leave. ✅ nothing dropped.

QA findings: `deferred-findings.md` cites QA-3 (SIGTERM, implemented) and QA-6 (blank Cooling default 25 °C, deferred). The approved fix list (API_BASE, limits, dead cluster, demo guard, werkzeug, `api/` 404, SIGTERM, atomic cloud.json, counters fsync, door once, internetOk, dead JSX, eslint comments) is fully implemented (see §2). **However, no QA report file exists under `_bmad-output/planning-artifacts/`** (only the plan, perf review, deferred list), so QA-1/2/4/5… cannot be cross-checked for silent drops. Required R1 asks to persist it (or a one-table "QA findings → status" section).

## 8. Plan work packages

| WP | Status | Evidence |
|---|---|---|
| N0 tooling guard | done | `eslint.config.js:9`; `.gitignore` +`updates/` +`.pytest_cache/`; `Not_Relevant/*` + READMEs |
| F1 single API base | done | 8 sites → 1 export; grep §4 |
| F2 limits + ProcessType | done | `limits.ts`, `MaterialContext.tsx:9`, `CsvBuilderModal` imports, `CureProcessPage.tsx:21` |
| F3 dead frontend cluster | done | renames + `App.tsx` + `shoot.mjs:97` |
| F4 demo-data guard | done | `MaterialContext.tsx:299`, `PrintHistoryContext.tsx:37`, `demo-data.ts:1–5` |
| B1 remove C++ tier | done | no `HW_AVAILABLE`; `server/hardware/` → `Not_Relevant/old-implementations/server-hardware-cpp/`; `build-update.sh`; `hardware-api.ts:5`; docs |
| B2 split app.py | done | three modules, verbatim (table §2); construction order Flask → probe → `hw` → `counters` → `_cure_files` → `cloud_sync` → routes preserved (`app.py:44,68,88,93,270,307`) |
| B3 io_controller housekeeping | done | renames; `sys.path` shim in both bench tools; new README (39 lines); comment :128 |
| N remaining moves | done | `scripts/*.py`, artifacts, `updates/` ignored; `render*.html`/logs absent |
| R1 README | done | all 8 sections present |
| R2 build-update.sh | done | stages `server/*.py` + `io_controller/{*.py,components.json}`, C++ block gone, owner-decision header; `bash -n` OK |
| R3 package identity / SBOM | done | `scure-box@0.4.9`, `gen-sbom.mjs` reads `VERSION`, sbom regenerated |
| R4 docs touch-ups | done (3 stale sentences remain, R2–R4) | `project-context.md`, `AGENTS.md` updated; `pi-setup.sh REPO_URL` correctly left for owner (D8) |
| §6 test plan | done | vitest 2 files/23 tests; pytest 50 tests (`server/tests` 36, `io_controller/tests` 14) covering exactly the listed cases |

## 9. Gates (run in this review)

| Command | Result |
|---|---|
| `npm run build` | ✅ `tsc -b` + vite, `dist/assets/index-*.js` 563 kB (pre-existing >500 kB warning) |
| `npm run lint` | ✅ 0 problems |
| `npm test` | ✅ 2 files, 23 tests |
| `.venv/Scripts/python -m pytest -q` | ✅ 50 passed |
| `python -m py_compile server/*.py io_controller/*.py` (venv 3.14 and system python) | ✅ |
| `bash -n tools/build-update.sh scripts/*.sh` | ✅; `git ls-files --eol` shows `eol=lf` for all `.sh`/`.service` |

## 10. Git hygiene

`git ls-files | grep -E 'keys/.*\.key|\.mcp\.json|server/data|portal_config'` → **empty** (only `keys/scure-update.pub` is tracked). ✅

Untracked files that **must be added** before commit (the branch does not build/test without them):
`server/hardware_controller.py`, `server/storage.py`, `server/cloud_sync.py`, `server/tests/` (3 files), `io_controller/tests/` (2 files), `src/lib/limits.ts`, `src/lib/limits.test.ts`, `src/context/MaterialContext.test.ts`, `vitest.config.ts`, `pytest.ini`, `Not_Relevant/legacy/io_controller/README.md`, and `_bmad-output/planning-artifacts/*.md` (referenced from `AGENTS.md` and `docs/project-context.md`).

---

## REQUIRED changes (all non-code)

1. **Git add the untracked files listed in §10** — `git add server/hardware_controller.py server/storage.py server/cloud_sync.py server/tests io_controller/tests src/lib/limits.ts src/lib/limits.test.ts src/context/MaterialContext.test.ts vitest.config.ts pytest.ini Not_Relevant/legacy/io_controller/README.md _bmad-output/planning-artifacts` — and persist the QA report (or add a "QA findings → resolved/deferred" table to `_bmad-output/planning-artifacts/deferred-findings.md`) so QA items other than QA-3/QA-6 are traceable.
2. `AGENTS.md:27` — "atomic write idiom (`tmp` → `flush` → `fsync` → `os.replace`) already used in `server/app.py`" → `server/storage.py`.
3. `docs/project-context.md:103` — heading "## 7. Verification available (no unit-test suite exists)" → "## 7. Verification available".
4. `docs/project-context.md:112` — "`keys/scure-update.key` (… untracked, NOT gitignored)" → "(… gitignored via `keys/*.key`, never commit)".

## Optional nits

- N1 README §Configuration: add "`SCURE_ACCESS_LOG=1` re-enables the werkzeug per-request log (silenced by default, `server/app.py:49`)".
- N2 `server/app.py`: routes `get_user_materials`/`save_all_user_materials`/`get_print_history`/`save_print_history`/`cure_history_list` could call the `_cloud_*` helpers (rename to `_programs/_save_programs/_prints/_save_prints/_cures`) — removes 5 duplicated `if _db_on()` bodies, no behavior change.
- N3 `server/app.py:81,96`: single top-level `import atexit`; `atexit.register(counters.flush)` instead of the lambda.
- N4 `server/storage.py:20–27,54–60`: collapse the two long "durable/atomic" comment blocks into the module docstring (they say the same thing three times).
- N5 `src/lib/limits.ts:8`: "no imports" → "type-only import" (or move `ProcessType` here and re-export from `MaterialContext`).
- N6 `Not_Relevant/README.md:6`: drop "/ `ORIGIN.txt`" (no such files; the per-folder READMEs carry the origin).
- N7 `server/tests/conftest.py:19`: move `import tempfile` up with the other imports.
- N8 `/api/cloud/config` now writes `cloud.json` compact (`save_json_file` has no `indent`); if humans edit that file on the Pi, pass `indent=2` through or accept it.
- N9 `.claude/settings.local.json` stale sCure-A entries and the live `.mcp.json` token (D11) — rotate the token.
