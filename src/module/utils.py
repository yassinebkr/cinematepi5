import psutil
from gpiozero import CPUTemperature

class Utils:
    @staticmethod
    def cpu_load() -> str:
        t = psutil.cpu_times_percent()
        return str(max(0, int(round(100 - t.idle - t.nice)))) + '%'

    @staticmethod
    def cpu_temp() -> str:
        return ('{}\u00B0C'.format(int(CPUTemperature().temperature)))
    
    @staticmethod
    def memory_usage() -> str:
        return str(int(psutil.virtual_memory().percent)) + '%'
