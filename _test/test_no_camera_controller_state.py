import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("redis", types.SimpleNamespace(StrictRedis=object))
sys.modules.setdefault("smbus", types.SimpleNamespace(SMBus=object))

from module.cinepi_controller import CinePiController
from module.redis_controller import ParameterKey


class Event:
    def subscribe(self, _handler):
        pass


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sets = []
        self.redis_parameter_changed = Event()

    def get_value(self, key, default=None):
        key = key.value if isinstance(key, ParameterKey) else key
        return self.values.get(key, default)

    def set_value(self, key, value, **_kwargs):
        if value is None:
            return
        key = key.value if isinstance(key, ParameterKey) else key
        self.values[key] = value
        self.sets.append((key, value))

    def mset(self, mapping):
        for key, value in mapping.items():
            self.set_value(key, value)

    def writes_to(self, key):
        key = key.value if isinstance(key, ParameterKey) else key
        return [v for k, v in self.sets if k == key]


class NoCameraSensor:
    camera_model = None
    res_modes = {}

    def get_gui_layout(self, *_args):
        return None

    def get_fps_max(self, *_args):
        return None

    def get_file_size(self, *_args):
        raise AssertionError("file size must not be queried without a camera")


class FakeSSD:
    def __init__(self):
        self.mount_event = Event()
        self.is_mounted = True
        self.space_left = 100
        self.write_speed_mb_s = 0

    def get_space_left(self):
        return self.space_left


def bare_controller(values=None):
    c = CinePiController.__new__(CinePiController)
    c.redis_controller = FakeRedis(values)
    c.sensor_detect = NoCameraSensor()
    c.fps_steps = [1, 24, 25, 50]
    c.dynamic_resolution_enabled = False
    c.dynamic_resolution_active = False
    c.dynamic_resolution_desired_mode = 6
    c.fps_max = 50
    return c


class DegradedStateTests(unittest.TestCase):
    def test_stored_sensor_mode_is_preserved_without_mode_table(self):
        c = bare_controller({ParameterKey.SENSOR_MODE.value: "6"})
        self.assertEqual(c._get_startup_sensor_mode(), 6)
        self.assertEqual(c.redis_controller.writes_to(ParameterKey.SENSOR_MODE), [])

    def test_missing_sensor_mode_defaults_in_memory_without_write(self):
        c = bare_controller()
        self.assertEqual(c._get_startup_sensor_mode(), 0)
        self.assertEqual(c.redis_controller.writes_to(ParameterKey.SENSOR_MODE), [])

    def test_dynamic_desired_mode_is_preserved_without_mode_table(self):
        c = bare_controller({ParameterKey.DYNAMIC_RESOLUTION_DESIRED_MODE.value: "4"})
        c.sensor_mode = 6
        self.assertEqual(c._get_startup_dynamic_resolution_desired_mode(), 4)

    def test_publish_does_not_persist_desired_mode_without_camera(self):
        c = bare_controller()
        c._publish_dynamic_resolution_state()
        self.assertEqual(
            c.redis_controller.writes_to(ParameterKey.DYNAMIC_RESOLUTION_DESIRED_MODE),
            [],
        )

    def test_stored_fps_max_wins(self):
        c = bare_controller({ParameterKey.FPS_MAX.value: "33"})
        self.assertEqual(c._stored_fps_max(), 33)

    def test_missing_fps_max_uses_configured_step_ceiling(self):
        c = bare_controller()
        self.assertEqual(c._stored_fps_max(), 50)

    def test_refresh_fps_max_does_not_write_without_camera(self):
        c = bare_controller({ParameterKey.FPS_MAX.value: "40"})
        self.assertEqual(c._refresh_fps_max(), 40)
        self.assertEqual(c.redis_controller.writes_to(ParameterKey.FPS_MAX), [])

    def test_initialize_fps_steps_does_not_write_without_camera(self):
        c = bare_controller({ParameterKey.FPS_MAX.value: "25"})
        c._fps_steps_capped_at_max = CinePiController._fps_steps_capped_at_max.__get__(c)
        c.initialize_fps_steps([1, 24, 25, 50])
        self.assertEqual(c.fps_steps_dynamic, [1, 24, 25])
        self.assertEqual(c.redis_controller.writes_to(ParameterKey.FPS_MAX), [])

    def test_start_recording_is_noop_without_camera(self):
        c = bare_controller({
            ParameterKey.IS_RECORDING.value: "0",
            ParameterKey.IS_WRITING_BUF.value: "0",
            ParameterKey.IS_BUFFERING.value: "0",
        })
        c.ssd_monitor = FakeSSD()
        c._preroll_active = types.SimpleNamespace(is_set=lambda: False)
        c._cancel_timed_recording_stop = lambda: None
        c._clear_frame_limited_recording_stop = lambda: None
        c.start_recording()
        self.assertEqual(c.redis_controller.get_value(ParameterKey.IS_RECORDING.value), "0")

    def test_resolution_request_returns_false_without_camera(self):
        c = bare_controller()
        c._normalize_sensor_mode_value = CinePiController._normalize_sensor_mode_value.__get__(c)
        self.assertFalse(c._apply_resolution_mode(3))
        self.assertEqual(
            c.redis_controller.get_value(ParameterKey.RESOLUTION_SWITCHING.value),
            0,
        )

    def test_white_balance_builds_fallback_curve_without_sensor(self):
        c = bare_controller()
        c.current_sensor = None
        c.wb_steps = [3200, 4400, 5600]
        c.interpolate = CinePiController.interpolate.__get__(c)
        c.initialize_wb_cg_rb_array()
        self.assertEqual(set(c.wb_cg_rb_array), {3200, 4400, 5600})
        for gains in c.wb_cg_rb_array.values():
            self.assertGreater(gains[0], 0)
            self.assertGreater(gains[1], 0)


if __name__ == "__main__":
    unittest.main()
