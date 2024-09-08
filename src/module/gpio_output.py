import logging
import lgpio

class GPIOOutput:
    def __init__(self, h, rec_out_pin=None):
        self.h = h
        self.rec_out_pin = rec_out_pin  # This is the pin for recording

        # Set up the rec_pin as an output if it's provided
        if self.rec_out_pin is not None:
            if isinstance(self.rec_out_pin, list):
                self.rec_out_pins = self.rec_out_pin
            else:
                self.rec_out_pins = [self.rec_out_pin]
            
            for pin in self.rec_out_pins:
                try:
                    lgpio.gpio_claim_output(self.h, pin)
                    logging.info(f"REC light instantiated on pin {pin}")
                except lgpio.error as e:
                    logging.error(f"Failed to claim GPIO pin {pin}: {str(e)}")

    def set_recording(self, status):
        """Set the status of the recording pin based on the given status."""
        if hasattr(self, 'rec_out_pins'):
            for pin in self.rec_out_pins:
                try:
                    lgpio.gpio_write(self.h, pin, 1 if status else 0)
                    logging.info(f"GPIO {pin} set to {'HIGH' if status else 'LOW'}")
                except lgpio.error as e:
                    logging.error(f"Failed to set GPIO {pin}: {str(e)}")




# import logging
# import lgpio

# class GPIOOutput:
#     def __init__(self, h, rec_out_pin=None):
#         self.h = h
#         self.rec_out_pin = rec_out_pin  # This is the pin for recording

#         # Set up the rec_pin as an output if it's provided
#         if self.rec_out_pin is not None:
#             if isinstance(self.rec_out_pin, list):
#                 self.rec_out_pins = self.rec_out_pin
#             else:
#                 self.rec_out_pins = [self.rec_out_pin]
            
#             for pin in self.rec_out_pins:
#                 lgpio.gpio_claim_output(self.h, pin)
#                 logging.info(f"REC light instantiated on pin {pin}")

#     def set_recording(self, status):
#         """Set the status of the recording pin based on the given status."""
#         if hasattr(self, 'rec_out_pins'):
#             for pin in self.rec_out_pins:
#                 lgpio.gpio_write(self.h, pin, 1 if status else 0)
#                 logging.info(f"GPIO {pin} set to {'HIGH' if status else 'LOW'}")