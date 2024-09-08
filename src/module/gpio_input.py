import threading
import logging
import time
import lgpio

class GPIOInput:
    def __init__(self, h, cinepi_controller, redis_controller, 
                 rec_button=None,
                 rec_button_inv=False,
                 iso_inc_button=None,
                 iso_inc_button_inv=False,
                 iso_dec_button=None,
                 iso_dec_button_inv=False,
                 res_switch=None,
                 res_switch_inv=False,
                 pwm_switch=None, 
                 pwm_switch_inv=False,
                 shutter_a_sync_switch=None, 
                 shutter_a_sync_switch_inv=False, 
                 fps_button=None,
                 fps_button_inv=False,
                 fps_switch=None,
                 fps_switch_inv=False,
                 pot_lock_switch=None,
                 pot_lock_switch_inv=False
                ):
        
        self.h = h
        self.cinepi_controller = cinepi_controller
        self.redis_controller = redis_controller
        
        self.buttons = {}

        self.fps_button_inverse = False
        self.fps_original = float(self.redis_controller.get_value('fps_actual'))
        self.fps_temp = 24
        self.fps_double = False
        self.ramp_up_speed = 0.1
        self.ramp_down_speed = 0.1

        button_configs = [
            (iso_inc_button, self.iso_inc_callback, "iso_inc_button", iso_inc_button_inv),
            (iso_dec_button, self.iso_dec_callback, "iso_dec_button", iso_dec_button_inv),
            (res_switch, self.res_switch_callback, "res_switch", res_switch_inv),
            (pwm_switch, self.pwm_switch_callback, "pwm_switch", pwm_switch_inv),
            (shutter_a_sync_switch, self.sync_switch_callback, "shutter_a_sync_switch", shutter_a_sync_switch_inv),
            (fps_button, self.fps_button_callback, "fps_button", fps_button_inv),
            (fps_switch, self.fps_switch_callback, "fps_switch", fps_switch_inv),
            (pot_lock_switch, self.pot_lock_switch_callback, "pot_lock_switch", pot_lock_switch_inv)
        ]

        for config in button_configs:
            self.setup_button(*config)

        if rec_button is not None:
            if isinstance(rec_button, list):
                for pin in rec_button:
                    self.setup_button(pin, self.recording_callback, f"rec_button_{pin}", rec_button_inv)
            else:
                self.setup_button(rec_button, self.recording_callback, "rec_button", rec_button_inv)
        
        self.start_polling()

    def _inverse_logic(self, value, inverse):
        return not value if inverse else value

    def setup_button(self, pin, callback, attribute_name, inverse=False):
        if pin is not None:
            try:
                lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_UP)
                self.buttons[pin] = {
                    'callback': callback,
                    'inverse': inverse,
                    'attribute_name': attribute_name,
                    'last_state': None
                }
                setattr(self, attribute_name, pin)
                logging.info(f"{attribute_name} instantiated on pin {pin}")
            except lgpio.error as e:
                logging.warning(f"Failed to set up {attribute_name} on pin {pin}: {str(e)}. Skipping this pin.")

    def start_polling(self):
        threading.Thread(target=self._poll_gpio, daemon=True).start()

    def _poll_gpio(self):
        while True:
            for pin, button in self.buttons.items():
                try:
                    state = self._inverse_logic(lgpio.gpio_read(self.h, pin) == 0, button['inverse'])
                    if state != button['last_state']:
                        button['callback'](state)
                        button['last_state'] = state
                except lgpio.error as e:
                    logging.error(f"Error reading GPIO {pin}: {str(e)}")
            time.sleep(0.01)  # Poll every 10ms

    # ... (rest of the callback methods remain the same)

    def recording_callback(self, state):
        if state:
            self.cinepi_controller.rec_button_pushed()

    def pot_lock_switch_callback(self, state):
        self.cinepi_controller.set_parameters_lock(state)
        logging.info(f"pot_lock_switch state {state}")

    def res_switch_callback(self, state):
        self.cinepi_controller.switch_resolution()
        logging.info(f"res_switch state {state}")

    def fps_switch_callback(self, state):
        self.cinepi_controller.fps_double = not state
        self.cinepi_controller.switch_fps()
        logging.info(f"fps_switch state {state}")
        
    def fps_button_callback(self, state):
        fps_button_state_old = self.cinepi_controller.fps_button_state
        self.cinepi_controller.lock_override = True

        self.cinepi_controller.fps_button_state = state

        if fps_button_state_old and fps_button_state_old != self.cinepi_controller.fps_button_state:
            if not self.cinepi_controller.pwm_mode:
                if not self.fps_double:
                    self.fps_temp = float(self.redis_controller.get_value('fps_actual'))
                    fps_new = self.fps_temp * 2
                    fps_max = float(self.redis_controller.get_value('fps_max', default=50))
                    fps_new = min(fps_new, fps_max)
                    self.cinepi_controller.set_fps(fps_new)
                    self.fps_double = True
                else:
                    self.cinepi_controller.set_fps(self.fps_temp)
                    self.fps_double = False
            else:
                if not self.fps_double:
                    self.fps_temp = float(self.redis_controller.get_value('fps_actual'))
                    fps_target = self.fps_temp * 2
                    fps_max = float(self.redis_controller.get_value('fps_max', default=50))
                    fps_target = min(fps_target, fps_max)

                    while float(self.redis_controller.get_value('fps_actual')) < int(float(self.redis_controller.get_value('fps_max'))):
                        logging.info('ramping up')
                        fps_current = float(self.redis_controller.get_value('fps_actual'))
                        fps_next = fps_current + 1
                        self.cinepi_controller.set_fps(int(fps_next))
                        time.sleep(self.ramp_up_speed)
                    self.fps_double = True
                else:
                    while float(self.redis_controller.get_value('fps_actual')) > self.fps_temp:
                        logging.info('ramping down')
                        fps_current = float(self.redis_controller.get_value('fps_actual'))
                        fps_next = fps_current - 1
                        self.cinepi_controller.set_fps(int(fps_next))
                        time.sleep(self.ramp_down_speed)
                    self.fps_double = False

            logging.info(f"fps_button state {self.cinepi_controller.fps_button_state}")

        self.cinepi_controller.lock_override = False

    def iso_inc_callback(self, state):
        if state:
            self.cinepi_controller.inc_iso()

    def iso_dec_callback(self, state):
        if state:
            self.cinepi_controller.dec_iso()
    
    def pwm_switch_callback(self, state):
        if self.cinepi_controller.pwm_controller.PWM_pin in [None, 18, 19]:
            self.cinepi_controller.set_pwm_mode(state)
            logging.info(f"pwm_switch state {state}")
                 
    def sync_switch_callback(self, state):
        self.cinepi_controller.set_shutter_a_sync(state)
        logging.info(f"shutter_a_sync_switch state {state}")


