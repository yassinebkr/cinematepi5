import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'services' / 'cinemate-autostart' / 'cinemate-console-handoff.sh').read_text(encoding='utf-8')

MAIN = (ROOT / "src" / "main.py").read_text(encoding="utf-8")


class ConsoleHandoffTests(unittest.TestCase):
    def test_getty_handoff_is_nonblocking(self):
        self.assertIn(
            '/bin/systemctl --no-block --no-ask-password start getty@tty1.service',
            SCRIPT,
        )
        self.assertNotIn(
            '/bin/systemctl start getty@tty1.service',
            SCRIPT,
        )

    def test_handoff_skips_getty_during_cinemate_restart_job(self):
        self.assertIn("cinemate_restart_in_progress()", SCRIPT)
        self.assertIn('"cinemate-autostart.service"', SCRIPT)
        self.assertIn("restart|try-restart|reload-or-restart", SCRIPT)
        restart_guard = SCRIPT.index("if cinemate_restart_in_progress; then")
        getty_start = SCRIPT.index(
            "/bin/systemctl --no-block --no-ask-password start getty@tty1.service"
        )
        self.assertLess(restart_guard, getty_start)

    def test_systemd_managed_cleanup_delegates_console_handoff_to_execstoppost(self):
        self.assertIn(
            "if not shutdown_in_progress and not running_under_systemd_service():",
            MAIN,
        )

if __name__ == '__main__':
    unittest.main()
