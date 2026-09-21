import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Import SimpleGUI with lightweight dependency stubs, but restore sys.modules
# immediately afterwards so this test cannot poison later tests in discovery
# order.
_MISSING = object()
_STUBS = {
    "flask_socketio": types.SimpleNamespace(SocketIO=object),
    "gpiozero": types.SimpleNamespace(CPUTemperature=object),
    "sugarpie": types.SimpleNamespace(pisugar=types.SimpleNamespace()),
}
try:
    import redis as _redis_dependency
except ImportError:
    _STUBS["redis"] = types.SimpleNamespace(StrictRedis=object, Redis=object)
_saved_modules = {name: sys.modules.get(name, _MISSING) for name in _STUBS}
try:
    sys.modules.update(_STUBS)
    from module.simple_gui import (
        _apply_camera_presence_display,
        _calculate_preview_guide_rect,
        _disk_space_recording_label,
        _display_fps_value,
    )
finally:
    for name, previous in _saved_modules.items():
        if previous is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    sys.modules.pop("module.simple_gui", None)


class DegradedCameraDisplayTests(unittest.TestCase):
    def test_no_camera_hides_remembered_camera_readouts(self):
        values = {
            "resolution": "2K",
            "iso": "800",
            "shutter_speed": "180.0 deg",
            "fps": 25,
            "color_temp": "5600 K",
            "color_temp_libcamera": "/ 5400K",
            "res": "1920x1080 :10b",
            "resolution_switching": True,
            "sensor": "",
            "aspect": "1.78",
            "exposure_time": "1/50",
        }

        result = _apply_camera_presence_display(values, False)

        self.assertEqual(result["resolution"], "--")
        self.assertEqual(result["iso"], "--")
        self.assertEqual(result["shutter_speed"], "--")
        self.assertEqual(result["color_temp"], "--")
        self.assertEqual(result["color_temp_libcamera"], "")
        self.assertEqual(result["res"], "NO CAM")
        self.assertFalse(result["resolution_switching"])
        self.assertEqual(result["sensor"], "")
        self.assertEqual(result["aspect"], "--")
        self.assertEqual(result["exposure_time"], "--")
        # Runtime FPS remains available for controller/UI timing context.
        self.assertEqual(result["fps"], 25)

    def test_active_camera_display_is_unchanged(self):
        values = {
            "resolution": "4K",
            "iso": "800",
            "shutter_speed": "180.0 deg",
            "fps": 25,
            "color_temp": "5600 K",
            "res": "5472x3648 :12b",
            "aspect": "1.5",
        }
        original = dict(values)

        result = _apply_camera_presence_display(values, True)

        self.assertEqual(result, original)


class DegradedFpsDisplayTests(unittest.TestCase):
    def test_missing_redis_fps_uses_runtime_controller_fps(self):
        self.assertEqual(_display_fps_value(None, 25.0), 25)

    def test_persisted_fps_user_keeps_precedence(self):
        self.assertEqual(_display_fps_value("23.976", 25.0), 24)

    def test_invalid_values_fall_back_without_exception(self):
        self.assertEqual(_display_fps_value("bad", None), 0)


class DegradedDiskSpaceLabelTests(unittest.TestCase):
    def test_mounted_disk_without_camera_reports_no_cam(self):
        self.assertEqual(
            _disk_space_recording_label(512.0, True, 0.0, 24.0),
            "NO CAM",
        )

    def test_mounted_disk_with_zero_runtime_fps_reports_no_cam(self):
        self.assertEqual(
            _disk_space_recording_label(512.0, True, 8.0, 0.0),
            "NO CAM",
        )

    def test_unmounted_storage_reports_no_disk(self):
        self.assertEqual(
            _disk_space_recording_label(512.0, False, 8.0, 24.0),
            "NO DISK",
        )

    def test_valid_camera_preserves_recording_minutes_estimate(self):
        self.assertEqual(
            _disk_space_recording_label(120.0, True, 10.0, 25.0),
            "8 MIN",
        )


class PreviewGuideGeometryTests(unittest.TestCase):
    def assert_rect_valid(self, rect, width=1920, height=1080):
        x0,y0,x1,y1=rect
        self.assertGreaterEqual(x0,0)
        self.assertGreaterEqual(y0,0)
        self.assertLess(x1,width)
        self.assertLess(y1,height)
        self.assertLess(x0,x1)
        self.assertLess(y0,y1)

    def test_preview_guide_matches_sensor_aspect_after_resolution_switch(self):
        rect=_calculate_preview_guide_rect(
            frame_width=1920,
            frame_height=1080,
            sensor_width=3856,
            sensor_height=2180,
        )
        self.assertEqual(rect,[93,48,1826,1030])
        self.assert_rect_valid(rect)

    def test_preview_guide_adapts_to_anamorphic_preview_height(self):
        rect=_calculate_preview_guide_rect(
            frame_width=1920,
            frame_height=1080,
            sensor_width=1928,
            sensor_height=1090,
            anamorphic_factor=1.33,
        )
        self.assertEqual(rect,[92,169,1827,908])
        self.assert_rect_valid(rect)

    def test_extreme_portrait_sensor_stays_inside_frame(self):
        rect=_calculate_preview_guide_rect(
            frame_width=1920,
            frame_height=1080,
            sensor_width=1080,
            sensor_height=1920,
        )
        self.assert_rect_valid(rect)

    def test_wide_anamorphic_factor_stays_inside_frame(self):
        rect=_calculate_preview_guide_rect(
            frame_width=1920,
            frame_height=1080,
            sensor_width=3936,
            sensor_height=2176,
            anamorphic_factor=2.0,
        )
        self.assert_rect_valid(rect)


if __name__=="__main__":
    unittest.main()
