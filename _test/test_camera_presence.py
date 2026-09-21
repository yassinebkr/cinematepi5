import unittest

from module.camera_presence import camera_present_from_cameras_value


class CameraPresenceTests(unittest.TestCase):
    def test_missing_and_empty_values_are_absent(self):
        for value in (None, "", "   ", "[]", b"[]", [], ()):
            with self.subTest(value=value):
                self.assertFalse(camera_present_from_cameras_value(value))

    def test_nonempty_json_list_is_present(self):
        self.assertTrue(camera_present_from_cameras_value('[{"index":0}]'))
        self.assertTrue(camera_present_from_cameras_value([{"index": 0}]))
        self.assertTrue(camera_present_from_cameras_value(({"index": 0},)))

    def test_malformed_or_wrong_shape_is_absent(self):
        for value in ("not-json", "{}", "null", "0", b"\xff"):
            with self.subTest(value=value):
                self.assertFalse(camera_present_from_cameras_value(value))


if __name__ == "__main__":
    unittest.main()
