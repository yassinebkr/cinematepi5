import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from module.app.main.events import register_events


class Signal:
    def __init__(self):
        self.handler = None

    def subscribe(self, handler):
        self.handler = handler


class FakeSocketIO:
    def __init__(self):
        self.handlers = {}
        self.emitted = []
        self.background = None

    def on(self, name):
        def decorator(fn):
            self.handlers[name] = fn
            return fn
        return decorator

    def emit(self, name, data=None):
        self.emitted.append((name, data))

    def start_background_task(self, fn):
        self.background = fn
        return None

    def sleep(self, _seconds):
        pass


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.redis_parameter_changed = Signal()

    def get_value(self, key, default=None):
        key = getattr(key, "value", key)
        return self.values.get(key, default)


class FakeController:
    def __init__(self):
        self.set_iso = mock.Mock()
        self.set_shutter_a = mock.Mock()
        self.set_fps = mock.Mock()
        self.set_wb = mock.Mock()
        self.set_resolution = mock.Mock(return_value=True)
        self.calculate_dynamic_shutter_angles = mock.Mock(
            side_effect=AssertionError(
                "degraded web handler must not derive camera shutter state"
            )
        )
        self.shutter_a_steps_dynamic = [90, 180]
        self.fps_steps_dynamic = [24, 25]
        self.wb_steps = [3200, 5600]
        self.rec = mock.Mock()
        self.unmount = mock.Mock()


class FakeGui:
    def get_background_color(self):
        return "black"

    def populate_values(self):
        return {}


class Sensor:
    camera_model = None

    def __init__(self, present=False):
        self.res_modes = (
            {6: {"width": 5472, "height": 3648}} if present else {}
        )

    def get_available_resolutions(self):
        return []


class WebDegradedCameraControlTests(unittest.TestCase):
    def make_events(self, present=False):
        socket = FakeSocketIO()
        redis = FakeRedis()
        controller = FakeController()
        sensor = Sensor(present=present)
        register_events(socket, redis, controller, FakeGui(), sensor)
        return socket, redis, controller, sensor

    def test_degraded_camera_commands_are_rejected_before_controller_and_emit(self):
        socket, _redis, controller, _sensor = self.make_events(present=False)

        cases = (
            ("change_iso", {"iso": "800"}, controller.set_iso),
            ("change_shutter_a", {"shutter_a": "180"}, controller.set_shutter_a),
            ("change_fps", {"fps": "25"}, controller.set_fps),
            ("change_wb", {"wb": "5600"}, controller.set_wb),
            ("change_resolution", {"mode": "6"}, controller.set_resolution),
        )
        for event, payload, method in cases:
            with self.subTest(event=event):
                socket.emitted.clear()
                socket.handlers[event](payload)
                method.assert_not_called()
                self.assertEqual(socket.emitted, [])

        controller.calculate_dynamic_shutter_angles.assert_not_called()

    def test_active_camera_iso_event_keeps_existing_acknowledgement(self):
        socket, _redis, controller, _sensor = self.make_events(present=True)

        socket.handlers["change_iso"]({"iso": "800"})

        controller.set_iso.assert_called_once_with(800)
        self.assertIn(("parameter_change", {"iso": "800"}), socket.emitted)

    def test_template_disables_camera_controls_with_no_cam_placeholder(self):
        html = (
            ROOT / "src/module/app/templates/template.html"
        ).read_text(encoding="utf-8")
        self.assertIn("setCameraControlsAvailable(!!data.camera_present)", html)
        self.assertIn("select.disabled = !cameraPresent", html)
        self.assertIn("option.textContent = 'NO CAM'", html)
        for control_id in (
            "iso-select",
            "shutter-speed-select",
            "fps-select",
            "wb-select",
            "resolution-select",
        ):
            self.assertIn(control_id, html)


if __name__ == "__main__":
    unittest.main()
