"""Authenticated structured editor for CineMate strict-JSON settings.

This surface deliberately edits only src/settings.json. Recovery configuration,
boot configuration, storage and playback stay on their dedicated surfaces.

Authentication is a non-persistent bearer token supplied in
X-CineMate-Settings-Token. The browser keeps it only in JavaScript memory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from module.config_loader import SettingsLoadError, load_settings
from module.redis_controller import ParameterKey

logger = logging.getLogger(__name__)

settings_editor_bp = Blueprint(
    "settings_editor",
    __name__,
    url_prefix="/settings-editor",
    template_folder="templates",
)

SETTINGS_FILE = Path(__file__).resolve().parents[2] / "settings.json"
TOKEN_CONF = Path("/etc/cinemate-settings-editor.conf")
TOKEN_HEADER = "X-CineMate-Settings-Token"
BACKUP_KEEP = 10
SETTINGS_BACKUP_DIR = Path.home() / ".local" / "state" / "cinemate" / "settings-backups"

_BUSY_KEYS = (
    ("recording", ParameterKey.IS_RECORDING.value),
    ("writing", ParameterKey.IS_WRITING.value),
    ("writing_buf", ParameterKey.IS_WRITING_BUF.value),
    ("buffering", ParameterKey.IS_BUFFERING.value),
)

# Never send these key names to the browser. A recovery/API token accidentally
# stored in settings.json must not become readable merely because someone has
# the settings-editor credential. Password remains editable for Wi-Fi.
_HIDDEN_KEY_WORDS = ("token", "secret", "credential")


def _read_editor_token(path: Path | None = None) -> str:
    path = TOKEN_CONF if path is None else Path(path)
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "token":
                return value.strip()
    except OSError:
        return ""
    return ""


def _auth_result():
    expected = _read_editor_token()
    if not expected:
        return False, jsonify({
            "ok": False,
            "message": (
                "Settings editor is locked because no access token is configured. "
                "Run cinemate-settings-editor-token show locally on the Pi, or "
                "sudo cinemate-settings-editor-token rotate to create a new one."
            ),
        }), 503

    supplied = request.headers.get(TOKEN_HEADER, "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        return False, jsonify({
            "ok": False,
            "message": "Missing or incorrect settings-editor token.",
        }), 403
    return True, None, None


def require_editor_token(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        ok, response, status = _auth_result()
        if not ok:
            return response, status
        return fn(*args, **kwargs)

    return wrapped


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_raw_settings(data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"settings.json is not valid UTF-8: {exc}") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"settings.json is not valid strict JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("settings.json must contain a top-level JSON object")
    return parsed


def _settings_for_editor(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in _HIDDEN_KEY_WORDS):
                continue
            cleaned[key] = _settings_for_editor(child)
        return cleaned
    if isinstance(value, list):
        return [_settings_for_editor(item) for item in value]
    return value


def _contains_hidden_keys(value) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in _HIDDEN_KEY_WORDS):
                return True
            if _contains_hidden_keys(child):
                return True
    elif isinstance(value, list):
        return any(_contains_hidden_keys(item) for item in value)
    return False


def _merge_saved_settings(existing, payload):
    """Overlay editor values without deleting fields it never rendered.

    Lists normally replace as a unit because the editor exposes them as JSON
    arrays. If a list contains protected keys, equal-length lists merge by
    index so hidden values survive. Structural changes to such a protected
    list are refused because there is no safe way to infer which secret belongs
    to a newly reordered element.
    """
    if isinstance(existing, dict) and isinstance(payload, dict):
        merged = dict(existing)
        for key, value in payload.items():
            if key in merged:
                merged[key] = _merge_saved_settings(merged[key], value)
            else:
                merged[key] = value
        return merged

    if isinstance(existing, list) and isinstance(payload, list):
        if _contains_hidden_keys(existing):
            if len(existing) != len(payload):
                raise ValueError(
                    "A list containing protected secret fields cannot be resized "
                    "from the web editor. Use editsettings locally."
                )
            return [
                _merge_saved_settings(old_item, new_item)
                for old_item, new_item in zip(existing, payload)
            ]
        return payload

    return payload


def _is_on(value) -> bool:
    return str(value or "0").strip().lower() in {"1", "true", "yes", "on"}


def _busy_states(redis_controller=None) -> dict[str, bool]:
    rc = redis_controller
    if rc is None:
        rc = current_app.config.get("REDIS_CONTROLLER")
    if rc is None:
        return {name: False for name, _ in _BUSY_KEYS}
    result = {}
    for name, key in _BUSY_KEYS:
        try:
            result[name] = _is_on(rc.get_value(key, "0"))
        except TypeError:
            result[name] = _is_on(rc.get_value(key))
        except Exception:
            logger.exception("Could not read settings-editor busy state %s", key)
            result[name] = True
    return result


def _busy_message(states: dict[str, bool]) -> str | None:
    active = [name for name, state in states.items() if state]
    if not active:
        return None
    return (
        "Settings changes are locked while camera/storage activity is still active: "
        + ", ".join(active)
        + ". Wait until the take is finalized."
    )


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _backup_settings(
    dest: Path,
    data: bytes,
    backup_dir: Path | None = None,
) -> Path:
    backup_dir = SETTINGS_BACKUP_DIR if backup_dir is None else Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = backup_dir / f"{dest.name}.{stamp}.bak"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(backup_dir),
        prefix=f".{dest.name}.",
        suffix=".bak.tmp",
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
        tmp_name = ""
        _fsync_directory(backup_dir)
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    backups = sorted(backup_dir.glob(f"{dest.name}.*.bak"))
    for stale in backups[:-BACKUP_KEEP]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("Could not prune settings backup %s", stale)
    return target


def _validate_temp_settings(path: Path) -> str | None:
    try:
        load_settings(path)
    except SettingsLoadError as exc:
        return exc.format_for_cli(use_color=False)
    except Exception as exc:
        logger.exception("Unexpected settings validation failure")
        return f"CineMate validator failed unexpectedly: {type(exc).__name__}: {exc}"
    return None


@settings_editor_bp.route("/")
def editor_page():
    # Public shell only. No settings or secrets are embedded in the HTML.
    return render_template("settings_editor.html")


@settings_editor_bp.route("/api/auth-check")
@require_editor_token
def auth_check():
    return jsonify({"ok": True})


@settings_editor_bp.route("/api/status")
@require_editor_token
def editor_status():
    states = _busy_states()
    return jsonify({
        "ok": True,
        "activity": states,
        "finalized": not any(states.values()),
    })


@settings_editor_bp.route("/api/settings")
@require_editor_token
def get_settings():
    dest = Path(SETTINGS_FILE)
    try:
        data = dest.read_bytes()
        raw = _strict_raw_settings(data)
        # Validate the actual file as CineMate would before exposing it as
        # editable. A broken file belongs in the recovery console.
        load_settings(dest)
    except (OSError, ValueError, SettingsLoadError) as exc:
        logger.error("Settings editor cannot load %s: %s", dest, exc)
        return jsonify({
            "ok": False,
            "message": (
                "The live settings file is not safe to edit here. "
                f"Use the recovery console or editsettings locally. Detail: {exc}"
            ),
        }), 409

    return jsonify({
        "ok": True,
        "settings": _settings_for_editor(raw),
        "revision": _revision(data),
        "activity": _busy_states(),
    })


@settings_editor_bp.route("/api/settings", methods=["PUT"])
@require_editor_token
def put_settings():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "message": "Request body must be a JSON object."}), 400

    payload = body.get("settings")
    expected_revision = body.get("revision")
    if not isinstance(payload, dict) or not isinstance(expected_revision, str):
        return jsonify({
            "ok": False,
            "message": "Save requires settings object and revision string.",
        }), 400

    states = _busy_states()
    message = _busy_message(states)
    if message:
        return jsonify({"ok": False, "message": message, "activity": states}), 409

    dest = Path(SETTINGS_FILE)
    try:
        original = dest.read_bytes()
        original_stat = dest.stat()
        existing = _strict_raw_settings(original)
    except (OSError, ValueError) as exc:
        return jsonify({
            "ok": False,
            "message": (
                "The live settings file changed into an unreadable state; "
                f"nothing was written. Detail: {exc}"
            ),
        }), 409

    current_revision = _revision(original)
    if current_revision != expected_revision:
        return jsonify({
            "ok": False,
            "message": (
                "settings.json changed after this page loaded. Reload the editor "
                "before saving so the newer configuration is not overwritten."
            ),
            "revision": current_revision,
        }), 409

    try:
        merged = _merge_saved_settings(existing, payload)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    rendered = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(dest.parent),
            prefix=".settings-editor-",
            suffix=".json.tmp",
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, original_stat.st_mode & 0o777)

        problem = _validate_temp_settings(Path(tmp_name))
        if problem:
            return jsonify({"ok": False, "message": problem}), 400

        # Re-check both activity and file revision immediately before backup /
        # replace. A stale browser or a take that started during validation
        # must not be able to race the write.
        states = _busy_states()
        message = _busy_message(states)
        if message:
            return jsonify({"ok": False, "message": message, "activity": states}), 409

        if dest.read_bytes() != original:
            return jsonify({
                "ok": False,
                "message": (
                    "settings.json changed during validation. Reload before saving."
                ),
            }), 409

        try:
            backup = _backup_settings(dest, original)
        except OSError as exc:
            logger.exception("Settings backup failed; refusing save")
            return jsonify({
                "ok": False,
                "message": f"Backup failed; live settings were not changed: {exc}",
            }), 500

        if dest.read_bytes() != original:
            return jsonify({
                "ok": False,
                "message": (
                    "settings.json changed during the save operation. "
                    "The newer file was not overwritten."
                ),
            }), 409

        os.replace(tmp_name, dest)
        tmp_name = None
        _fsync_directory(dest.parent)
    except OSError as exc:
        logger.exception("Could not save settings")
        return jsonify({
            "ok": False,
            "message": f"Could not save settings.json: {exc}",
        }), 500
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    return jsonify({
        "ok": True,
        "message": "Saved. Restart CineMate when you are ready to apply the changes.",
        "revision": _revision(rendered),
        "backup": str(backup),
        "restarting": False,
    })


@settings_editor_bp.route("/api/restart", methods=["POST"])
@require_editor_token
def restart_cinemate():
    states = _busy_states()
    message = _busy_message(states)
    if message:
        return jsonify({"ok": False, "message": message, "activity": states}), 409

    controller = current_app.config.get("CINEPI_CONTROLLER")
    redis_controller = current_app.config.get("REDIS_CONTROLLER")
    if controller is None or not hasattr(controller, "restart_cinemate"):
        return jsonify({
            "ok": False,
            "message": "CineMate restart control is unavailable.",
        }), 503

    def guarded_restart():
        late_states = _busy_states(redis_controller)
        if any(late_states.values()):
            logger.warning(
                "Settings-editor restart cancelled because activity began: %s",
                late_states,
            )
            return
        try:
            controller.restart_cinemate()
        except Exception:
            logger.exception("Settings-editor CineMate restart failed")

    timer = threading.Timer(0.5, guarded_restart)
    timer.daemon = True
    timer.start()
    return jsonify({
        "ok": True,
        "message": "CineMate restart scheduled.",
        "restarting": True,
    })
