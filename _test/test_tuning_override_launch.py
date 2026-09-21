import copy
import json
import os
import sys
import tempfile
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
sys.modules.setdefault("psutil", types.SimpleNamespace())
sys.modules.setdefault("module.framebuffer", types.SimpleNamespace(Framebuffer=object))

import module.cinepi_multi as cinepi_multi
from module.cinepi_multi import CameraInfo, CinePiProcess

DEFAULT_TUNE = "/home/pi/libcamera/src/ipa/rpi/pisp/data/imx283.json"


class FakeRedisController:
    def get_value(self, key, default=None):
        # _build_args asks for cg_rb without an explicit default.
        if str(getattr(key, "value", key)) == "cg_rb":
            return "1.3,2.5"
        return default

    def set_value(self, key, value):
        pass


class FakeSensorDetect:
    def get_resolution_info(self, model_key, sensor_mode):
        return {
            "width": 3936,
            "height": 2176,
            "bit_depth": 12,
            "packing": "P",
        }

    def get_packing_for_platform(self, model_key, sensor_mode, is_pi4=None):
        return "P"


def settings_with_override(override):
    settings = copy.deepcopy(cinepi_multi._settings())
    settings.setdefault("camera", {}).setdefault("cam0", {})[
        "tuning_file_override"
    ] = override
    return settings


def build_args(override):
    settings = settings_with_override(override)
    with mock.patch("module.cinepi_multi._settings", return_value=settings), \
         mock.patch.object(CinePiProcess, "_is_pi4", return_value=False), \
         mock.patch("module.cinepi_multi._active_framebuffer_size", return_value=(1920,1080)):
        cam = CameraInfo(0, "imx283", "RGB", "i2c@1a")
        proc = CinePiProcess(
            FakeRedisController(),
            FakeSensorDetect(),
            cam,
            primary=True,
            multi=False,
        )
        return proc._build_args()


class TuningOverrideLaunchTests(unittest.TestCase):
    def tuning_arg(self, args):
        return args[args.index("--tuning-file") + 1]

    def test_disabled_override_uses_detected_tuning(self):
        args = build_args({"enabled": False, "path": "/does/not/exist"})
        self.assertEqual(self.tuning_arg(args), DEFAULT_TUNE)

    def test_missing_override_file_falls_back(self):
        with self.assertLogs(level="ERROR") as cm:
            args = build_args({"enabled": True, "path": "/does/not/exist"})
        self.assertEqual(self.tuning_arg(args), DEFAULT_TUNE)
        self.assertIn("file not found", "\n".join(cm.output))

    def test_blank_override_path_falls_back(self):
        with self.assertLogs(level="ERROR") as cm:
            args = build_args({"enabled": True, "path": "  "})
        self.assertEqual(self.tuning_arg(args), DEFAULT_TUNE)
        self.assertIn("no path", "\n".join(cm.output))

    def test_invalid_json_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.json"
            p.write_text('{"target":"pisp",',encoding="utf-8")
            with self.assertLogs(level="ERROR") as cm:
                args=build_args({"enabled":True,"path":str(p)})
        self.assertEqual(self.tuning_arg(args),DEFAULT_TUNE)
        self.assertIn("not valid JSON","\n".join(cm.output))

    def test_wrong_platform_target_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"vc4.json"
            p.write_text(json.dumps({"target":"bcm2835","algorithms":[]}),encoding="utf-8")
            with self.assertLogs(level="ERROR") as cm:
                args=build_args({"enabled":True,"path":str(p)})
        self.assertEqual(self.tuning_arg(args),DEFAULT_TUNE)
        self.assertIn("VC4","\n".join(cm.output))

    def test_valid_absolute_override_is_forwarded(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"valid.json"
            p.write_text(json.dumps({"target":"pisp","algorithms":[]}),encoding="utf-8")
            args=build_args({"enabled":True,"path":str(p)})
        self.assertEqual(self.tuning_arg(args),str(p.resolve()))

    def test_valid_relative_override_is_resolved_from_repo_root(self):
        relative="_test/.tmp-valid-tuning.json"
        p=ROOT/relative
        p.write_text(json.dumps({"target":"pisp","algorithms":[]}),encoding="utf-8")
        old=os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as td:
                os.chdir(td)
                args=build_args({"enabled":True,"path":relative})
        finally:
            os.chdir(old)
            p.unlink(missing_ok=True)
        self.assertEqual(self.tuning_arg(args),str((ROOT/relative).resolve()))


if __name__=="__main__":
    unittest.main()
