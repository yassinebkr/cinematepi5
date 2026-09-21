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
        self.asset_dir = self.tmp / "settings-assets"
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
            mock.patch.object(se, "SETTINGS_ASSET_DIR", self.asset_dir),
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


    def test_template_renders_schema_driven_image_widget(self):
        html = (
            Path(__file__).resolve().parents[1]
            / "src/module/app/templates/settings_editor.html"
        ).read_text(encoding="utf-8")
        self.assertIn('meta.widget === "image-upload"', html)
        self.assertIn('form.append("file", file)', html)
        self.assertIn('parent[key] = null', html)
        self.assertIn('/settings-editor/api/assets/image?path=', html)
        self.assertIn('!(options.body instanceof FormData)', html)

    def test_template_uses_hybrid_desktop_grid_and_mobile_collapse(self):
        html = (
            Path(__file__).resolve().parents[1]
            / "src/module/app/templates/settings_editor.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "#settings-root{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))",
            html,
        )
        self.assertIn(".field--wide{grid-column:1/-1}", html)
        self.assertIn('row.classList.add("metadata-field", "field--wide")', html)
        self.assertIn("field field--wide field--array", html)
        self.assertIn("@media(max-width:900px)", html)
        self.assertIn("#settings-root,.inside{grid-template-columns:1fr", html)

    def test_get_exposes_ui_metadata_for_welcome_image(self):
        res = self.client.get("/settings-editor/api/settings", headers=self.headers())
        self.assertEqual(res.status_code, 200)
        ui = res.get_json()["ui"]
        self.assertEqual(ui["welcome_image"]["widget"], "image-upload")
        self.assertEqual(ui["welcome_image"]["accept"], "image/*")

    def _png_bytes(self):
        import io
        from PIL import Image
        out = io.BytesIO()
        Image.new("RGBA", (32, 18), (20, 40, 60, 128)).save(out, format="PNG")
        return out.getvalue()

    def test_image_upload_is_authenticated_normalized_and_does_not_save_settings(self):
        import io
        before = self.settings.read_bytes()
        res = self.client.post(
            "/settings-editor/api/assets/image",
            headers=self.headers(),
            data={"file": (io.BytesIO(self._png_bytes()), "startup.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        asset = Path(data["path"])
        self.assertEqual(asset.parent, self.asset_dir)
        self.assertEqual(asset.suffix, ".png")
        self.assertTrue(asset.is_file())
        self.assertEqual(self.settings.read_bytes(), before)
        from PIL import Image
        with Image.open(asset) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (32, 18))
        preview = self.client.get(
            "/settings-editor/api/assets/image",
            headers=self.headers(),
            query_string={"path": str(asset)},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, "image/png")

    def test_image_upload_rejects_invalid_image(self):
        import io
        res = self.client.post(
            "/settings-editor/api/assets/image",
            headers=self.headers(),
            data={"file": (io.BytesIO(b"not-an-image"), "fake.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(list(self.asset_dir.glob("*")), [])

    def test_image_preview_refuses_external_file(self):
        external = self.tmp / "external.png"
        external.write_bytes(self._png_bytes())
        res = self.client.get(
            "/settings-editor/api/assets/image",
            headers=self.headers(),
            query_string={"path": str(external)},
        )
        self.assertEqual(res.status_code, 404)

    def test_image_upload_is_locked_during_camera_activity(self):
        import io
        self.redis.values = {ParameterKey.IS_RECORDING.value: "1"}
        res = self.client.post(
            "/settings-editor/api/assets/image",
            headers=self.headers(),
            data={"file": (io.BytesIO(self._png_bytes()), "startup.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(list(self.asset_dir.glob("*")), [])

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
            ParameterKey.STORAGE_PREROLL_ACTIVE.value,
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
        invoke = mock.Mock(return_value=None)
        with (
            mock.patch.object(se, "_invoke_restart_helper", invoke),
            mock.patch.object(se.threading, "Timer", ImmediateTimer),
        ):
            res = self.client.post(
                "/settings-editor/api/restart",
                headers=self.headers(),
                json={},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            invoke.call_args_list,
            [mock.call(check=True), mock.call(check=False)],
        )

    def test_restart_preflight_failure_is_reported_before_timer(self):
        with mock.patch.object(
            se,
            "_invoke_restart_helper",
            return_value="Restart helper is unavailable.",
        ):
            res = self.client.post(
                "/settings-editor/api/restart",
                headers=self.headers(),
                json={},
            )
        self.assertEqual(res.status_code, 503)
        self.assertIn("unavailable", res.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
