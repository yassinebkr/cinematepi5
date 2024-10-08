import logging
import sys
import traceback
import threading
import json
from signal import pause
import lgpio
import os

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.redis_controller import RedisController
from module.cinepi_app import CinePi
from module.usb_monitor import USBMonitor
from module.ssd_monitor import SSDMonitor
from module.gpio_output import GPIOOutput
from module.cinepi_controller import CinePiController
from module.simple_gui import SimpleGUI
from module.gpio_input import GPIOInput
from module.analog_controls import AnalogControls
from module.grove_base_hat_adc import ADC
from module.keyboard import Keyboard
from module.system_button import SystemButton
from module.cli_commands import CommandExecutor
from module.serial_handler import SerialHandler
from module.logger import configure_logging
from module.rotary_encoder import SimpleRotaryEncoder
from module.PWMcontroller import PWMController
from module.sensor_detect import SensorDetect
from module.mediator import Mediator
from module.dmesg_monitor import DmesgMonitor
from module.redis_listener import RedisListener

MODULES_OUTPUT_TO_SERIAL = ['cinepi_controller']

def load_settings(filename):
    with open(filename, 'r') as file:
        settings = json.load(file)
        additional_shutter_a_steps = settings.get('additional_shutter_a_steps', [])
        shutter_a_steps = sorted(set(range(1, 361)).union(additional_shutter_a_steps))
        settings['shutter_a_steps'] = shutter_a_steps
        return settings

if __name__ == "__main__":
    logger, log_queue = configure_logging(MODULES_OUTPUT_TO_SERIAL)
    
    settings = load_settings('/home/pi/cinemate/src/settings.json')

    # Initialize lgpio
    h = lgpio.gpiochip_open(0)
    if h < 0:
        logger.error("Failed to open gpiochip")
        sys.exit(1)

    # Detect sensor
    sensor_detect = SensorDetect()
    
    # Instantiate the PWMController
    pwm_controller = PWMController(h, sensor_detect, PWM_pin=settings['pwm_pin'])

    # Instantiate other necessary components
    redis_controller = RedisController()

    # Instantiate the CinePi instance
    cinepi_app = CinePi(redis_controller, sensor_detect)

    ssd_monitor = SSDMonitor()
    usb_monitor = USBMonitor(ssd_monitor)

    try:
        gpio_output = GPIOOutput(h, rec_out_pin=settings['rec_out_pin'])
    except Exception as e:
        logging.error(f"Failed to initialize GPIOOutput: {str(e)}")
        gpio_output = None

    #gpio_output = GPIOOutput(h, rec_out_pin=settings['rec_out_pin'])
    
    dmesg_monitor = DmesgMonitor("/var/log/kern.log")
    dmesg_monitor.start() 

    # Instantiate the CinePiController with all necessary components and settings
    cinepi_controller = CinePiController(pwm_controller,
                                        redis_controller,
                                        usb_monitor, 
                                        ssd_monitor,
                                        sensor_detect,
                                        iso_steps=settings['iso_steps'],
                                        shutter_a_steps=settings['shutter_a_steps'],
                                        fps_steps=settings['fps_steps'],
                                        wb_steps=settings.get('wb_steps', [])
                                        )

    # Instantiate the AnalogControls component
    analog_controls = AnalogControls(cinepi_controller, redis_controller, 
                                 iso_pot=settings['analog_controls']['iso_pot'], 
                                 shutter_a_pot=settings['analog_controls']['shutter_a_pot'], 
                                 fps_pot=settings['analog_controls']['fps_pot'])
    # analog_controls = AnalogControls(cinepi_controller, iso_pot=settings['analog_controls']['iso_pot'], shutter_a_pot=settings['analog_controls']['shutter_a_pot'], fps_pot=settings['analog_controls']['fps_pot'])

    # Instantiate the GPIOControls component
    gpio_input = GPIOInput(h, cinepi_controller, redis_controller, **settings['gpio_input'])

    # Instantiate SystemButton
    system_button = SystemButton(h, cinepi_controller, redis_controller, ssd_monitor, **settings['system_button'])
                                
    # Instantiate rotary encoders
    iso_encoder = SimpleRotaryEncoder(h, cinepi_controller, setting="iso", **settings['iso_encoder'])
    shu_encoder = SimpleRotaryEncoder(h, cinepi_controller, setting="shutter_a_nom", **settings['shu_encoder'])
    fps_encoder = SimpleRotaryEncoder(h, cinepi_controller, setting="fps", **settings['fps_encoder'])

    # Instantiate the Mediator and pass the components to it
    mediator = Mediator(cinepi_app, redis_controller, usb_monitor, ssd_monitor, gpio_output)

    # Only after the mediator has been set up and subscribed to the events,
    # we can trigger methods that may cause the events to fire.
    usb_monitor.check_initial_devices()
    
    keyboard = Keyboard(cinepi_controller, usb_monitor)
    
    # Instantiate the CommandExecutor with all necessary components and settings
    command_executor = CommandExecutor(cinepi_controller, system_button)

    # Start the CommandExecutor thread
    command_executor.start()
    
    serial_handler = SerialHandler(command_executor.handle_received_data, 9600, log_queue=log_queue)
    serial_handler.start()
    
    redis_listener = RedisListener(redis_controller)
    
    simple_gui = SimpleGUI(pwm_controller, 
                           redis_controller, 
                           cinepi_controller, 
                           usb_monitor, 
                           ssd_monitor, 
                           serial_handler,
                           dmesg_monitor
                           )

    # Log initialization complete message
    logging.info("--- initialization complete")

    try:
        redis_controller.set_value('is_recording', 0)
        redis_controller.set_value('is_writing', 0)
        # Pause program execution, keeping it running until interrupted
        pause()
    except Exception:
        logging.error("An unexpected error occurred:\n" + traceback.format_exc())
        sys.exit(1)
    finally:
        # Reset trigger mode to default 0
        pwm_controller.stop_pwm()
        pwm_controller.set_trigger_mode(0)
        # Reset redis values to default
        redis_controller.set_value('fps', 24)
        redis_controller.set_value('is_recording', 0)
        redis_controller.set_value('is_writing', 0)
        
        # Set recording status to 0  
        gpio_output.set_recording(0)
        
        dmesg_monitor.join()
        serial_handler.join()
        command_executor.join()
        
        # Cleanup GPIO
        lgpio.gpiochip_close(h)