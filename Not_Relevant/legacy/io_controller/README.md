# Not_Relevant/legacy/io_controller/

Parked 2026-08 (refactor/clean-architecture). Original path: `io_controller/`.

Superseded standalone drivers and Tk dashboards from before everything was
merged into the single live driver `io_controller/io_controller.py`:
`pca9685.py, tca6424a.py, analog_read.py, temp_monitor.py, servo.py,
gpio_control.py, gpio_manager.py, pinctrl.py, toggle_gpio.py,
write_gpio_example.py, config.py, dashboard.py`, plus the C++ twin
`io_controller.cpp`, the legacy `requirements.txt` (RPi.GPIO/smbus2 — live
deps come from `server/requirements.txt`) and the old `README.md` (kept here as
`README-old-io_controller.md`) that described the Tk GPIO dashboard.

Why parked: their only importers were each other (rg over the repo); nothing
in `server/`, `scripts/` or the kiosk uses them. Not built, not deployed.

`hardware-reference/` holds the IO-board spec artifacts (`HSI sCure (3)*.xlsx`,
`IO BOARD SCURE.pdf`, `curebox-flow-diagram.html`) — documentation, not code.
