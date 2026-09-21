import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "cinemate-settings-editor-token.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("settings_editor_token_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()


class SettingsEditorTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_ctx.name)
        self.addCleanup(self.tmp_ctx.cleanup)
        self.conf = self.tmp / "editor.conf"

    def root(self):
        return mock.patch.object(tool.os, "geteuid", return_value=0)

    def fake_group(self):
        fake = type("G", (), {"gr_gid": os.getgid()})()
        return mock.patch.object(tool.grp, "getgrnam", return_value=fake)

    def fake_chown(self):
        return mock.patch.object(tool.os, "chown")

    def test_ensure_creates_then_preserves_token(self):
        with self.root(), self.fake_group(), self.fake_chown():
            first, created = tool.ensure(path=self.conf, group="pi")
            second, created_again = tool.ensure(path=self.conf, group="pi")
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 24)
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o640)

    def test_rotate_changes_token(self):
        with self.root(), self.fake_group(), self.fake_chown():
            first, _ = tool.ensure(path=self.conf, group="pi")
            second = tool.rotate(path=self.conf, group="pi")
        self.assertNotEqual(first, second)
        self.assertEqual(tool.read_token(self.conf), second)

    def test_mutation_requires_root(self):
        with mock.patch.object(tool.os, "geteuid", return_value=1000):
            with self.assertRaises(RuntimeError):
                tool.rotate(path=self.conf, group="pi")


if __name__ == "__main__":
    unittest.main()
