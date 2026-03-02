#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pigpio
import time

class Throttle:
    def __init__(self, pwm_pin=12, in1=24, in2=23, freq=800):
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise Exception("pigpio is not running!")

        self.pwm_pin = pwm_pin
        self.in1 = in1
        self.in2 = in2

        # Set pin modes
        self.pi.set_mode(self.pwm_pin, pigpio.OUTPUT)
        self.pi.set_mode(self.in1, pigpio.OUTPUT)
        self.pi.set_mode(self.in2, pigpio.OUTPUT)

        # PWM frequency suitable for L298N
        self.pi.set_PWM_frequency(self.pwm_pin, freq)
        self.pi.set_PWM_range(self.pwm_pin, 255)

        self.speed = 150  # Max PWM target (0–255)

    def set_speed(self, pwm):
        pwm = max(0, min(255, int(pwm)))
        self.speed = pwm

    # --- Internal Soft Ramp ---
    def _ramp_pwm(self, direction):
        """
        direction = 'open' or 'close'
        Smoothly ramps PWM from 0 → speed
        """

        # Set motor direction
        if direction == "open":
            self.pi.write(self.in1, 1)
            self.pi.write(self.in2, 0)
        else:
            self.pi.write(self.in1, 0)
            self.pi.write(self.in2, 1)

        # Smooth ramp-up
        for pwm in range(0, self.speed + 1, 5):   # step of 5 (smooth motion)
            self.pi.set_PWM_dutycycle(self.pwm_pin, pwm)
            time.sleep(0.02)  # 20ms per step

    # --- Public Motor Operations ---
    def open(self):
        self._ramp_pwm("open")

    def close(self):
        self._ramp_pwm("close")

    def stop(self):
        self.pi.write(self.in1, 0)
        self.pi.write(self.in2, 0)
        self.pi.set_PWM_dutycycle(self.pwm_pin, 0)

    def shutdown(self):
        self.stop()
        self.pi.stop()
