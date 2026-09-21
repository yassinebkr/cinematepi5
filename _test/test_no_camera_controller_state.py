import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    import redis as _redis_dependency  # prefer the real app dependency when available
except ImportError:
    sys.modules.setdefault(
        "redis",
        types.SimpleNamespace(StrictRedis=object, Redis=object),
    )
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
    c.settings = {"settings": {"conform_frame_rate": 25}}
    c.dynamic_resolution_enabled = False
    c.dynamic_resolution_active = False
    c.dynamic_resolution_desired_mode = 6
    c.fps_max = 50
    return c


class FullNoCameraConstructorTests(unittest.TestCase):
    SETTINGS = {
        "camera": {},
        "dynamic_resolution": {"enabled": False},
        "preview": {"default_zoom": 1.0},
        "free_mode": {
            "iso_free": False,
            "shutter_a_free": False,
            "fps_free": False,
            "wb_free": False,
        },
        "arrays": {
            "iso_steps": [100, 200, 400],
            "shutter_a_steps": [90, 180, 360],
            "fps_steps": [1, 24, 25, 30],
            "wb_steps": [3200, 4400, 5600],
        },
        "settings": {"light_hz": [], "conform_frame_rate": 25},
    }

    class FakeCinePi:
        def restart(self, *_args, **_kwargs):
            pass

    def make_controller(self, values):
        redis = FakeRedis(values)
        with mock.patch.object(
            CinePiController, "load_settings", return_value=self.SETTINGS
        ), mock.patch("module.cinepi_controller.threading.Timer"):
            controller = CinePiController(
                self.FakeCinePi(),
                redis,
                FakeSSD(),
                NoCameraSensor(),
                iso_steps=self.SETTINGS["arrays"]["iso_steps"],
                shutter_a_steps=self.SETTINGS["arrays"]["shutter_a_steps"],
                fps_steps=self.SETTINGS["arrays"]["fps_steps"],
                wb_steps=self.SETTINGS["arrays"]["wb_steps"],
                light_hz=[],
                anamorphic_steps=[1.0],
                default_anamorphic_factor=1.0,
            )
        return controller, redis

    def test_full_constructor_preserves_operator_fps_state_without_camera(self):
        values = {
            ParameterKey.FPS_LAST.value: "25",
            ParameterKey.FPS_USER.value: "24",
            ParameterKey.FPS.value: "24",
            ParameterKey.SHUTTER_A.value: "180",
            ParameterKey.SENSOR.value: "imx283",
            ParameterKey.SENSOR_MODE.value: "6",
            ParameterKey.DYNAMIC_RESOLUTION_DESIRED_MODE.value: "6",
            ParameterKey.DYNAMIC_RESOLUTION_ACTIVE.value: "0",
            ParameterKey.FPS_MAX.value: "30",
            ParameterKey.ZOOM.value: "1.0",
            ParameterKey.STORAGE_FILESYSTEM.value: "none",
        }
        preserved = {
            key: values[key]
            for key in (
                ParameterKey.FPS_USER.value,
                ParameterKey.FPS.value,
                ParameterKey.FPS_MAX.value,
                ParameterKey.SENSOR_MODE.value,
                ParameterKey.DYNAMIC_RESOLUTION_DESIRED_MODE.value,
            )
        }

        controller, redis = self.make_controller(values)

        self.assertEqual(controller.current_fps, 24.0)
        self.assertEqual(controller.fps, 24)
        for key, value in preserved.items():
            self.assertEqual(redis.values[key], value, key)
            self.assertEqual(redis.writes_to(key), [], key)

    def test_degraded_fps_fallback_precedence_is_non_mutating(self):
        cases = [
            (
                {
                    ParameterKey.FPS_USER.value: "23.976",
                    ParameterKey.FPS.value: "25",
                    ParameterKey.FPS_LAST.value: "30",
                },
                23.976,
            ),
            (
                {
                    ParameterKey.FPS_USER.value: "bad",
                    ParameterKey.FPS.value: "25",
                    ParameterKey.FPS_LAST.value: "30",
                },
                25.0,
            ),
            (
                {
                    ParameterKey.FPS_USER.value: None,
                    ParameterKey.FPS.value: "bad",
                    ParameterKey.FPS_LAST.value: "30",
                },
                30.0,
            ),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                c = bare_controller(values)
                self.assertEqual(c._get_degraded_startup_fps(), expected)
                self.assertEqual(c.redis_controller.sets, [])

    def test_degraded_fps_uses_conform_rate_when_redis_empty(self):
        c = bare_controller()
        c.fps_steps = [1, 23.976, 25, 50]
        self.assertEqual(c._get_degraded_startup_fps(), 25.0)
        self.assertEqual(c.redis_controller.sets, [])

    def test_degraded_shutter_missing_uses_180_in_memory_only(self):
        c = bare_controller()
        self.assertEqual(c._get_degraded_startup_shutter_angle(), 180.0)
        self.assertEqual(c.redis_controller.sets, [])

    def test_degraded_shutter_preserves_valid_stored_value_without_write(self):
        c = bare_controller({ParameterKey.SHUTTER_A.value: "172.8"})
        self.assertEqual(c._get_degraded_startup_shutter_angle(), 172.8)
        self.assertEqual(c.redis_controller.sets, [])

    def test_fresh_empty_redis_constructor_stays_degraded_without_seeding_camera_state(self):
        controller, redis = self.make_controller({})

        self.assertEqual(controller.current_fps, 25.0)
        self.assertEqual(controller.fps, 25)
        self.assertEqual(controller.fps_saved, 25.0)
        self.assertEqual(controller.shutter_angle_nom, 180.0)
        self.assertEqual(controller.shutter_angle_actual, 180.0)
        self.assertAlmostEqual(controller.exposure_time_s, 0.02)
        self.assertEqual(controller.file_size, 0.0)

        forbidden = (
            ParameterKey.FPS_USER.value,
            ParameterKey.FPS.value,
            ParameterKey.FPS_LAST.value,
            ParameterKey.SHUTTER_A.value,
            ParameterKey.SENSOR_MODE.value,
            ParameterKey.WIDTH.value,
            ParameterKey.HEIGHT.value,
            ParameterKey.BIT_DEPTH.value,
        )
        for key in forbidden:
            self.assertNotIn(key, redis.values, key)
            self.assertEqual(redis.writes_to(key), [], key)


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

    def test_direct_camera_controls_are_read_only_without_sensor(self):
        c = bare_controller()
        c.iso_lock = False
        c.parameters_lock_obj = __import__("threading").Lock()
        c.iso_steps = [100, 200, 400]
        c.shutter_a_steps = [90, 180, 360]
        c.shutter_a_steps_dynamic = [90, 180, 360]
        c.shutter_a_sync_mode = 0
        c.shutter_a_free = False
        c.shutter_a_nom_lock = False
        c.fps_lock = False
        c.lock_override = False
        c.fps_free = False
        c.fps_double = False
        c.fps = 25
        c.current_fps = 25.0
        c.shutter_angle_nom = 180.0
        c.shutter_angle_actual = 180.0
        c.wb_steps = [3200, 4400, 5600]
        c.wb_cg_rb_array = {5600: (2.0, 1.5)}

        before = dict(c.redis_controller.values)
        before_runtime = {
            "fps": c.fps,
            "current_fps": c.current_fps,
            "fps_double": c.fps_double,
            "shutter_angle_nom": c.shutter_angle_nom,
            "shutter_angle_actual": c.shutter_angle_actual,
        }

        c.set_iso(400)
        c.set_shutter_a(90)
        c.set_shutter_a_nom(90)
        c.set_fps(50)
        c.set_wb(5600)
        c.set_fps_double(True)
        c._ramp_fps(True)

        self.assertEqual(c.redis_controller.values, before)
        self.assertEqual(c.redis_controller.sets, [])
        for key, value in before_runtime.items():
            self.assertEqual(getattr(c, key), value, key)

    def test_inc_dec_camera_controls_do_not_read_missing_redis_state(self):
        c = bare_controller()
        c.get_setting = mock.Mock(side_effect=AssertionError(
            "degraded camera inc/dec must stop before reading Redis"
        ))

        for setting, steps in (
            ("iso", [100, 200]),
            ("shutter_a", [90, 180]),
            ("shutter_a_nom", [90, 180]),
            ("fps", [24, 25]),
        ):
            with self.subTest(setting=setting, direction="inc"):
                c.increment_setting(setting, steps)
            with self.subTest(setting=setting, direction="dec"):
                c.decrement_setting(setting, steps)

        c.get_setting.assert_not_called()
        self.assertEqual(c.redis_controller.sets, [])

    def test_camera_control_gate_allows_active_sensor(self):
        c = bare_controller()
        c.sensor_detect.res_modes = {6: {"width": 5472, "height": 3648}}
        self.assertTrue(c._camera_control_available("iso"))

    def test_normal_iso_setter_still_writes_with_active_sensor(self):
        c = bare_controller()
        c.sensor_detect.res_modes = {6: {"width": 5472, "height": 3648}}
        c.iso_lock = False
        c.parameters_lock_obj = __import__("threading").Lock()
        c.iso_steps = [100, 200, 400]

        c.set_iso(350)

        self.assertEqual(c.redis_controller.writes_to(ParameterKey.ISO), [350])

    def test_camera_mode_toggles_are_read_only_without_sensor(self):
        c = bare_controller()
        c.iso_free = False
        c.shutter_a_free = False
        c.fps_free = False
        c.wb_free = False
        c.shutter_a_sync_mode = 0
        c.shutter_angle_nom = 180.0
        c.current_fps = 25.0
        c.shutter_angle_steps = [90, 180, 360]
        c.settings.setdefault("free_mode", {
            "iso_free": False,
            "shutter_a_free": False,
            "fps_free": False,
            "wb_free": False,
        })
        c.update_steps = mock.Mock(side_effect=AssertionError(
            "degraded mode toggle must not rebuild camera step tables"
        ))
        c.initialize_wb_cg_rb_array = mock.Mock(side_effect=AssertionError(
            "degraded WB free toggle must not rebuild sensor-dependent WB state"
        ))
        c.initialize_shutter_angle_steps = mock.Mock(side_effect=AssertionError(
            "degraded shutter sync toggle must not rebuild shutter state"
        ))

        before_settings = dict(c.settings["free_mode"])
        before_runtime = (
            c.iso_free,
            c.shutter_a_free,
            c.fps_free,
            c.wb_free,
            c.shutter_a_sync_mode,
        )

        c.set_iso_free(True)
        c.set_shutter_a_free(True)
        c.set_fps_free(True)
        c.set_wb_free(True)
        c.set_shutter_a_sync_mode(True)
        c.set_free_mode(True, True, True, True)

        self.assertEqual(
            (
                c.iso_free,
                c.shutter_a_free,
                c.fps_free,
                c.wb_free,
                c.shutter_a_sync_mode,
            ),
            before_runtime,
        )
        self.assertEqual(c.settings["free_mode"], before_settings)
        self.assertEqual(c.redis_controller.sets, [])
        c.update_steps.assert_not_called()
        c.initialize_wb_cg_rb_array.assert_not_called()
        c.initialize_shutter_angle_steps.assert_not_called()

    def test_shutter_sync_still_routes_imu_calibration_input_while_degraded(self):
        c = bare_controller()
        c.shutter_a_sync_mode = 0
        c._imu_cal_input = mock.Mock(return_value=True)

        c.set_shutter_a_sync_mode()

        c._imu_cal_input.assert_called_once_with("confirm")
        self.assertEqual(c.shutter_a_sync_mode, 0)
        self.assertEqual(c.redis_controller.sets, [])

    def test_camera_mode_toggle_gate_allows_active_sensor(self):
        c = bare_controller()
        c.sensor_detect.res_modes = {6: {"width": 5472, "height": 3648}}
        c.iso_free = False
        c.update_steps = mock.Mock()

        c.set_iso_free(True)

        self.assertTrue(c.iso_free)
        c.update_steps.assert_called_once_with()

    def test_internal_camera_updates_cannot_bypass_degraded_lock(self):
        c = bare_controller()
        c.current_fps = 25.0
        c.shutter_angle_nom = 180.0
        c.shutter_angle_actual = 180.0
        c.shutter_a_sync_mode = 1
        c.exposure_time_nominal = 1 / 50
        c.is_shutter_angle_transient = True

        c.update_fps(30.0)
        c.update_shutter_angle_nom(90.0)
        c.end_shutter_angle_transient()

        self.assertEqual(c.current_fps, 25.0)
        self.assertEqual(c.shutter_angle_nom, 180.0)
        self.assertFalse(c.is_shutter_angle_transient)
        self.assertEqual(c.redis_controller.sets, [])

    def test_anamorphic_factor_can_be_preconfigured_without_camera_restart(self):
        c = bare_controller({ParameterKey.ANAMORPHIC_FACTOR.value: 1.0})
        c.anamorphic_steps = [1.0, 1.33, 1.5]
        c.cinepi = mock.Mock()

        c.set_anamorphic_factor(1.33)

        self.assertEqual(
            c.redis_controller.writes_to(ParameterKey.ANAMORPHIC_FACTOR),
            [1.33],
        )
        c.cinepi.restart.assert_not_called()

    def test_storage_profile_change_does_not_restart_camera_without_sensor(self):
        c = bare_controller({ParameterKey.STORAGE_FILESYSTEM.value: "ext4"})
        c._storage_profile_restart_lock = __import__("threading").Lock()
        c._storage_profile_restart_pending = True
        c._active_storage_recorder_profile = "previous"
        c._current_storage_recorder_profile = lambda: "ext4-profile"
        c.restart_camera = mock.Mock(side_effect=AssertionError(
            "storage event must not trigger camera discovery without a sensor"
        ))

        with mock.patch("module.cinepi_controller.threading.Thread") as thread:
            c._maybe_schedule_storage_profile_restart("storage mount")

        thread.assert_not_called()
        c.restart_camera.assert_not_called()
        self.assertEqual(c._active_storage_recorder_profile, "ext4-profile")
        self.assertFalse(c._storage_profile_restart_pending)

    def test_storage_mount_refreshes_state_without_camera_restart(self):
        c = bare_controller({ParameterKey.STORAGE_FILESYSTEM.value: "ext4"})
        c._storage_profile_restart_lock = __import__("threading").Lock()
        c._storage_profile_restart_pending = False
        c._active_storage_recorder_profile = "previous"
        c._current_storage_recorder_profile = lambda: "ext4-profile"
        c._refresh_fps_max = mock.Mock(return_value=40)
        c.update_steps = mock.Mock()
        c.restart_camera = mock.Mock(side_effect=AssertionError(
            "storage mount must not trigger camera discovery without a sensor"
        ))

        with mock.patch("module.cinepi_controller.threading.Thread") as thread:
            c._handle_storage_mount_event()

        c._refresh_fps_max.assert_called_once_with()
        c.update_steps.assert_called_once_with()
        thread.assert_not_called()
        c.restart_camera.assert_not_called()
        self.assertEqual(c._active_storage_recorder_profile, "ext4-profile")

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
