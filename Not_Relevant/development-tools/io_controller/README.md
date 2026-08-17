# Not_Relevant/development-tools/io_controller/

Parked 2026-08. Original path: `io_controller/control_dashboard.py`,
`io_controller/fan_control.py`.

Bench tools built ON the live driver (`io_controller/io_controller.py`): a Tk
control dashboard and a fan CLI. Not part of the kiosk software; kept
runnable via a `sys.path` shim at the top of each file that points at
`<repo>/io_controller/`. Run on the Pi:

```
python3 Not_Relevant/development-tools/io_controller/fan_control.py status
python3 Not_Relevant/development-tools/io_controller/control_dashboard.py
```
