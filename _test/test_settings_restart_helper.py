import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "cinemate-restart-service"


class SettingsRestartHelperTests(unittest.TestCase):
    def test_check_mode_is_non_destructive(self):
        result = subprocess.run(
            [str(HELPER), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unexpected_arguments_are_rejected(self):
        result = subprocess.run(
            [str(HELPER), "--unexpected"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_only_fixed_cinemate_service_is_restart_target(self):
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn(
            "/bin/systemctl --no-block --no-ask-password restart cinemate-autostart.service",
            text,
        )
        self.assertNotIn('"$2"', text)


if __name__ == "__main__":
    unittest.main()
