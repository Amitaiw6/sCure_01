# io_controller/ — live IO-board driver

Python drivers for the sCure Box IO board (Raspberry Pi CM5). The Flask API
(`server/app.py`) reaches them only through `server/io_bridge.py`; server code
never touches PCA/GPIO directly.

| Module | Role |
|---|---|
| `io_controller.py` | `IOController` (PCA9685 PWM, TCA6424A expander, ADS1115 analog/NTC, servo, direct GPIO) and `SystemController` (safety interlocks: door, heater pre-flight/health check, verified writes via `set_and_verify` / `verify_each`) |
| `temperature_control.py` | `TemperatureController` — PI heating loop with delta-sigma heater output and heater-fan run-on |
| `cooling_mode.py` | `CoolingController` — damper open + fixed chamber-fan duty until the target temperature is reached |
| `system_log.py` | rotating log (`logs/curebox.log`) shared by all modules |
| `components.json` | tuning/limits (heating targets, cooling PWMs, LED min intensity, door sensor…); re-read on every activation, no restart needed |

## CLIs (bench use, on the Pi)

```
python3 io_controller.py --help                # per-component actions
python3 temperature_control.py <target_c>      # PI heating to target; --off = everything off
python3 cooling_mode.py <fan_pwm> [--target C] # cooling mode until target
```

Off-Pi the modules import (for help/listing); hardware calls fail and the API
falls back to simulation.

## Dependencies

Installed from `server/requirements.txt` by `scripts/pi-setup.sh`
(`smbus2`, `gpiozero`, `neopixel`); the `pinctrl` system tool is used for the
direct-GPIO signals.

## Parked code

Standalone legacy drivers, Tk dashboards, the C++ twin and the hardware
reference sheets moved to `Not_Relevant/legacy/io_controller/`; bench tools
built on this driver (`control_dashboard.py`, `fan_control.py`) live in
`Not_Relevant/development-tools/io_controller/`.
