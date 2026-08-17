# QA Report — sCure Box refactor (`refactor/clean-architecture` vs `main` 4e75eb0)

Date 2026-08-17. Verdict: **approve with fixes required** → all required fixes applied in the developer fix pass (see status column).

## Test suites created

| File | Covers | Count |
|---|---|---|
| `src/lib/limits.test.ts` | limit constants, `isHeatType`/`isUvProcess` | 3 |
| `src/context/MaterialContext.test.ts` | `parseCsv`/`stepsToCsv`: legacy 5-col, full 9-col, Bleacher 720, N₂/Cooling blanks, OFF/no-heat 15–29 for heat-type steps (per 0.4.8/0.4.9 notes), <15/>80, cooling outside 30–75, cooling not ≥5 °C below previous, time limits, UV <10/>100, malformed rows, N₂ rules, round-trip stability | 20 |
| `server/tests/test_api_simulation.py` | state/hwSource, 7001/7002/7003 incl. boundaries, heat→state→cool→stop, cure-405 UV on/off, N₂ valve, door open + auto-reclose + door-abort ack, materials/print-history round-trip + files under `SCURE_DATA_DIR`, presets 503, cure-run lifecycle→cure-history, report save/get/404, phase timings, version, network status, diagnostics/bofa/rgb, cloud config 400, UI catch-all, `/api/*` 404 JSON, werkzeug log level | 22 |
| `server/tests/test_storage.py` | `DATA_DIR` env, atomic write/no `.tmp`/corrupt→default, user_materials, `CureFileStore` flush + power-cut `running`→`error`, `ComponentCounters` mapping/flush/reload/corrupt, `HardwareController` sim tier + fake-bridge delegation + fallback, `CloudSync` disabled/bad-config/injected `_apply` | 13 |
| `io_controller/tests/test_pure.py` | NTC math/monotonicity, `load_component_config`, `parse_rgb_color`, `set_and_verify` retry/raise, `verify_each`, `_slope_c_per_min`, constants | 15 |

Config: `vitest.config.ts`, `pytest.ini`, `server/tests/conftest.py` (sets `SCURE_DATA_DIR` before `import app`), `io_controller/tests/conftest.py`.

## Results

| Command | Result |
|---|---|
| `npm test` | 23 passed |
| `.venv/Scripts/python -m pytest -q` | 50 passed |
| `npm run build` / `npm run lint` / `py_compile` | pass |
| Live scenario (55 steps, temp data dir) | all expected (codes, door auto-reclose 5.2 s, presets 503, SPA routes, persistence) |
| Restart with same data dir | materials/cure-history/report persist; counters written after 60 s and reloaded |
| Baseline regression (worktree of `main`, same scenario) | **0 diffs** across 43 aligned steps; Flask url_map identical (48 rules) |
| AST comparison of `app.py` defs vs new modules | renames + injected callables + C++ tier removal only |

## Findings and status

| # | Problem | Sev | Origin | Status |
|---|---|---|---|---|
| QA-1 | Refactor files untracked | high (process) | introduced | **fixed** — added in the refactor commit |
| QA-2 | Unknown `/api/*` GET returned `index.html` 200 | low | pre-existing | **fixed** — JSON 404 in `serve_ui` (+ test) |
| QA-3 | atexit (outputs OFF, counters flush) skipped on SIGTERM (`systemctl stop`) | medium | pre-existing | **fixed** in `app.py __main__` (SIGTERM→SystemExit); on-device verification pending (deferred D9) |
| QA-4 | `POST /api/cloud/config` wrote cloud.json non-atomically | low | pre-existing | **fixed** — `save_json_file` |
| QA-5 | `ComponentCounters.flush` lacked fsync | low | pre-existing | **fixed** |
| QA-6 | Blank Cooling temp in CSV defaults to 25 °C (< UI 30) | low | pre-existing | deferred D7 (product rule) |
| QA-7 | Simulation heater-fan counter never accrues (off-Pi only) | info | pre-existing | accepted (simulation only) |
| QA-8 | "extracted verbatim" wording vs removed C++ tier | info | introduced | accepted (plan-approved) |

## Safety invariants (plan §7)
All 10 items verified with evidence (see `final-review.md`): no PCA/GPIO from server code; tiers bridge→simulation; door/heater/verified-write paths untouched (`io_controller/` diff = one comment; `io_bridge.py` diff = door-read-once + dead key); atexit + SIGTERM; limits unchanged; atomic idiom everywhere; demo data guarded. Not run here: `qa-tool` browser harness and on-device smoke (deferred D10).
