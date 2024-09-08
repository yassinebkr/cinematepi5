import time
import threading
import logging
import os
import signal
import sys
import lgpio

class SystemButton:
    def __init__(self, h, cinepi_controller, redis_controller, ssd_monitor, system_button_pin=None):
        self.h = h
        self.system_button_pin = system_button_pin
        self.system_button = None
        
        if self.system_button_pin is not None:
            lgpio.gpio_claim_input(self.h, self.system_button_pin, lgpio.SET_PULL_UP)
            lgpio.gpio_set_debounce_micros(self.h, self.system_button_pin, 10000)  # 10ms debounce

        self.cinepi_controller = cinepi_controller
        self.redis_controller = redis_controller
        self.ssd_monitor = ssd_monitor

        self.last_press_time = 0
        self.click_count = 0
        self.click_timer = None
        
        self.click_was_held = False
        self.press_start_time = None

        # Set up the signal handler for SIGINT (Ctrl+C)
        signal.signal(signal.SIGINT, self.cleanup)

        # Start the polling thread
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            while True:
                if self.system_button_pin is not None:
                    state = lgpio.gpio_read(self.h, self.system_button_pin) == 0
                    if state:
                        if self.press_start_time is None:
                            self.press_start_time = time.time()
                        elif time.time() - self.press_start_time >= 3:
                            self.system_button_held()
                    else:
                        if self.press_start_time is not None:
                            press_duration = time.time() - self.press_start_time
                            if press_duration < 3:
                                self.system_button_released()
                            self.press_start_time = None
                time.sleep(0.01)  # Poll every 10ms
        except KeyboardInterrupt:
            self.cleanup(signal.SIGINT, None)

    def system_button_pressed(self):
        current_time = time.time()
        if current_time - self.last_press_time < 1.5:
            self.click_count += 1
        else:
            self.click_count = 1
        self.last_press_time = current_time

    def system_button_held(self):
        logging.info("System button held for 3 seconds.")
        self.ssd_monitor.unmount_drive()
        self.click_count = 0  # Reset the click count after a hold
        self.click_was_held = True 

    def system_button_released(self):
        if self.click_count > 0:
            if self.click_timer:
                self.click_timer.cancel()
            self.click_timer = threading.Timer(1.5, self.handle_clicks)
            self.click_timer.start()
        self.click_was_held = False

    def handle_clicks(self):
        if self.click_count == 1 and not self.click_was_held:
            logging.info("System button clicked once.")
            self.cinepi_controller.switch_resolution()
        elif self.click_count == 2:
            logging.info("System button double-clicked.")
            self.restart_camera()
        elif self.click_count == 3:
            logging.info("System button triple-clicked.")
            self.system_restart()
        elif self.click_count == 4:
            logging.info("System button quadruple-clicked.")
            self.safe_shutdown()
        elif self.click_count > 4:
            logging.info(f"System button clicked {self.click_count} times.")

        self.click_count = 0
        self.click_was_held = False

    def restart_camera(self):
        self.redis_controller.set_value('cam_init', 1)

    def system_restart(self):
        try:
            logging.info("Restarting system...")
            os.system('sudo reboot')
        except Exception as e:
            logging.error(f"Error restarting system: {e}")

    def safe_shutdown(self):
        if self.redis_controller.get_value('is_recording') == "1":
            self.cinepi_controller.stop_recording()
        logging.info("Initiating safe system shutdown.")
        os.system("sudo shutdown -h now")

    def cleanup(self, signum, frame):
        logging.info("Cleaning up and exiting...")
        sys.exit(0)


# import time
# import threading
# import logging
# import os
# import signal
# import sys
# import lgpio

# class SystemButton:
#     def __init__(self, h, cinepi_controller, redis_controller, ssd_monitor, system_button_pin=None):
#         self.h = h
#         self.system_button_pin = system_button_pin
#         self.system_button = None
        
#         if self.system_button_pin is not None:
#             lgpio.gpio_claim_input(self.h, self.system_button_pin, lgpio.SET_PULL_UP)
#             lgpio.gpio_set_debounce_micros(self.h, self.system_button_pin, 10000)  # 10ms debounce  # 10ms debounce

#         self.cinepi_controller = cinepi_controller
#         self.redis_controller = redis_controller
#         self.ssd_monitor = ssd_monitor

#         self.last_press_time = 0
#         self.click_count = 0
#         self.click_timer = None
        
#         self.click_was_held = False

#         # Set up the signal handler for SIGINT (Ctrl+C)
#         signal.signal(signal.SIGINT, self.cleanup)

