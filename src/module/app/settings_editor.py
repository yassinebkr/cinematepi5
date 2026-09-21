"""Authenticated structured editor for CineMate strict-JSON settings.

This surface deliberately edits only src/settings.json. Recovery configuration,
boot configuration, storage and playback stay on their dedicated surfaces.

Authentication is a non-persistent bearer token supplied in
X-CineMate-Settings-Token. The browser keeps it only in JavaScript memory.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import secrets
import subprocess
import tempfile
import threading
import warnings
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from module.config_loader import SettingsLoadError, load_settings
from module.redis_controller import ParameterKey
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

settings_editor_bp = Blueprint(
    "settings_editor",
    __name__,
    url_prefix="/settings-editor",
    template_folder="templates",
)

SETTINGS_FILE = Path(__file__).resolve().parents[2] / "settings.json"
SETTINGS_SCHEMA_FILE = SETTINGS_FILE.with_name("settings.schema.json")
SETTINGS_ASSET_DIR = Path.home() / ".local" / "share" / "cinemate" / "settings-assets"
TOKEN_CONF = Path("/etc/cinemate-settings-editor.conf")
TOKEN_HEADER = "X-CineMate-Settings-Token"
BACKUP_KEEP = 10
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
SETTINGS_BACKUP_DIR = Path.home() / ".local" / "state" / "cinemate" / "settings-backups"
RESTART_HELPER = Path("/usr/local/bin/cinemate-restart-service")
SUDO_BIN = Path("/usr/bin/sudo")

_BUSY_KEYS = (
    ("recording", ParameterKey.IS_RECORDING.value),
    ("writing", ParameterKey.IS_WRITING.value),
    ("writing_buf", ParameterKey.IS_WRITING_BUF.value),
    ("buffering", ParameterKey.IS_BUFFERING.value),
    ("storage_preroll", ParameterKey.STORAGE_PREROLL_ACTIVE.value),
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


def _load_editor_ui_metadata(path: Path | None = None) -> dict:
    source = SETTINGS_SCHEMA_FILE if path is None else Path(path)
    try:
        schema = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Settings UI metadata unavailable from %s: %s", source, exc)
        return {}

    result = {}

    def walk(node, parts):
        if not isinstance(node, dict):
            return
        ui = node.get("x-cinemate-ui")
        if parts and isinstance(ui, dict):
            result[".".join(parts)] = dict(ui)
        props = node.get("properties")
        if isinstance(props, dict):
            for key, child in props.items():
                walk(child, parts + [str(key)])

    walk(schema, [])
    return result


def _atomic_write_asset(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o750)
    if path.exists():
        return
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
        tmp_name = ""
        _fsync_directory(path.parent)
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _normalize_uploaded_image(raw: bytes) -> tuple[bytes, int, int]:
    if not raw:
        raise ValueError("The uploaded image is empty.")
    if len(raw) > MAX_IMAGE_UPLOAD_BYTES:
        raise ValueError(
            f"Image exceeds the {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit."
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as opened:
                opened.load()
                image = ImageOps.exif_transpose(opened)
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ValueError("Image dimensions are invalid.")
                if width * height > MAX_IMAGE_PIXELS:
                    raise ValueError(
                        f"Image is too large after decoding ({width}x{height}); "
                        f"maximum is {MAX_IMAGE_PIXELS:,} pixels."
                    )
                normalized = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Unsupported or invalid image: {exc}") from exc
    except Image.DecompressionBombWarning as exc:
        raise ValueError(f"Image is too large to decode safely: {exc}") from exc

    output = io.BytesIO()
    normalized.save(output, format="PNG", optimize=True)
    return output.getvalue(), width, height


def _managed_asset_path(raw_path: str) -> Path:
    base = SETTINGS_ASSET_DIR.resolve()
    candidate = Path(raw_path).expanduser().resolve(strict=True)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("Only CineMate-managed settings assets can be previewed.") from exc
    if not candidate.is_file():
        raise ValueError("Managed settings asset does not exist.")
    return candidate


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


def _invoke_restart_helper(
    *,
    check: bool,
    runner=subprocess.run,
) -> str | None:
    if not SUDO_BIN.is_file():
        return f"Restart unavailable: {SUDO_BIN} is missing."
    if not RESTART_HELPER.is_file():
        return f"Restart unavailable: {RESTART_HELPER} is missing."

    command = [str(SUDO_BIN), "-n", str(RESTART_HELPER)]
    if check:
        command.append("--check")

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Restart helper failed: {type(exc).__name__}: {exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if detail:
            detail = f" Detail: {detail[:300]}"
        return (
            f"Restart helper is unavailable or not authorized "
            f"(exit {result.returncode}).{detail}"
        )
    return None


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
        "ui": _load_editor_ui_metadata(),
    })


@settings_editor_bp.route("/api/assets/image", methods=["POST"])
@require_editor_token
def upload_settings_image():
    states = _busy_states()
    message = _busy_message(states)
    if message:
        return jsonify({"ok": False, "message": message, "activity": states}), 409

    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"ok": False, "message": "Upload requires a file field."}), 400

    raw = uploaded.stream.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    if len(raw) > MAX_IMAGE_UPLOAD_BYTES:
        return jsonify({
            "ok": False,
            "message": (
                f"Image exceeds the {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MiB "
                "upload limit."
            ),
        }), 413

    try:
        normalized, width, height = _normalize_uploaded_image(raw)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    digest = hashlib.sha256(normalized).hexdigest()
    target = SETTINGS_ASSET_DIR / f"settings-image-{digest[:20]}.png"
    try:
        _atomic_write_asset(target, normalized)
    except OSError as exc:
        logger.exception("Could not store managed settings image")
        return jsonify({
            "ok": False,
            "message": f"Could not store image asset: {exc}",
        }), 500

    return jsonify({
        "ok": True,
        "path": str(target),
        "width": width,
        "height": height,
        "bytes": len(normalized),
        "message": "Image uploaded and normalized to PNG. Save settings to make it active.",
    })


@settings_editor_bp.route("/api/assets/image")
@require_editor_token
def preview_settings_image():
    raw_path = request.args.get("path", "")
    if not raw_path:
        return jsonify({"ok": False, "message": "Missing asset path."}), 400
    try:
        target = _managed_asset_path(raw_path)
    except (OSError, ValueError) as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    return send_file(target, mimetype="image/png", conditional=True, max_age=0)


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

    preflight_error = _invoke_restart_helper(check=True)
    if preflight_error:
        return jsonify({"ok": False, "message": preflight_error}), 503

    redis_controller = current_app.config.get("REDIS_CONTROLLER")

    def guarded_restart():
        late_states = _busy_states(redis_controller)
        if any(late_states.values()):
            logger.warning(
                "Settings-editor restart cancelled because activity began: %s",
                late_states,
            )
            return
        restart_error = _invoke_restart_helper(check=False)
        if restart_error:
            logger.error(
                "Settings-editor CineMate restart failed: %s",
                restart_error,
            )

    timer = threading.Timer(0.5, guarded_restart)
    timer.daemon = True
    timer.start()
    return jsonify({
        "ok": True,
        "message": "Systemd-managed CineMate restart scheduled.",
        "restarting": True,
    })