# import threading
# import logging
# import time
# import lgpio

# class GPIOInput:
#     def __init__(self, h, cinepi_controller, redis_controller, 
#                  rec_button=None,
#                  rec_button_inv=False,
#                  iso_inc_button=None,
#                  iso_inc_button_inv=False,
#                  iso_dec_button=None,
#                  iso_dec_button_inv=False,
#                  res_switch=None,
#                  res_switch_inv=False,
#                  pwm_switch=None, 
#                  pwm_switch_inv=False,
#                  shutter_a_sync_switch=None, 
#                  shutter_a_sync_switch_inv=False, 
#                  fps_button=None,
#                  fps_button_inv=False,
#                  fps_switch=None,
#                  fps_switch_inv=False,
#                  pot_lock_switch=None,
#                  pot_lock_switch_inv=False
#                 ):
        
#         self.h = h
#         self.cinepi_controller = cinepi_controller
#         self.redis_controller = redis_controller
        
#         self.buttons = []  # Store all buttons for future references or cleanups

#         self.fps_button_inverse = False
        
#         self.fps_original = float(self.redis_controller.get_value('fps_actual'))
        
#         self.fps_temp = 24
        
#         self.fps_double = False
        
#         self.ramp_up_speed = 0.1
#         self.ramp_down_speed = 0.1

#         self.setup_button(iso_inc_button, self.iso_inc_callback, "iso_inc_button", iso_inc_button_inv)
#         self.setup_button(iso_dec_button, self.iso_dec_callback, "iso_dec_button", iso_dec_button_inv)
#         self.setup_button(res_switch, self.res_switch_callback, "res_switch", res_switch_inv, react_to_both=True)
#         self.setup_button(pwm_switch, self.pwm_switch_callback, "pwm_switch", pwm_switch_inv, react_to_both=True)
#         self.setup_button(shutter_a_sync_switch, self.sync_switch_callback, "shutter_a_sync_switch", shutter_a_sync_switch_inv, react_to_both=True)
#         self.setup_button(fps_button, self.fps_button_callback, "fps_button", fps_button_inv, react_to_both=True)
#         self.setup_button(fps_switch, self.fps_switch_callback, "fps_switch", fps_switch_inv, react_to_both=True)
#         self.setup_button(pot_lock_switch, self.pot_lock_switch_callback, "pot_lock_switch", pot_lock_switch_inv, react_to_both=True)

#         if rec_button is not None:
#             if isinstance(rec_button, list):
#                 for pin in rec_button:
#                     self.setup_button(pin, self.recording_callback, f"rec_button_{pin}", rec_button_inv)
#             else:
#                 self.setup_button(rec_button, self.recording_callback, "rec_button", rec_button_inv)
        