#         # Start the polling thread
#         threading.Thread(target=self.run, daemon=True).start()

#     def run(self):
#         try:
#             while True:
#                 if self.system_button_pin is not None:
#                     state = lgpio.gpio_read(self.h, self.system_button_pin) == 0
#                     if state:
#                         self.system_button_pressed()
#                     else:
#                         self.system_button_released()
#                 time.sleep(0.01)  # Poll every 10ms
#         except KeyboardInterrupt:
#             self.cleanup(signal.SIGINT, None)

#     # ... (rest of the methods remain the same)

#     def cleanup(self, signum, frame):
#         # Handle cleanup actions here
#         logging.info("Cleaning up and exiting...")
#         sys.exit(0)



# import time
# import threading
# import logging
# import os
# import signal
# import sys
# import lgpio

# class SystemButton:
#     def __init__(self, h, cinepi_controller, redis_controller, ssd_monitor, system_button_pin=None):
#         self.h = h
#         self.system_button_pin = system_button_pin
        
#         if self.system_button_pin is not None:
#             lgpio.gpio_claim_input(self.h, self.system_button_pin, lgpio.SET_PULL_UP)
#             lgpio.gpio_set_debounce(self.h, self.system_button_pin, 10000)  # 10ms debounce
#             lgpio.gpio_set_alert_func(self.h, self.system_button_pin, self.button_callback)

#         self.cinepi_controller = cinepi_controller
#         self.redis_controller = redis_controller
#         self.ssd_monitor = ssd_monitor

#         self.last_press_time = 0
#         self.click_count = 0
#         self.click_timer = None
#         self.press_start_time = None
        
#         self.click_was_held = False

#         # Set up the signal handler for SIGINT (Ctrl+C)
#         signal.signal(signal.SIGINT, self.cleanup)

#     def button_callback(self, gpio, level, tick):
#         if level == 0:  # Button pressed
#             self.press_start_time = time.time()
#             self.system_button_pressed()
#         else:  # Button released
#             press_duration = time.time() - self.press_start_time
#             if press_duration >= 3:
#                 self.system_button_held()
#             else:
#                 self.system_button_released()

#     def system_button_held(self):
#         logging.info("System button held for 3 seconds.")
#         self.unmount_drive()
#         self.click_count = 0  # Reset the click count after a hold
#         self.click_was_held = True

#     def system_button_pressed(self):
#         current_time = time.time()

#         if current_time - self.last_press_time < 1.5:
#             self.click_count += 1
#         else:
#             self.click_count = 1

#         self.last_press_time = current_time

#     def system_button_released(self):
#         if self.click_count > 0:
#             # If there were consecutive clicks, start the timer for handling clicks
#             if self.click_timer:
#                 self.click_timer.cancel()

#             self.click_timer = threading.Timer(1.5, self.handle_clicks)
#             self.click_timer.start()
#         self.click_was_held = False

#     def handle_clicks(self):
#         if self.click_count == 1 and not self.click_was_held:
#             logging.info("System button clicked once.")
#             self.cinepi_controller.switch_resolution()
#         elif self.click_count == 2:
#             logging.info("System button double-clicked.")
#             self.restart_camera()
#         elif self.click_count == 3:
#             logging.info("System button triple-clicked.")
#             self.system_restart()
#         elif self.click_count == 4:
#             logging.info("System button quadruple-clicked.")
#             self.safe_shutdown()
#         elif self.click_count > 4:
#             logging.info(f"System button clicked {self.click_count} times.")

#         self.click_count = 0
#         self.click_was_held = False

#     def unmount_drive(self):
#         self.ssd_monitor.unmount_drive()

#     def safe_shutdown(self):
#         if self.redis_controller.get_value('is_recording') == "1":
#             self.stop_recording()

#         logging.info("Initiating safe system shutdown.")
#         os.system("sudo shutdown -h now")

#     def system_restart(self):
#         try:
#             logging.info("Restarting system...")
#             os.system('sudo reboot')
#         except Exception as e:
#             logging.error(f"Error restarting system: {e}")
            
#     def restart_camera(self):
#         self.redis_controller.set_value('cam_init', 1)

#     def cleanup(self, signum, frame):
#         # Handle cleanup actions here
#         logging.info("Cleaning up and exiting...")
#         if self.system_button_pin is not None:
#             lgpio.gpio_set_alert_func(self.h, self.system_button_pin, None)
#         sys.exit(0)

#     def run(self):
#         try:
#             while True:
#                 time.sleep(0.1)
#         except KeyboardInterrupt:
#             self.cleanup(signal.SIGINT, None)