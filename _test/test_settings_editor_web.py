import hashlib
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from module.redis_controller import ParameterKey

se = importlib.import_module("module.app.settings_editor")


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_value(self, key, default=None):
        return self.values.get(key, default)


class FakeController:
    def __init__(self):
        self.restarts = 0

    def restart_cinemate(self):
        self.restarts += 1


class ImmediateTimer:
    def __init__(self, delay, fn):
        self.fn = fn
        self.daemon = False

    def start(self):
        self.fn()


class SettingsEditorRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_ctx.name)
        self.addCleanup(self.tmp_ctx.cleanup)
        self.settings = self.tmp / "settings.json"
        self.conf = self.tmp / "editor.conf"
        self.backup_dir = self.tmp / "settings-backups"
        self.token = "test-token"
        self.conf.write_text("token=" + self.token + "\n", encoding="utf-8")
        self.initial = {
            "system": {
                "wifi_hotspot": {
                    "name": "CinePi",
                    "password": "wifi-secret",
                    "enabled": True,
                },
                "recovery": {"token": "must-not-leak"},
            },
            "preview": {"default_zoom": 1.0, "zoom_steps": [1.0, 2.0]},
            "future_unrendered": {"keep": 7},
        }
        self.settings.write_text(json.dumps(self.initial, indent=2) + "\n", encoding="utf-8")
        self.redis = FakeRedis()
        self.controller = FakeController()

        self.patches = [
            mock.patch.object(se, "SETTINGS_FILE", self.settings),
            mock.patch.object(se, "TOKEN_CONF", self.conf),
            mock.patch.object(se, "SETTINGS_BACKUP_DIR", self.backup_dir),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

        app = Flask(__name__)
        app.config["REDIS_CONTROLLER"] = self.redis
        app.config["CINEPI_CONTROLLER"] = self.controller
        app.register_blueprint(se.settings_editor_bp)
        self.client = app.test_client()

    def headers(self, token=None):
        return {se.TOKEN_HEADER: self.token if token is None else token}

    def revision(self):
        return hashlib.sha256(self.settings.read_bytes()).hexdigest()

    def test_public_page_contains_no_settings_or_wifi_password(self):
        res = self.client.get("/settings-editor/")
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)
        self.assertNotIn("wifi-secret", text)
        self.assertNotIn("must-not-leak", text)

    def test_browser_does_not_persist_editor_token(self):
        html = (
            Path(__file__).resolve().parents[1]
            / "src/module/app/templates/settings_editor.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("localStorage", html)
        self.assertNotIn("sessionStorage", html)
        self.assertNotIn("document.cookie", html)
        self.assertIn('var editorToken = "";', html)


    def test_api_requires_token(self):
        self.assertEqual(self.client.get("/settings-editor/api/settings").status_code, 403)
        self.assertEqual(
            self.client.get("/settings-editor/api/settings", headers=self.headers("wrong")).status_code,
            403,
        )

    def test_blank_config_locks_api(self):
        self.conf.write_text("token=\n", encoding="utf-8")
        res = self.client.get("/settings-editor/api/auth-check", headers=self.headers())
        self.assertEqual(res.status_code, 503)

    def test_get_hides_recovery_token_but_keeps_wifi_password(self):
        res = self.client.get("/settings-editor/api/settings", headers=self.headers())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["settings"]["system"]["wifi_hotspot"]["password"], "wifi-secret")
        self.assertNotIn("token", data["settings"]["system"]["recovery"])

    def test_save_preserves_hidden_and_unrendered_keys(self):
        data = self.client.get("/settings-editor/api/settings", headers=self.headers()).get_json()
        payload = data["settings"]
        payload["preview"]["default_zoom"] = 2.0
        res = self.client.put(
            "/settings-editor/api/settings",
            headers=self.headers(),
            json={"settings": payload, "revision": data["revision"]},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        saved = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(saved["preview"]["default_zoom"], 2.0)
        self.assertEqual(saved["system"]["recovery"]["token"], "must-not-leak")
        self.assertEqual(saved["future_unrendered"], {"keep": 7})
        backups = list(self.backup_dir.glob("*.bak"))
        self.assertEqual(len(backups), 1)

    def test_hidden_secret_inside_array_is_preserved(self):
        self.initial["future_list"] = [
            {"name": "one", "token": "array-secret", "enabled": True}
        ]
        self.settings.write_text(
            json.dumps(self.initial, indent=2) + "\n", encoding="utf-8"
        )
        data = self.client.get(
            "/settings-editor/api/settings", headers=self.headers()
        ).get_json()
        item = data["settings"]["future_list"][0]
        self.assertNotIn("token", item)
        item["enabled"] = False

        res = self.client.put(
            "/settings-editor/api/settings",
            headers=self.headers(),
            json={"settings": data["settings"], "revision": data["revision"]},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        saved = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(saved["future_list"][0]["token"], "array-secret")
        self.assertFalse(saved["future_list"][0]["enabled"])

    def test_protected_array_cannot_be_resized_from_web_editor(self):
        self.initial["future_list"] = [
            {"name": "one", "token": "array-secret"}
        ]
        self.settings.write_text(
            json.dumps(self.initial, indent=2) + "\n", encoding="utf-8"
        )
        data = self.client.get(
            "/settings-editor/api/settings", headers=self.headers()
        ).get_json()
        data["settings"]["future_list"].append({"name": "two"})

        res = self.client.put(
            "/settings-editor/api/settings",
            headers=self.headers(),
            json={"settings": data["settings"], "revision": data["revision"]},
        )
        self.assertEqual(res.status_code, 400)
        saved = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["future_list"]), 1)
        self.assertEqual(saved["future_list"][0]["token"], "array-secret")


    def test_stale_revision_cannot_overwrite_newer_file(self):
        stale = self.revision()
        newer = dict(self.initial)
        newer["external_change"] = True
        self.settings.write_text(json.dumps(newer) + "\n", encoding="utf-8")
        res = self.client.put(
            "/settings-editor/api/settings",
            headers=self.headers(),
            json={"settings": {"preview": {"default_zoom": 2.0}}, "revision": stale},
        )
        self.assertEqual(res.status_code, 409)
        self.assertTrue(json.loads(self.settings.read_text())["external_change"])

    def test_structurally_invalid_candidate_is_rejected_without_write(self):
        before = self.settings.read_bytes()
        res = self.client.put(
            "/settings-editor/api/settings",
            headers=self.headers(),
            json={"settings": {"preview": "broken"}, "revision": self.revision()},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.settings.read_bytes(), before)

    def test_save_is_locked_during_every_recording_or_flush_state(self):
        for key in (
            ParameterKey.IS_RECORDING.value,
            ParameterKey.IS_WRITING.value,
            ParameterKey.IS_WRITING_BUF.value,
            ParameterKey.IS_BUFFERING.value,
        ):
            with self.subTest(key=key):
                self.redis.values = {key: "1"}
                before = self.settings.read_bytes()
                res = self.client.put(
                    "/settings-editor/api/settings",
                    headers=self.headers(),
                    json={"settings": {"preview": {"default_zoom": 2.0}}, "revision": self.revision()},
                )
                self.assertEqual(res.status_code, 409)
                self.assertEqual(self.settings.read_bytes(), before)

    def test_restart_is_locked_while_busy(self):
        self.redis.values = {ParameterKey.IS_WRITING_BUF.value: "1"}
        res = self.client.post("/settings-editor/api/restart", headers=self.headers(), json={})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.controller.restarts, 0)

    def test_restart_rechecks_activity_at_timer_boundary(self):
        with mock.patch.object(se.threading, "Timer", ImmediateTimer):
            res = self.client.post("/settings-editor/api/restart", headers=self.headers(), json={})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.controller.restarts, 1)


if __name__ == "__main__":
    unittest.main()
