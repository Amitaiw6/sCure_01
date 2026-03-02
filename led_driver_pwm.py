import pigpio

class LEDDriverPWM:
    """
    Controls the MeanWell HLG-480H-40B LED driver using PWM duty cycle.
    Output pin drives an optocoupler/transistor that switches the DIM+ line.
    Includes safety GPIO that enables output only above threshold.
    """

    def __init__(self, pwm_pin=13, safety_pin=6, freq=2000, safety_threshold=5):
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise Exception("pigpiod is not running!")

        self.pin = pwm_pin
        self.safety_pin = safety_pin
        self.safety_threshold = safety_threshold  # %

        # Configure PWM pin
        self.pi.set_mode(self.pin, pigpio.OUTPUT)
        self.pi.set_PWM_frequency(self.pin, freq)
        self.pi.set_PWM_range(self.pin, 1000)  # High resolution

        # Configure safety pin
        self.pi.set_mode(self.safety_pin, pigpio.OUTPUT)
        self.pi.write(self.safety_pin, 0)  # Safety OFF by default

        self.set_duty(0)  # Start with LEDs off

    def set_duty(self, percent):
        """
        Set LED brightness using PWM duty cycle.
        percent: 0–100 (%)
        """
        percent = max(0, min(100, float(percent)))
        duty_value = int((percent / 100.0) * 1000)

        self.pi.set_PWM_dutycycle(self.pin, duty_value)

        # Safety logic
        if percent > self.safety_threshold:
            self.pi.write(self.safety_pin, 1)
        else:
            self.pi.write(self.safety_pin, 0)

        print(
            f"[LED PWM] Duty: {percent:.1f}% | "
            f"Safety GPIO6: {'ON' if percent > self.safety_threshold else 'OFF'}"
        )

    def off(self):
        """Turn off output (0% duty)."""
        self.set_duty(0)
