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
        _format_level_hud_roll,
        _snap_level_hud_roll,
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


class LevelHudZeroSnapTests(unittest.TestCase):
    def test_values_strictly_inside_half_display_unit_snap_to_zero(self):
        for value in (-0.049, -0.001, -0.0, 0.0, 0.001, 0.049):
            with self.subTest(value=value):
                self.assertEqual(_snap_level_hud_roll(value, 1), 0.0)
                self.assertEqual(_format_level_hud_roll(value, 1), "0.0°")

    def test_boundary_and_visible_values_are_not_hidden(self):
        cases = [
            (-0.050, "-0.1°"),
            (0.050, "+0.1°"),
            (-0.051, "-0.1°"),
            (0.051, "+0.1°"),
            (-12.5, "-12.5°"),
            (12.5, "+12.5°"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_snap_level_hud_roll(value, 1), value)
                self.assertEqual(_format_level_hud_roll(value, 1), expected)

    def test_two_decimal_helper_uses_matching_half_unit_threshold(self):
        self.assertEqual(_format_level_hud_roll(-0.0049, 2), "0.00°")
        self.assertEqual(_format_level_hud_roll(0.0049, 2), "0.00°")
        self.assertEqual(_format_level_hud_roll(-0.0051, 2), "-0.01°")
        self.assertEqual(_format_level_hud_roll(0.0051, 2), "+0.01°")


class _HudRedis:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        value = self.values.get(key)
        if value is None:
            return None
        return str(value).encode("utf-8")


class _HudDrawRecorder:
    def __init__(self):
        self.lines = []
        self.rectangles = []
        self.texts = []
        self.ellipses = []

    def ellipse(self, coords, **kwargs):
        self.ellipses.append((coords, kwargs))

    def line(self, coords, **kwargs):
        self.lines.append((coords, kwargs))

    def rectangle(self, coords, **kwargs):
        self.rectangles.append((coords, kwargs))

    def text(self, coords, text, **kwargs):
        self.texts.append((coords, text, kwargs))


class LevelHudRenderPathTests(unittest.TestCase):
    def render(self, roll, shake):
        from module.simple_gui import SimpleGUI

        gui = SimpleGUI.__new__(SimpleGUI)
        gui._hud_rc = _HudRedis({
            "imu_roll": roll,
            "imu_shake": shake,
        })
        gui.disp_width = 1920
        gui.disp_height = 1080
        gui.width = 3856
        gui.height = 2180
        gui._hud_font = object()
        gui._hud_logged = True

        draw = _HudDrawRecorder()
        SimpleGUI.draw_level_hud(gui, draw)
        return draw

    def test_subprecision_positive_and_negative_roll_render_identically_level(self):
        positive = self.render(0.049, 6.0)
        negative = self.render(-0.049, 6.0)

        positive_labels = [text for _, text, _ in positive.texts]
        negative_labels = [text for _, text, _ in negative.texts]
        self.assertIn("0.0°", positive_labels)
        self.assertIn("0.0°", negative_labels)
        self.assertNotIn("+0.0°", positive_labels)
        self.assertNotIn("-0.0°", negative_labels)

        positive_horizon = positive.lines[0][0]
        negative_horizon = negative.lines[0][0]
        self.assertEqual(positive_horizon, negative_horizon)
        self.assertEqual(positive_horizon[0][1], positive_horizon[1][1])

        # Shake must still render while roll is visually snapped to level.
        self.assertIn("6°/s", positive_labels)
        filled_bar = positive.rectangles[0][0]
        self.assertGreater(filled_bar[2], filled_bar[0])

    def test_roll_just_outside_snap_moves_line_and_keeps_sign(self):
        positive = self.render(0.051, 0.0)
        negative = self.render(-0.051, 0.0)

        self.assertIn("+0.1°", [text for _, text, _ in positive.texts])
        self.assertIn("-0.1°", [text for _, text, _ in negative.texts])
        self.assertNotEqual(positive.lines[0][0][0][1], positive.lines[0][0][1][1])
        self.assertNotEqual(negative.lines[0][0][0][1], negative.lines[0][0][1][1])

    def test_positive_roll_and_shake_reach_actual_draw_calls(self):
        draw = self.render(12.5, 6.0)
        labels = [text for _, text, _ in draw.texts]
        self.assertIn("+12.5°", labels)
        self.assertIn("6°/s", labels)

        horizon = draw.lines[0][0]
        self.assertNotEqual(horizon[0][1], horizon[1][1])

        filled_bar = draw.rectangles[0][0]
        self.assertGreater(filled_bar[2], filled_bar[0])

    def test_negative_roll_preserves_direction_and_geometry(self):
        draw = self.render(-12.5, 6.0)
        labels = [text for _, text, _ in draw.texts]
        self.assertIn("-12.5°", labels)
        horizon = draw.lines[0][0]
        self.assertNotEqual(horizon[0][1], horizon[1][1])

    def test_high_shake_saturates_bar_instead_of_sticking_at_zero(self):
        draw = self.render(0.0, 50.0)
        labels = [text for _, text, _ in draw.texts]
        self.assertIn("50°/s", labels)
        filled = draw.rectangles[0][0]
        outline = draw.rectangles[1][0]
        self.assertEqual(filled[0], outline[0])
        self.assertEqual(filled[2], outline[2])

    def test_missing_redis_values_fall_back_to_zero_without_exception(self):
        draw = self.render("", "")
        labels = [text for _, text, _ in draw.texts]
        self.assertIn("0.0°", labels)
        self.assertIn("0°/s", labels)


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
