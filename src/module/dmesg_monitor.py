import logging
import subprocess
import pyinotify
import threading
import time
import os

class DmesgMonitor(threading.Thread):
    def __init__(self, dmesg_file):
        super().__init__()
        self.dmesg_file = dmesg_file
        self.keywords = {
            "Undervoltage": "Undervoltage detected!",
            "Voltage_normalised": "Voltage normalised",
            "sda": "sda"
        }
        self.last_occurrence = {key: None for key in self.keywords}
        self.undervoltage_flag = False
        self.undervoltage_timer = None
        self.disk_attached = False
        self.disk_detached_event = threading.Event()
        
    def run(self):
        self._start_monitoring()

    def read_dmesg_log(self):
        try:
            with open(self.dmesg_file, "r") as f:
                return f.readlines()
        except Exception as e:
            logging.error(f"Error reading dmesg log: {e}")
            return []

    def parse_dmesg_messages(self, lines):
        parsed_messages = {}
        for line in lines:
            for key, value in self.keywords.items():
                if value in line:
                    parsed_messages[key] = line
        return parsed_messages

    def track_last_occurrence(self, messages):
        new_messages = {}
        for message_type, message in messages.items():
            if self.last_occurrence[message_type] != message:
                new_messages[message_type] = message
                self.last_occurrence[message_type] = message
        return new_messages

    def handle_file_change(self):
        pass

    def reset_undervoltage_flag(self):
        self.undervoltage_flag = False

    def _start_monitoring(self):
        if not os.path.exists(self.dmesg_file):
            logging.error(f"Dmesg file {self.dmesg_file} does not exist.")
            return

        wm = pyinotify.WatchManager()
        mask = pyinotify.IN_MODIFY | pyinotify.IN_DELETE_SELF

        class EventHandler(pyinotify.ProcessEvent):
            def process_IN_MODIFY(self, event):
                self.handle_file_change()

            def process_IN_DELETE_SELF(self, event):
                logging.info("File deleted")

        handler = EventHandler()
        notifier = pyinotify.Notifier(wm, handler)
        
        try:
            wm.add_watch(self.dmesg_file, mask)
        except pyinotify.WatchManagerError as e:
            logging.error(f"Error adding watch for {self.dmesg_file}: {e}")
            return

        try:
            while True:
                notifier.process_events()
                if notifier.check_events():
                    notifier.read_events()
                
                dmesg_lines = self.read_dmesg_log()
                new_messages = self.parse_dmesg_messages(dmesg_lines)
                new_messages = self.track_last_occurrence(new_messages)
                if new_messages:
                    for message_type, message in new_messages.items():
                        parts = message.split(":", 4)
                        if len(parts) > 4:
                            message = ":".join(parts[4:])
                            if "Undervoltage" in message:
                                if not self.undervoltage_flag:
                                    logging.warning("Undervoltage detected!")
                                    self.undervoltage_flag = True
                            elif "Voltage_normalised" in message:
                                logging.info("Voltage normalised")
                                self.undervoltage_flag = False
                            elif "sda" in message:
                                if "[sda] Attached SCSI disk" in message:
                                    self.disk_attached = True
                                    logging.info("Disk attached.")
                                elif "[sda] Synchronize Cache" and "failed" in message:
                                    self.disk_attached = False
                                    logging.info("Disk detached.")
                                    self.disk_detached_event.set()
        except KeyboardInterrupt:
            notifier.stop()


# import logging
# import subprocess
# import pyinotify
# import threading
# import time

# class DmesgMonitor(threading.Thread):
#     def __init__(self, dmesg_file):
#         super().__init__()
#         self.dmesg_file = dmesg_file
#         self.keywords = {
#             "Undervoltage": "Undervoltage detected!",
#             "Voltage_normalised": "Voltage normalised",
#             "sda": "sda"
#         }
#         self.last_occurrence = {key: None for key in self.keywords}
#         self.undervoltage_flag = False
#         self.undervoltage_timer = None
#         self.disk_attached = False
#         self.disk_detached_event = threading.Event()
        
#     def run(self):
#         self._start_monitoring()

#     def read_dmesg_log(self):
#         try:
#             with open(self.dmesg_file, "r") as f:
#                 return f.readlines()
#         except Exception as e:
#             logging.error(f"Error reading dmesg log: {e}")
#             return []

#     def parse_dmesg_messages(self, lines):
#         parsed_messages = {}
#         for line in lines:
#             for key, value in self.keywords.items():
#                 if value in line:
#                     parsed_messages[key] = line
#         return parsed_messages

#     def track_last_occurrence(self, messages):
#         new_messages = {}
#         for message_type, message in messages.items():
#             if self.last_occurrence[message_type] != message:
#                 new_messages[message_type] = message
#                 self.last_occurrence[message_type] = message
#         return new_messages

#     def handle_file_change(self):
#         pass

#     def reset_undervoltage_flag(self):
#         self.undervoltage_flag = False

#     def _start_monitoring(self):
#         wm = pyinotify.WatchManager()
#         mask = pyinotify.IN_MODIFY | pyinotify.IN_DELETE_SELF

#         class EventHandler(pyinotify.ProcessEvent):
#             def process_IN_MODIFY(self, event):
#                 self.handle_file_change()

#             def process_IN_DELETE_SELF(self, event):
#                 logging.info("File deleted")

#         handler = EventHandler()
#         notifier = pyinotify.Notifier(wm, handler)
#         wm.add_watch(self.dmesg_file, mask)

#         try:
#             while True:
#                 notifier.process_events()
#                 if notifier.check_events():
#                     notifier.read_events()
                
#                 dmesg_lines = self.read_dmesg_log()
#                 new_messages = self.parse_dmesg_messages(dmesg_lines)
#                 new_messages = self.track_last_occurrence(new_messages)
#                 if new_messages:
#                     for message_type, message in new_messages.items():
#                         parts = message.split(":", 4)
#                         if len(parts) > 4:
#                             message = ":".join(parts[4:])
#                             if "Undervoltage" in message:
#                                 if not self.undervoltage_flag:
#                                     logging.warning("Undervoltage detected!")
#                                     self.undervoltage_flag = True
#                             elif "Voltage_normalised" in message:
#                                 logging.info("Voltage normalised")
#                                 self.undervoltage_flag = False
#                             elif "sda" in message:
#                                 if "[sda] Attached SCSI disk" in message:
#                                     self.disk_attached = True
#                                     logging.info("Disk attached.")
#                                 elif "[sda] Synchronize Cache" and "failed" in message:
#                                     self.disk_attached = False
#                                     logging.info("Disk detached.")
#                                     self.disk_detached_event.set()
#         except KeyboardInterrupt:
#             notifier.stop()
