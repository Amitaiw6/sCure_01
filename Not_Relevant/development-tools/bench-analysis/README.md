# Not_Relevant/development-tools/bench-analysis/

Parked 2026-08. Original path: `scripts/*.py`.

One-off bench-analysis scripts (`calibrate_scure_temp.py`, `live_temp_graph.py`,
`compare_delta_live.py`, `uv_led_experiment.py`, `uv_experiment_viewer.py`,
`picolog_report.py`, `scure_temp_correction.py`) used to derive the chamber
temperature calibration and UV LED characterization. Not referenced by
`pi-setup.sh`, `pi-start.sh`, `pi-kiosk.sh`, `scure.service`, `win-start.bat`
or `build-update.sh`; only cross-references among themselves and the doc
comment in `io_controller/io_controller.py` (TEMP_CHAMBER calibration).
