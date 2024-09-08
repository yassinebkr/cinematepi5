import time
import subprocess
import logging
import lgpio

class PWMController:
    def __init__(self, h, sensor_detect, PWM_pin=None, PWM_inv_pin=None, start_freq=24, shutter_angle=180, trigger_mode=0):
        self.h = h
        self.sensor_detect = sensor_detect
        
        self.PWM_pin = PWM_pin
        self.PWM_inv_pin = PWM_inv_pin
        
        if PWM_pin not in [None, 18, 19]:
            logging.warning(f"Invalid PWM_pin value: {PWM_pin}. Should be None, 18, or 19.")
        
        self.fps = start_freq
        self.shutter_angle = shutter_angle
        
        self.freq = start_freq
        self.period = 1.0 / self.freq
        self.duty_cycle = 500000  # 50% duty cycle (0-1000000)
        self.exposure_time = (self.shutter_angle / 360.0) * self.period
        
        self.pwm_active = False
        
        if PWM_pin in [18, 19]:
            try:
                lgpio.gpio_claim_output(self.h, self.PWM_pin)
                logging.info(f"PWM controller instantiated on PWM_pin {PWM_pin}")
            except lgpio.error as e:
                logging.error(f"Failed to claim PWM pin {PWM_pin}: {str(e)}")
                self.PWM_pin = None  # Set PWM_pin to None if we fail to claim it
        
        self.set_freq(start_freq)
        self.set_duty_cycle(shutter_angle)
        self.set_trigger_mode(trigger_mode)

    def start_pwm(self, freq=None, shutter_angle=None, trigger_mode=None):
        if freq is not None:
            self.set_freq(freq)
        if shutter_angle is not None:
            self.set_duty_cycle(shutter_angle)
        if trigger_mode is not None:
            self.set_trigger_mode(trigger_mode)
        
        if self.PWM_pin is not None:
            try:
                lgpio.tx_pwm(self.h, self.PWM_pin, self.freq, self.duty_cycle)
                self.pwm_active = True
                logging.info(f"PWM started on pin {self.PWM_pin} with freq {self.freq}Hz and duty cycle {self.duty_cycle/10000:.1f}%")
            except lgpio.error as e:
                logging.error(f"Failed to start PWM: {str(e)}")
        else:
            logging.warning("No PWM pin specified. PWM not started.")

    def stop_pwm(self):
        if self.pwm_active and self.PWM_pin is not None:
            try:
                lgpio.tx_pwm(self.h, self.PWM_pin, 0, 0)
                self.pwm_active = False
                logging.info(f"PWM stopped on pin {self.PWM_pin}")
            except lgpio.error as e:
                logging.error(f"Failed to stop PWM: {str(e)}")
        
        self.set_trigger_mode(0)

    def set_trigger_mode(self, value):
        if value not in [0, 2]:
            raise ValueError("Invalid trigger mode. Must be 0 or 2.")
        
        if self.sensor_detect.camera_model == 'imx477':
            command = f'echo {value} > /sys/module/imx477/parameters/trigger_mode'
        elif self.sensor_detect.camera_model == 'imx296':
            command = f'echo {1 if value == 2 else 0} > /sys/module/imx296/parameters/trigger_mode'
        else:
            logging.warning(f"Unsupported camera model: {self.sensor_detect.camera_model}")
            return
        
        try:
            subprocess.run(['sudo', 'sh', '-c', command], check=True)
            logging.info(f"Trigger mode set to {value}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to set trigger mode: {str(e)}")

    def set_freq(self, new_freq):
        self.freq = max(min(new_freq, 50), 1)  # Clamp between 1 and 50 Hz
        self.period = 1.0 / self.freq
        self.update_pwm()

    def set_duty_cycle(self, shutter_angle):
        self.shutter_angle = max(min(shutter_angle, 360), 1)  # Clamp between 1 and 360 degrees
        self.exposure_time = (self.shutter_angle / 360.0) * self.period
        self.duty_cycle = int((1 - (self.exposure_time / self.period)) * 1000000)
        self.update_pwm()

    def update_pwm(self):
        if self.pwm_active and self.PWM_pin is not None:
            try:
                lgpio.tx_pwm(self.h, self.PWM_pin, self.freq, self.duty_cycle)
                logging.info(f"PWM updated: freq={self.freq}Hz, duty_cycle={self.duty_cycle/10000:.1f}%, shutter_angle={self.shutter_angle}°")
            except lgpio.error as e:
                logging.error(f"Failed to update PWM: {str(e)}")

    def set_pwm(self, fps=None, shutter_angle=None):
        if fps is not None:
            self.set_freq(fps)
        if shutter_angle is not None:
            self.set_duty_cycle(shutter_angle)

    def ramp_mode(self, ramp_mode):
        if ramp_mode not in [0, 2, 3]:
            raise ValueError("Invalid ramp mode. Must be 0, 2, or 3.")
        
        if ramp_mode in [2, 3]:
            self.start_pwm()
            self.set_trigger_mode(2)
        else:
            self.stop_pwm()