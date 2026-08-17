"""
Hardware abstraction for the sCure API: IOBridge (real io_controller drivers)
or the built-in simulation when no IO board is present.

Extracted verbatim from server/app.py (2026-08 refactor). app.py constructs
the single instance (`hw = HardwareController(io_bridge)`); every route acts
on hardware only through it, and it acts only through the bridge - server code
never writes PCA/GPIO directly.
"""

import time

# Simulation thermal model (no IO board): the simulated chamber follows the
# commanded target the way the real PI loop does, so the UI always sees a
# chamber temperature that moves toward the target.
SIM_AMBIENT = 24.0
SIM_HEAT_RATE = 0.5                      # C/s while heating toward target
SIM_COOL_RATES = {'fast': 5.0 / 60, 'medium': 2.5 / 60, 'slow': 1.0 / 60}  # C/s
SIM_IDLE_RATE = 0.05                     # C/s drift back to ambient when idle
# UI cooling modes -> fixed chamber-fan duty % (mirrors io_bridge COOLING_MODE_PWMS)
COOLING_MODE_PWMS = {'fast': 100, 'medium': 60, 'slow': 30}


class HardwareController:
    def __init__(self, bridge=None):
        self.bridge = bridge              # IOBridge (real io_controller drivers) or None
        self.chamber_temp = SIM_AMBIENT
        self._sim_time = time.time()
        self.target_temp = None
        self.door_closed = True
        self.heating = False
        self.cooling = False
        self.cooling_mode = None       # 'fast' | 'medium' | 'slow'
        self.uv_on = False
        self.uv_intensity = 0
        self.uv_wavelength = None       # 405 (Cure) | 450 (Bleaching)
        self.damper_open = False
        self.nitrogen_on = False
        self.bofa_on = False
        self._door_reclose_at = None      # sim: door re-reads closed after release
        self.fans = {
            'led_cooling': 0,
            'chamber_intake': 0,
            'chamber_heating': 0,
        }

    def _sim_tick(self):
        """Advance the simulated chamber temperature toward the target."""
        if self._door_reclose_at and time.time() >= self._door_reclose_at:
            self.door_closed = True
            self._door_reclose_at = None
        now = time.time()
        dt = min(max(now - self._sim_time, 0.0), 10.0)
        self._sim_time = now
        if dt <= 0:
            return
        if self.heating and self.target_temp is not None:
            self.chamber_temp = min(float(self.target_temp),
                                    self.chamber_temp + SIM_HEAT_RATE * dt)
        elif self.cooling and self.target_temp is not None:
            rate = SIM_COOL_RATES.get(self.cooling_mode, SIM_COOL_RATES['medium'])
            self.chamber_temp = max(float(self.target_temp),
                                    self.chamber_temp - rate * dt)
        elif self.chamber_temp > SIM_AMBIENT:
            self.chamber_temp = max(SIM_AMBIENT,
                                    self.chamber_temp - SIM_IDLE_RATE * dt)
        self.chamber_temp = round(self.chamber_temp, 1)

    def get_state(self):
        if self.bridge:
            try:
                return self.bridge.get_state()
            except Exception as e:        # noqa: BLE001 - fall back to simulation
                print(f"[HW] state read failed: {e}")
        self._sim_tick()
        base = self.chamber_temp
        return {
            'chamberTemp': self.chamber_temp,
            'targetTemp': self.target_temp,
            'doorClosed': self.door_closed,
            'isHeating': self.heating,
            'isCooling': self.cooling,
            'coolingMode': self.cooling_mode,
            'coolingFanPwm': (COOLING_MODE_PWMS.get(self.cooling_mode)
                              if self.cooling else None),
            'uvOn': self.uv_on,
            'uvIntensity': self.uv_intensity,
            'uvWavelength': self.uv_wavelength,
            'damperOpen': self.damper_open,
            'fans': self.fans,
            'fanRpm': {k: (2850 if v > 0 else 0) for k, v in self.fans.items()},
            'ledTemps': {'left': round(base + 1.5, 1), 'right': round(base + 2.0, 1),
                         'door': round(base + 0.5, 1), 'back': round(base + 1.0, 1)},
            'nitrogenActive': self.nitrogen_on,
            'n2LinePressure': 6.0,        # simulated line pressure (no sensor off-Pi)
            'bofaOn': self.bofa_on,
            'faults': {'heater': None, 'cooling': None, 'led': None},
            'hwSource': 'simulation',
        }

    def set_target_temp(self, temp):
        self.target_temp = temp
        if self.bridge:
            ok, why = self.bridge.set_target_temp(temp)
            self.heating = ok
            return ok, why
        self.heating = True               # simulation ramps toward the target
        return True, None

    def stop_heating(self):
        self.heating = False
        if self.bridge:
            return self.bridge.stop_heating()
        return True, None

    def set_fan_speed(self, fan, speed):
        self.fans[fan] = speed
        if self.bridge:
            return self.bridge.set_fan_speed(fan, speed)
        return True, None

    def set_damper(self, open_state):
        self.damper_open = open_state
        if self.bridge:
            return self.bridge.set_damper(open_state)
        return True, None

    def open_door(self):
        if self.bridge:
            return self.bridge.open_door()
        # Simulation: the magnet releases and the operator shuts the door
        # again — mirror that so the door does not stay "open" forever.
        self.door_closed = False
        self._door_reclose_at = time.time() + 5.0
        return True, None

    def ack_door_abort(self):
        """User acknowledged the door-abort alert: strip returns to normal."""
        if self.bridge:
            return self.bridge.ack_door_abort()
        return True, None      # simulation: nothing to clear

    # ---- low-level output control ----
    def set_heating(self, on):
        self.heating = bool(on)
        if on:
            self.cooling = False

    def set_cooling(self, on, mode=None):
        self.cooling = bool(on)
        self.cooling_mode = mode if on else None
        if on:
            self.heating = False

    def set_uv(self, on, intensity=0, wavelength=None):
        self.uv_on = bool(on)
        self.uv_intensity = int(intensity) if on else 0
        self.uv_wavelength = wavelength if on else None
        if self.bridge:
            return self.bridge.set_uv(bool(on), int(intensity) if on else 0,
                                      wavelength)
        return True, None

    def set_nitrogen(self, on):
        """Open/close the N2 purge valve (GPIO13 on the IO board)."""
        if self.bridge:
            ok, why = self.bridge.set_nitrogen(on)
            self.nitrogen_on = ok and bool(on)
            return ok, why
        self.nitrogen_on = bool(on)
        return True, None

    def set_rgb(self, on, color=None, brightness=None):
        """Manual RGB strip override; off-Pi it is a no-op that reports ok."""
        if self.bridge:
            return self.bridge.set_rgb(on, color, brightness)
        return True, None

    def set_bofa(self, on):
        """BOFA fume-extraction control (PCA channel 10)."""
        if self.bridge:
            ok, why = self.bridge.set_bofa(on)
            self.bofa_on = ok and bool(on)
            return ok, why
        self.bofa_on = bool(on)
        return True, None

    # ---- high-level operation functions (one per recipe process) ----
    # Each function owns starting / controlling / stopping its hardware. The
    # process ends automatically per its own logic (target reached, etc.).
    def heat_to_target_temperature(self, target_c):
        """Heat the chamber to target_c. Ends when the target is reached."""
        self.target_temp = target_c
        if self.bridge:
            return self.bridge.heat_to_target(target_c)
        self.set_uv(False)
        self.set_cooling(False)
        self.heating = True
        return True, None

    def dry_to_target_temperature(self, target_c):
        """Run drying toward target_c; the process logic stops it automatically."""
        self.target_temp = target_c
        if self.bridge:
            return self.bridge.dry_to_target(target_c)
        self.set_uv(False)
        self.set_cooling(False)
        self.heating = True
        return True, None

    def cure_uv_405(self, target_c, intensity_pct):
        """Cure: heater to target_c + UV 405 nm at intensity_pct."""
        self.target_temp = target_c
        if self.bridge:
            return self.bridge.cure_uv(target_c, intensity_pct, 405)
        self.set_cooling(False)
        self.heating = True
        self.set_uv(True, intensity_pct, 405)
        return True, None

    def cure_uv_450(self, target_c, intensity_pct):
        """Bleaching: heater to target_c + UV 450 nm at intensity_pct."""
        self.target_temp = target_c
        if self.bridge:
            return self.bridge.cure_uv(target_c, intensity_pct, 450)
        self.set_cooling(False)
        self.heating = True
        self.set_uv(True, intensity_pct, 450)
        return True, None

    def cool_to_target_temperature(self, target_c, mode):
        """Cool the chamber to target_c in mode (fast/medium/slow). Ends when reached."""
        self.target_temp = target_c
        if self.bridge:
            return self.bridge.cool_to_target(target_c, mode)
        self.set_uv(False)
        self.set_heating(False)
        self.set_cooling(True, mode)
        # FAST cooling: the LED-cooling fans join the chamber fan (mirrors
        # the io_bridge behavior so the UI sees the same fans state off-Pi).
        self.fans['led_cooling'] = 100 if mode == 'fast' else 0
        self.fans['chamber_intake'] = COOLING_MODE_PWMS.get(mode, 60)
        return True, None

    def stop_all(self, immediate=False):
        """Stop every cure output (heater, UV, cooling, N2).
        immediate=True (abort): no heater-fan run-on."""
        self.nitrogen_on = False
        if self.bridge:
            return self.bridge.stop_all(immediate)
        self.set_uv(False)
        self.set_heating(False)
        self.set_cooling(False)
        self.fans['led_cooling'] = 0
        self.fans['chamber_intake'] = 0
        return True, None

    def run_fan_test(self, fan=None):
        if self.bridge:
            return self.bridge.run_fan_test(fan)
        return {'rpm': 2850, 'status': 'OK'}

    def run_led_test(self):
        if self.bridge:
            return self.bridge.run_led_test()
        return {
            'results': [
                {'name': 'Font LED', 'temp': 62, 'status': 'OK'},
                {'name': 'Left LED', 'temp': 62, 'status': 'OK'},
                {'name': 'Door LED', 'temp': 62, 'status': 'OK'},
                {'name': 'Right LED', 'temp': 62, 'status': 'OK'},
            ]
        }
