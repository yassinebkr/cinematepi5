import subprocess
import logging
from queue import Queue
from threading import Thread

class Event:
    def __init__(self):
        self._listeners = []

    def subscribe(self, listener):
        self._listeners.append(listener)

    def emit(self, data=None):
        for listener in self._listeners:
            listener(data)

def enqueue_output(out, queue, event):
    for line in iter(out.readline, b''):
        queue.put(line)
        # emit the line to all subscribers
        event.emit(line.decode('utf-8'))
    out.close()

class CinePi:
    _instance = None  # Singleton instance

    def __new__(cls, redis_controller, sensor_detect):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, redis_controller, sensor_detect):
        if not hasattr(self, 'initialized'):  # only initialize once
            self.redis_controller = redis_controller
            self.sensor_detect = sensor_detect
            self.message = Event()
            self.suppress_output = False
            self.process = subprocess.Popen(['cinepi-raw'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.out_queue = Queue()
            self.err_queue = Queue()

            # These are the corrected positions for the thread initializations
            self.out_thread = Thread(target=enqueue_output, args=(self.process.stdout, self.out_queue, self.message))
            self.err_thread = Thread(target=enqueue_output, args=(self.process.stderr, self.err_queue, self.message))
            
            self.out_thread.daemon = True
            self.err_thread.daemon = True
            self.out_thread.start()
            self.err_thread.start()                        
            self.initialized = True  # indicate that the instance has been initialized
            logging.info('CinePi instantiated')
