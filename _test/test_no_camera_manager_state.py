import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from module import cinepi_multi
from module.redis_controller import ParameterKey


class RawRedis:
    def __init__(self):
        self.published = []

    def get(self, _key):
        return None

    def keys(self, _pattern):
        return []

    def delete(self, *_keys):
        pass

    def publish(self, channel, key):
        self.published.append((channel, key))


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sets = []
        self.r = RawRedis()

    def get_value(self, key, default=None):
        key = key.value if isinstance(key, ParameterKey) else key
        return self.values.get(key, default)

    def set_value(self, key, value):
        if value is None:
            return
        key = key.value if isinstance(key, ParameterKey) else key
        self.values[key] = str(value)
        self.sets.append((key, value))


class StaleSensorState:
    def __init__(self):
        modes = {
            6: {
                "width": 5472,
                "height": 3648,
                "bit_depth": 12,
                "fps_max": 24,
            }
        }
        self.camera_model = "imx283"
        self.res_modes = dict(modes)
        self.sensor_resolutions = {"imx283": dict(modes)}


class NoCameraManagerStateTests(unittest.TestCase):
    def _manager(self):
        values = {
            ParameterKey.ZOOM.value: "1.0",
            ParameterKey.SENSOR.value: "imx283",
            ParameterKey.SENSOR_MODE.value: "6",
            ParameterKey.DYNAMIC_RESOLUTION_DESIRED_MODE.value: "6",
            ParameterKey.DYNAMIC_RESOLUTION_ACTIVE.value: "1",
            ParameterKey.FPS_MAX.value: "24",
            ParameterKey.FPS.value: "24",
        }
        redis = FakeRedis(values)
        sensor = StaleSensorState()
        manager = cinepi_multi.CinePiManager(redis, sensor)
        return manager, redis, sensor

    def test_camera_only_restart_is_refused_from_degraded_state(self):
        manager, _redis, sensor = self._manager()
        sensor.camera_model = None
        sensor.res_modes = {}
        manager.stop_all = mock.Mock(side_effect=AssertionError(
            "degraded restart must not stop/start camera machinery"
        ))
        manager.start_all = mock.Mock(side_effect=AssertionError(
            "degraded restart must not rediscover camera hardware"
        ))

        result = manager.restart()

        self.assertIsNone(result)
        manager.stop_all.assert_not_called()
        manager.start_all.assert_not_called()

    def test_camera_only_restart_remains_available_with_active_sensor(self):
        manager, _redis, sensor = self._manager()
        self.assertTrue(sensor.res_modes)
        manager.stop_all = mock.Mock()
        manager.start_all = mock.Mock()

        manager.restart(preview_enabled=False)

        manager.stop_all.assert_called_once_with()
        manager.start_all.assert_called_once_with(preview_enabled=False)

    def test_imx283_discovery_grace_period_is_ten_seconds(self):
        self.assertEqual(cinepi_multi.CAMERA_DISCOVERY_TIMEOUT_S, 10.0)
        self.assertEqual(cinepi_multi.CAMERA_DISCOVERY_INTERVAL_S, 1.0)
        sig = inspect.signature(cinepi_multi.discover_cameras)
        self.assertEqual(sig.parameters["timeout"].default, 10.0)
        self.assertEqual(sig.parameters["interval"].default, 1.0)

    def test_failed_rediscovery_clears_only_active_sensor_state(self):
        manager, redis, sensor = self._manager()
        cached_database = sensor.sensor_resolutions.copy()

        with mock.patch.object(cinepi_multi, "discover_cameras", return_value=[]), \
             mock.patch.object(cinepi_multi, "_is_pi4_family", return_value=False):
            manager.start_all()

        self.assertIsNone(sensor.camera_model)
        self.assertEqual(sensor.res_modes, {})
        self.assertEqual(sensor.sensor_resolutions, cached_database)
        self.assertEqual(redis.values[ParameterKey.CAMERAS.value], "[]")

    def test_failed_rediscovery_preserves_persisted_operator_state(self):
        manager, redis, _sensor = self._manager()
        preserved = {
            key: redis.values[key]
            for key in (
                ParameterKey.SENSOR.value,
                ParameterKey.SENSOR_MODE.value,
                ParameterKey.DYNAMIC_RESOLUTION_DESIRED_MODE.value,
                ParameterKey.DYNAMIC_RESOLUTION_ACTIVE.value,
                ParameterKey.FPS_MAX.value,
                ParameterKey.FPS.value,
            )
        }

        with mock.patch.object(cinepi_multi, "discover_cameras", return_value=[]), \
             mock.patch.object(cinepi_multi, "_is_pi4_family", return_value=False):
            manager.start_all()

        for key, value in preserved.items():
            self.assertEqual(redis.values[key], value, key)

        touched = {key for key, _value in redis.sets}
        for key in preserved:
            self.assertNotIn(key, touched)


if __name__ == "__main__":
    unittest.main()
