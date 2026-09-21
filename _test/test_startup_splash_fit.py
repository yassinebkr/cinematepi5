import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "src" / "main.py").read_text(encoding="utf-8")


class StartupSplashFitTests(unittest.TestCase):
    def test_startup_image_uses_aspect_preserving_cover_fit(self):
        self.assertIn("ImageOps.exif_transpose(source)", MAIN)
        self.assertIn("ImageOps.fit(", MAIN)
        self.assertIn("centering=(0.5, 0.5)", MAIN)
        self.assertNotIn("pic = pic.resize((W, H))", MAIN)


if __name__ == "__main__":
    unittest.main()