#         # Check initial states
#         self.check_initial_states()

#     def _inverse_logic(self, value, inverse):
#         return not value if inverse else value

#     def setup_button(self, pin, callback, attribute_name, inverse=False, react_to_both=False):
#         if pin is not None:
#             lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_UP)
#             lgpio.gpio_set_debounce_micros(self.h, pin, 10000)  # 10ms debounce
            
#             if react_to_both:
#                 lgpio.gpio_set_alert_func(self.h, pin, lambda g, l, t: self._gpio_callback(g, l, t, callback, inverse))
#             else:
#                 lgpio.gpio_set_alert_func(self.h, pin, lambda g, l, t: self._gpio_callback(g, l, t, callback, inverse) if l == 0 else None)
            
#             self.buttons.append(pin)
#             setattr(self, attribute_name, pin)
#             logging.info(f"{attribute_name} instantiated on pin {pin}")

#     def _gpio_callback(self, gpio, level, tick, callback, inverse):
#         state = self._inverse_logic(level == 0, inverse)
#         callback(state)

#     def check_initial_states(self):
#         for attr, pin in vars(self).items():
#             if isinstance(pin, int) and hasattr(self, f"{attr}_callback"):
#                 state = self._inverse_logic(lgpio.gpio_read(self.h, pin) == 0, False)
#                 getattr(self, f"{attr}_callback")(state)

#     def recording_callback(self, state):
#         if state:
#             self.cinepi_controller.rec_button_pushed()

#     def pot_lock_switch_callback(self, state):
#         self.cinepi_controller.set_parameters_lock(state)
#         logging.info(f"pot_lock_switch state {state}")

#     def res_switch_callback(self, state):
#         self.cinepi_controller.switch_resolution()
#         logging.info(f"res_switch state {state}")

#     def fps_switch_callback(self, state):
#         self.cinepi_controller.fps_double = not state
#         self.cinepi_controller.switch_fps()
#         logging.info(f"fps_switch state {state}")
        
#     def fps_button_callback(self, state):
#         fps_button_state_old = self.cinepi_controller.fps_button_state
#         self.cinepi_controller.lock_override = True

#         self.cinepi_controller.fps_button_state = state

#         if fps_button_state_old and fps_button_state_old != self.cinepi_controller.fps_button_state:
#             if not self.cinepi_controller.pwm_mode:
#                 if not self.fps_double:
#                     self.fps_temp = float(self.redis_controller.get_value('fps_actual'))
#                     fps_new = self.fps_temp * 2
#                     fps_max = float(self.redis_controller.get_value('fps_max', default=50))
#                     fps_new = min(fps_new, fps_max)
#                     self.cinepi_controller.set_fps(fps_new)
#                     self.fps_double = True
#                 else:
#                     self.cinepi_controller.set_fps(self.fps_temp)
#                     self.fps_double = False
#             else:
#                 if not self.fps_double:
#                     self.fps_temp = float(self.redis_controller.get_value('fps_actual'))
#                     fps_target = self.fps_temp * 2
#                     fps_max = float(self.redis_controller.get_value('fps_max', default=50))
#                     fps_target = min(fps_target, fps_max)

#                     while float(self.redis_controller.get_value('fps_actual')) < int(float(self.redis_controller.get_value('fps_max'))):
#                         logging.info('ramping up')
#                         fps_current = float(self.redis_controller.get_value('fps_actual'))
#                         fps_next = fps_current + 1
#                         self.cinepi_controller.set_fps(int(fps_next))
#                         time.sleep(self.ramp_up_speed)
#                     self.fps_double = True
#                 else:
#                     while float(self.redis_controller.get_value('fps_actual')) > self.fps_temp:
#                         logging.info('ramping down')
#                         fps_current = float(self.redis_controller.get_value('fps_actual'))
#                         fps_next = fps_current - 1
#                         self.cinepi_controller.set_fps(int(fps_next))
#                         time.sleep(self.ramp_down_speed)
#                     self.fps_double = False

#             logging.info(f"fps_button state {self.cinepi_controller.fps_button_state}")

#         self.cinepi_controller.lock_override = False

#     def iso_inc_callback(self, state):
#         if state:
#             self.cinepi_controller.inc_iso()

#     def iso_dec_callback(self, state):
#         if state:
#             self.cinepi_controller.dec_iso()
    
#     def pwm_switch_callback(self, state):
#         if self.cinepi_controller.pwm_controller.PWM_pin in [None, 18, 19]:
#             self.cinepi_controller.set_pwm_mode(state)
#             logging.info(f"pwm_switch state {state}")
                 
#     def sync_switch_callback(self, state):
#         self.cinepi_controller.set_shutter_a_sync(state)
#         logging.info(f"shutter_a_sync_switch state {state}")