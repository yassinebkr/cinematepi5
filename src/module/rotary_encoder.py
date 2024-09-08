import logging
import lgpio
import threading
import time

class SimpleRotaryEncoder:
    def __init__(self, h, cinepi_controller, setting=None, clk=None, dt=None):
        self.h = h
        self.cinepi_controller = cinepi_controller
        self.setting = setting
        self.clk = clk
        self.dt = dt
        self.last_clk_state = None
        self.last_dt_state = None

        if clk is not None and dt is not None:
            lgpio.gpio_claim_input(self.h, clk, lgpio.SET_PULL_UP)
            lgpio.gpio_claim_input(self.h, dt, lgpio.SET_PULL_UP)
            lgpio.gpio_set_debounce_micros(self.h, clk, 10000)  # 10ms debounce
            lgpio.gpio_set_debounce_micros(self.h, dt, 10000)  # 10ms debounce
            self.start_monitoring()
            logging.info(f"{self.setting} rotary encoder instantiated on clk {clk}, dt {dt}")

    def start_monitoring(self):
        threading.Thread(target=self._monitor_gpio, daemon=True).start()

    def _monitor_gpio(self):
        while True:
            clk_state = lgpio.gpio_read(self.h, self.clk)
            dt_state = lgpio.gpio_read(self.h, self.dt)

            if clk_state != self.last_clk_state:
                if dt_state != clk_state:
                    self.clockwise_turn()
                else:
                    self.counter_clockwise_turn()

            self.last_clk_state = clk_state
            self.last_dt_state = dt_state
            time.sleep(0.001)  # Small delay to prevent excessive CPU usage

    def clockwise_turn(self):
        getattr(self.cinepi_controller, f"inc_{self.setting}")()
        logging.info(f"{self.setting} rotary encoder UP")

    def counter_clockwise_turn(self):
        getattr(self.cinepi_controller, f"dec_{self.setting}")()
        logging.info(f"{self.setting} rotary encoder DOWN")


# import logging
# import lgpio

# class SimpleRotaryEncoder:
#     def __init__(self, h, cinepi_controller, setting=None, clk=None, dt=None):
#         self.h = h
#         self.cinepi_controller = cinepi_controller
#         self.setting = setting
#         self.clk = clk
#         self.dt = dt
#         self.last_clk_state = None
#         self.last_dt_state = None

#         if clk is not None and dt is not None:
#             lgpio.gpio_claim_input(self.h, clk, lgpio.SET_PULL_UP)
#             lgpio.gpio_claim_input(self.h, dt, lgpio.SET_PULL_UP)
#             lgpio.gpio_set_alert_func(self.h, clk, self._gpio_callback)
#             lgpio.gpio_set_alert_func(self.h, dt, self._gpio_callback)
#             logging.info(f"{self.setting} rotary encoder instantiated on clk {clk}, dt {dt}")

#     def _gpio_callback(self, gpio, level, tick):
#         clk_state = lgpio.gpio_read(self.h, self.clk)
#         dt_state = lgpio.gpio_read(self.h, self.dt)

#         if gpio == self.clk and clk_state != self.last_clk_state:
#             if dt_state != clk_state:
#                 self.clockwise_turn()
#             else:
#                 self.counter_clockwise_turn()

#         self.last_clk_state = clk_state
#         self.last_dt_state = dt_state

#     def clockwise_turn(self):
#         getattr(self.cinepi_controller, f"inc_{self.setting}")()
#         logging.info(f"{self.setting} rotary encoder UP")

#     def counter_clockwise_turn(self):
#         getattr(self.cinepi_controller, f"dec_{self.setting}")()
#         logging.info(f"{self.setting} rotary encoder DOWN")