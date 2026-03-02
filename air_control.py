#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pigpio

class AirController:
    """
    Controls the air/cooling blower using PWM on GPIO18.
    Tuned for DC brushless blowers (recommended freq = 2kHz, range = 255).
    """

    def __init__(self, pwm_pin=18, freq=50, pwm_range=255):
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise Exception("pigpiod is not running!")

        self.pwm_pin = pwm_pin

        # Set the pin mode
        self.pi.set_mode(self.pwm_pin, pigpio.OUTPUT)

        # Set recommended frequency (500Hz)
        self.pi.set_PWM_frequency(self.pwm_pin, freq)

        # Set PWM range (0–255)
        self.pi.set_PWM_range(self.pwm_pin, pwm_range)

        # Start with fan OFF
        self.set_air_percent(0)

    def set_air_percent(self, percent: float):
        """
        Set air blower speed in percent (0–100).
        Converts percentage to 0–255 duty cycle.
        """
        percent = max(0.0, min(100.0, float(percent)))
        pwm_range = self.pi.get_PWM_range(self.pwm_pin)

        duty = int((percent / 100.0) * pwm_range)
        self.pi.set_PWM_dutycycle(self.pwm_pin, duty)

        print(f"[AIR] PWM set to {percent}%  (duty={duty})")

    def off(self):
        self.set_air_percent(0)

    def stop(self):
        self.pi.set_PWM_dutycycle(self.pwm_pin, 0)
        self.pi.stop()
