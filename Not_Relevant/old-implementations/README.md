# Not_Relevant/old-implementations/

Parked 2026-08. Earlier implementations of functionality that is live elsewhere.

| Item | Original path | Superseded by |
|---|---|---|
| `server-hardware-cpp/` (`hw_driver.cpp`, `temperature_control.hpp`, `build.sh`) | `server/hardware/` | `server/io_bridge.py` → `io_controller/`. The pybind11 tier was never built by `pi-setup.sh` (no `.so` in tree); `HardwareController` is now IOBridge → simulation only |
| `control_dashboard1.py` | `io_controller/` | `development-tools/io_controller/control_dashboard.py` (later revision) |
