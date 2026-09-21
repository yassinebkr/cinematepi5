import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("flask_socketio", types.SimpleNamespace(SocketIO=object))
sys.modules.setdefault("gpiozero", types.SimpleNamespace(CPUTemperature=object))
sys.modules.setdefault("redis", types.SimpleNamespace(StrictRedis=object))
sys.modules.setdefault("sugarpie", types.SimpleNamespace(pisugar=types.SimpleNamespace()))

from module.simple_gui import _calculate_preview_guide_rect


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
