import importlib.util
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "cinemate-edit-settings.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("cinemate_edit_settings", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


editor = load_tool()


class SettingsEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_ctx.name)
        self.addCleanup(self.tmp_ctx.cleanup)
        self.settings = self.tmp / "settings.json"
        self.backups = self.tmp / "backups"
        self.original = b'{\n  "preview": {"default_zoom": 1.0, "zoom_steps": [1.0, 2.0]}\n}\n'
        self.settings.write_bytes(self.original)
        os.chmod(self.settings, 0o640)
        self.messages = []

    def runner_writing(self, text, *, also=None, returncode=0):
        def runner(cmd, check=False):
            Path(cmd[-1]).write_text(text, encoding="utf-8")
            if also is not None:
                also()
            return subprocess.CompletedProcess(cmd, returncode)
        return runner

    def run_edit(self, runner):
        return editor.edit_settings(
            self.settings,
            backup_dir=self.backups,
            editor="fake-editor",
            runner=runner,
            interactive_retry=False,
            output=self.messages.append,
        )

    def test_valid_edit_is_backed_up_and_atomically_replaced(self):
        rc = self.run_edit(self.runner_writing(
            '{"preview":{"default_zoom":2.0,"zoom_steps":[1.0,2.0]}}\n'
        ))
        self.assertEqual(rc, 0)
        self.assertIn('"default_zoom":2.0', self.settings.read_text())
        backups = editor.backup_paths(self.backups)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o640)

    def test_invalid_json_never_touches_live_file(self):
        rc = self.run_edit(self.runner_writing('{"preview": // comment\n{}}\n'))
        self.assertEqual(rc, 2)
        self.assertEqual(self.settings.read_bytes(), self.original)
        self.assertEqual(editor.backup_paths(self.backups), [])

    def test_structurally_invalid_json_never_touches_live_file(self):
        rc = self.run_edit(self.runner_writing('{"preview":"broken"}\n'))
        self.assertEqual(rc, 2)
        self.assertEqual(self.settings.read_bytes(), self.original)
        self.assertTrue(any("preview" in message for message in self.messages))

    def test_concurrent_live_change_is_not_overwritten(self):
        external = b'{"preview":{"default_zoom":1.5,"zoom_steps":[1.0,1.5]}}\n'

        def concurrent_change():
            self.settings.write_bytes(external)

        rc = self.run_edit(self.runner_writing(
            '{"preview":{"default_zoom":2.0,"zoom_steps":[1.0,2.0]}}\n',
            also=concurrent_change,
        ))
        self.assertEqual(rc, 3)
        self.assertEqual(self.settings.read_bytes(), external)
        self.assertEqual(editor.backup_paths(self.backups), [])

    def test_no_change_creates_no_backup(self):
        rc = self.run_edit(self.runner_writing(self.original.decode("utf-8")))
        self.assertEqual(rc, 0)
        self.assertEqual(self.settings.read_bytes(), self.original)
        self.assertEqual(editor.backup_paths(self.backups), [])

    def test_editor_failure_leaves_live_file_untouched(self):
        rc = self.run_edit(self.runner_writing(
            '{"preview":{"default_zoom":2.0,"zoom_steps":[1.0,2.0]}}\n',
            returncode=7,
        ))
        self.assertEqual(rc, 7)
        self.assertEqual(self.settings.read_bytes(), self.original)

    def test_installer_and_update_path_use_safe_editor(self):
        install = (ROOT / "cinemate-install.sh").read_text(encoding="utf-8")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("tools/cinemate-edit-settings.py", install)
        self.assertIn("install-editsettings-alias.sh", makefile)


if __name__ == "__main__":
    unittest.main()
