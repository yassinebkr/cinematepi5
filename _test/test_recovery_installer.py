import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "cinemate-install.sh").read_text(encoding="utf-8")
SERVICE_MAKEFILE = (ROOT / "services" / "Makefile").read_text(encoding="utf-8")
RECOVERY_MAKEFILE = (
    ROOT / "services" / "cinemate-recovery" / "Makefile"
).read_text(encoding="utf-8")


class RecoveryInstallerTests(unittest.TestCase):
    def test_recovery_service_is_enabled_by_default(self):
        self.assertIn(
            'ENABLE_RECOVERY_CONSOLE_SERVICE="${ENABLE_RECOVERY_CONSOLE_SERVICE:-1}"',
            INSTALLER,
        )

    def test_installer_generates_cryptographic_token(self):
        self.assertIn("secrets.token_urlsafe(24)", INSTALLER)

    def test_installer_preserves_existing_token(self):
        self.assertIn('existing_token="$(sudo awk', INSTALLER)
        self.assertIn('recovery_token="$existing_token"', INSTALLER)

    def test_fallback_config_is_root_readable_only(self):
        self.assertRegex(
            INSTALLER,
            r'sudo install -o root -g root -m 600 "\$temp" "\$conf_path"',
        )

    def test_config_txt_editing_stays_disabled_by_default(self):
        self.assertIn("allow_config_txt=false", INSTALLER)

    def test_settings_editor_token_helper_is_installed_and_ensured(self):
        self.assertIn(
            'local tool_src="$CINEMATE_DIR/tools/cinemate-settings-editor-token.py"',
            INSTALLER,
        )
        self.assertIn(
            'sudo install -m 755 "$tool_src" /usr/local/bin/cinemate-settings-editor-token',
            INSTALLER,
        )
        self.assertIn(
            'cinemate-settings-editor-token ensure --group "$PI_GROUP"',
            INSTALLER,
        )

    def test_settings_editor_token_is_group_readable_not_world_readable(self):
        helper = (ROOT / "tools" / "cinemate-settings-editor-token.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("os.chmod(tmp_name, 0o640)", helper)


    def test_recovery_service_is_in_umbrella_makefile(self):
        self.assertIn("cinemate-recovery", SERVICE_MAKEFILE)

    def test_installer_enables_recovery_through_umbrella_makefile(self):
        self.assertIn(
            'sudo make -C "$CINEMATE_SOURCE_DIR/services" enable-cinemate-recovery',
            INSTALLER,
        )

    def test_recovery_service_installs_state_and_private_backup_dirs(self):
        self.assertIn("install -d -m 755 /var/lib/cinemate", RECOVERY_MAKEFILE)
        self.assertIn("install -d -m 700 /var/lib/cinemate/backups", RECOVERY_MAKEFILE)

    def test_installer_does_not_ship_a_fixed_token(self):
        block = INSTALLER[
            INSTALLER.index("write_recovery_conf() {"):
            INSTALLER.index("configure_media_permissions() {")
        ]
        token_assignments = re.findall(r"^token=(.*)$", block, flags=re.MULTILINE)
        self.assertEqual(token_assignments, ["$recovery_token"])

    def test_recovery_service_can_be_explicitly_disabled(self):
        self.assertIn(
            'if is_true "$ENABLE_RECOVERY_CONSOLE_SERVICE"; then',
            INSTALLER,
        )
        self.assertIn('detail "Skipping cinemate-recovery.service"', INSTALLER)


if __name__ == "__main__":
    unittest.main()
