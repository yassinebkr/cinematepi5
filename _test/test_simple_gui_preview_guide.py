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
    "redis": types.SimpleNamespace(StrictRedis=object),
    "sugarpie": types.SimpleNamespace(pisugar=types.SimpleNamespace()),
}
_saved_modules = {name: sys.modules.get(name, _MISSING) for name in _STUBS}
try:
    sys.modules.update(_STUBS)
    from module.simple_gui import _calculate_preview_guide_rect
finally:
    for name, previous in _saved_modules.items():
        if previous is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    sys.modules.pop("module.simple_gui", None)


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
