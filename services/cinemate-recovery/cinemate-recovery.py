#!/usr/bin/env python3
"""Cinemate recovery console -- diagnose and repair a camera that will not start.

A deliberately ugly, deliberately dependency-free web console on :8080, run by
its own root systemd service. When Cinemate fails to start, the operator can
still reach this from a phone over the camera's hotspot (http://10.42.0.1:8080)
to see *why* it failed, edit settings.json and config.txt, and restart it --
with no laptop and no SSH.

  Operator docs: docs/recovery-console.md

THE ONE RULE
============
STANDARD LIBRARY ONLY. No flask, no jinja, no redis, and nothing from src/module/. "Cinemate's Python packages are
missing or broken" and "redis is down" are supported failure modes that this
console exists to survive; every import it makes is another way for it to
die exactly when it is needed.

The unit deliberately has no Wants= or After= on cinemate-autostart. That
coupling is the bug being fixed, not an oversight.

Everything degrades. Each configuration and validation step is a ladder whose
last rung still produces a usable answer -- see load_config() and
validate_settings_text(). A fallback that only fires when something else is
already broken is still tested; see _test/test_recovery_console.py.
"""

from __future__ import annotations

import argparse
import hmac
import html
import http.server
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import parse_qs, urlparse

# This branch uses strict JSON for settings. The recovery console remains
# standard-library-only and does not accept syntax the main runtime rejects.
log = logging.getLogger("cinemate-recovery")

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

SETTINGS_PATH  = Path("/home/pi/cinemate/src/settings.json")
CONF_PATH      = Path("/etc/cinemate-recovery.conf")
STATE_DIR      = Path("/var/lib/cinemate")
BACKUP_DIR     = STATE_DIR / "backups"
PENDING_PATH   = STATE_DIR / "config-pending.json"
HOTSPOT_STATE  = STATE_DIR / "hotspot.state"
FAILURE_FILE   = Path("/home/pi/.cache/cinemate/startup-failure.ansi")
CONFIG_TXT     = Path("/boot/firmware/config.txt")
CINEMATE_PYTHON = Path("/usr/bin/python3")
CINEMATE_SRC   = Path("/home/pi/cinemate/src")

#: Compiled-in defaults. A missing system.recovery block behaves exactly as
#: these -- requiring an edit to settings.json to get a working recovery
#: console would be circular.
DEFAULTS = {
    "enabled": True,
    "port": 8080,
    "token": "",
    "allow_config_txt": False,
    "config_confirm_timeout_s": 300,
}

#: No free-form service name ever reaches subprocess.
ALLOWED_SERVICES = ("cinemate-autostart", "wifi-hotspot", "storage-automount")
ALLOWED_ACTIONS = ("start", "stop", "restart")

#: The AP must never be stopped from here -- that is the operator's only way
#: back in. It may only be restarted, behind the re-arm timer below.
PROTECTED_SERVICES = ("wifi-hotspot",)
HOTSPOT_REARM_S = 60

MAX_LOG_LINES = 2000
DEFAULT_LOG_LINES = 200
BACKUP_KEEP = 10

CONFIG_RUNG_SETTINGS, CONFIG_RUNG_CONF, CONFIG_RUNG_DEFAULTS = 1, 2, 3
VALIDATE_RUNG_INTERPRETER, VALIDATE_RUNG_STDLIB, VALIDATE_RUNG_NONE = 1, 2, 3


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# 4.3 Recovery console config ladder
# ---------------------------------------------------------------------------

class ConsoleConfig(NamedTuple):
    enabled: bool
    port: int
    token: str
    allow_config_txt: bool
    config_confirm_timeout_s: int
    rung: int
    reason: str


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
    return default


def _as_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _merge(raw: dict, rung: int, reason: str) -> ConsoleConfig:
    """Coerce a raw mapping over DEFAULTS. Tolerates all-string values so the
    flat /etc/cinemate-recovery.conf rung shares this code path."""
    raw = raw if isinstance(raw, dict) else {}
    return ConsoleConfig(
        enabled=_as_bool(raw.get("enabled"), DEFAULTS["enabled"]),
        port=_as_int(raw.get("port"), DEFAULTS["port"]),
        token=str(raw.get("token", DEFAULTS["token"]) or ""),
        allow_config_txt=_as_bool(
            raw.get("allow_config_txt"), DEFAULTS["allow_config_txt"]
        ),
        config_confirm_timeout_s=_as_int(
            raw.get("config_confirm_timeout_s"), DEFAULTS["config_confirm_timeout_s"]
        ),
        rung=rung,
        reason=reason,
    )


def parse_conf(text: str) -> dict:
    """Parse the flat key=value fallback file. '#' comments, blank lines ok."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_config(
    settings_path: Path = SETTINGS_PATH,
    conf_path: Path = CONF_PATH,
) -> ConsoleConfig:
    """Resolve console configuration without depending on CineMate itself.

    Rung 1: valid settings.json. Values from system.recovery override the
            installer fallback file; omitted values (notably token) inherit
            from /etc/cinemate-recovery.conf when it is available.
    Rung 2: settings.json is unavailable/invalid -> fallback config file.
    Rung 3: neither is usable -> compiled defaults. With no token, mutating
            HTTP actions are locked rather than unauthenticated.
    """
    conf_raw = {}
    conf_ok = False
    conf_error = "not read"
    try:
        conf_raw = parse_conf(Path(conf_path).read_text(encoding="utf-8"))
        conf_ok = True
        conf_error = ""
    except Exception as exc:
        conf_error = f"{type(exc).__name__}: {exc}"

    try:
        text = Path(settings_path).read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
        system = data.get("system", {})
        if not isinstance(system, dict):
            system = {}
        block = system.get("recovery", {})
        if not isinstance(block, dict):
            block = {}

        raw = dict(conf_raw) if conf_ok else {}
        raw.update(block)
        if block:
            reason = "settings.json parsed; system.recovery applied"
        elif conf_ok:
            reason = (
                "settings.json parsed; no system.recovery block, "
                "using installer fallback values"
            )
        else:
            reason = "settings.json parsed; no recovery block or fallback config"
        return _merge(raw, CONFIG_RUNG_SETTINGS, reason)
    except Exception as exc:
        settings_error = f"{type(exc).__name__}: {exc}"

    if conf_ok:
        return _merge(
            conf_raw,
            CONFIG_RUNG_CONF,
            f"settings.json unusable ({settings_error}); using {conf_path}",
        )

    return _merge(
        {},
        CONFIG_RUNG_DEFAULTS,
        f"settings.json unusable ({settings_error}); "
        f"{conf_path} unusable ({conf_error}); using built-in defaults",
    )


# ---------------------------------------------------------------------------
# 4.5 Write discipline
# ---------------------------------------------------------------------------

def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    """Temp file in the same directory, fsync, os.replace, fsync the directory.

    The directory fsync is what makes the rename durable across power loss --
    the normal way this camera is switched off.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def backup_paths(name: str, backup_dir: Path = BACKUP_DIR) -> list[Path]:
    """Existing backups for *name*, oldest first."""
    try:
        found = [
            p for p in Path(backup_dir).iterdir()
            if p.name.startswith(f"{name}.") and p.name.endswith(".bak")
        ]
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name)


def prune_backups(name: str, backup_dir: Path = BACKUP_DIR, keep: int = BACKUP_KEEP):
    """Keep at most *keep* backups, and never the oldest one.

    The oldest backup is the pristine pre-Cinemate original -- the thing an
    operator wants after ten bad edits in a row. So retention is "the oldest,
    plus the keep-1 most recent"; pruning happens in the middle.
    """
    existing = backup_paths(name, backup_dir)
    if len(existing) <= keep:
        return []

    oldest, rest = existing[0], existing[1:]
    survivors = rest[-(keep - 1):] if keep > 1 else []
    doomed = [p for p in rest if p not in survivors]

    removed = []
    for path in doomed:
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            log.warning("Could not prune backup %s: %s", path, exc)
    log.info("Pruned %d backup(s) of %s, kept oldest %s", len(removed), name, oldest.name)
    return removed


def backup_file(
    path: Path, backup_dir: Path = BACKUP_DIR, keep: int = BACKUP_KEEP
) -> Path | None:
    """Copy *path* into the backup directory. Returns the backup path.

    Returns None when the source does not exist -- writing a file that was
    never there is legitimate and must not be blocked by a failed backup.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        log.info("No backup taken for %s: %s", path, exc)
        return None

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = utc_stamp()
    target = backup_dir / f"{path.name}.{stamp}.bak"
    counter = 1
    while target.exists():  # two writes inside one second
        target = backup_dir / f"{path.name}.{stamp}-{counter}.bak"
        counter += 1

    atomic_write_bytes(target, data, mode=0o600)
    prune_backups(path.name, backup_dir, keep)
    return target


def write_config_file(
    path: Path, text: str, backup_dir: Path = BACKUP_DIR, keep: int = BACKUP_KEEP
) -> Path | None:
    """Back up, then atomically replace. The order is not negotiable."""
    backup = backup_file(path, backup_dir, keep)
    atomic_write_bytes(Path(path), text.encode("utf-8"))
    return backup


# ---------------------------------------------------------------------------
# 4.4 Settings validation ladder
# ---------------------------------------------------------------------------

class Validation(NamedTuple):
    ok: bool
    rung: int
    message: str
    validated: bool   # False => rung 3 fired; the write is unverified


_INTERPRETER_VALIDATOR = """
import sys
sys.path.insert(0, sys.argv[1])
from module.config_loader import SettingsLoadError, load_settings
try:
    load_settings(sys.argv[2])
except SettingsLoadError as exc:
    sys.stdout.write(exc.format_for_cli(use_color=False))
    sys.exit(2)
except Exception as exc:
    sys.stdout.write("%s: %s" % (type(exc).__name__, exc))
    sys.exit(3)
sys.exit(0)
"""


def validate_settings_text(
    text: str,
    *,
    python_bin: Path = CINEMATE_PYTHON,
    src_dir: Path = CINEMATE_SRC,
    runner: Callable = subprocess.run,
) -> Validation:
    """Validate candidate settings.json through two independent rungs.

    1. CineMate's own config_loader gives the same detailed error the main
       process would report.
    2. If that interpreter/import path is unavailable, stdlib json validates
       syntax and requires the same top-level object shape.

    This strict-JSON recovery path never
    accepts comments/trailing commas and never writes malformed JSON merely
    because the main runtime is unavailable.
    """
    if Path(python_bin).exists() and Path(src_dir).exists():
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(text)
                tmp_path = tmp.name
            proc = runner(
                [str(python_bin), "-c", _INTERPRETER_VALIDATOR, str(src_dir), tmp_path],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if proc.returncode == 0:
                return Validation(True, VALIDATE_RUNG_INTERPRETER, "Valid.", True)
            if proc.returncode == 2:
                return Validation(
                    False,
                    VALIDATE_RUNG_INTERPRETER,
                    proc.stdout.strip() or "Invalid.",
                    True,
                )
            log.warning(
                "interpreter validator unusable (rc=%s): %s",
                proc.returncode,
                (proc.stderr or proc.stdout)[:400],
            )
        except Exception as exc:
            log.warning("interpreter validation rung unavailable: %s", exc)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("top level must be a JSON object")
        return Validation(
            True,
            VALIDATE_RUNG_STDLIB,
            "Valid (checked with Python stdlib JSON; CineMate validator unavailable).",
            True,
        )
    except Exception as exc:
        return Validation(
            False,
            VALIDATE_RUNG_STDLIB,
            f"{type(exc).__name__}: {exc}",
            True,
        )


# ---------------------------------------------------------------------------
# 4.6 config.txt confirm-or-revert
# ---------------------------------------------------------------------------

class Pending(NamedTuple):
    backup: str
    target: str
    armed_at: float
    timeout_s: int


def read_pending(path: Path | None = None) -> Pending | None:
    # Resolved at call time, not bound at def time, so the module constant
    # stays overridable (tests, and any future relocation of the state dir).
    path = Path(path) if path is not None else PENDING_PATH
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return Pending(
            backup=str(raw["backup"]),
            target=str(raw["target"]),
            armed_at=float(raw["armed_at"]),
            timeout_s=int(raw["timeout_s"]),
        )
    except Exception:
        return None


def arm_pending(
    backup: Path, target: Path, timeout_s: int,
    path: Path = PENDING_PATH, *, now: Callable[[], float] = time.time,
) -> Pending:
    """Record that a config.txt write is awaiting confirmation."""
    pending = Pending(str(backup), str(target), float(now()), int(timeout_s))
    atomic_write_bytes(
        Path(path), (json.dumps(pending._asdict(), indent=2) + "\n").encode("utf-8")
    )
    log.warning("config.txt change armed; confirm within %ss or it reverts", timeout_s)
    return pending


def clear_pending(path: Path = PENDING_PATH) -> bool:
    try:
        Path(path).unlink()
        log.info("config.txt change confirmed; pending marker cleared")
        return True
    except OSError:
        return False


def pending_remaining(pending: Pending, *, now: Callable[[], float] = time.time) -> float:
    return max(0.0, pending.armed_at + pending.timeout_s - now())


def revert_pending(
    pending: Pending,
    path: Path = PENDING_PATH,
    *,
    copy: Callable = shutil.copyfile,
    reboot: Callable = None,
    clear: Callable = None,
) -> bool:
    """Restore the backup, clear the marker, reboot.

    This recovers a boot that *succeeds but is broken* -- no camera, no HDMI,
    no network. It cannot recover a Pi that never reaches userspace; for that
    the only fallback is pulling the SD card (docs/recovery-console.md).
    """
    clear = clear or (lambda: clear_pending(path))
    reboot = reboot or (lambda: subprocess.run(["reboot"], check=False))

    restored = False
    try:
        copy(pending.backup, pending.target)
        restored = True
        log.error("config.txt was not confirmed in time; restored %s", pending.backup)
    except Exception as exc:
        log.error("Could not restore %s over %s: %s",
                  pending.backup, pending.target, exc)
    clear()
    reboot()
    return restored


# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------

class ServiceError(ValueError):
    pass


def systemctl(
    action: str, service: str, *, runner: Callable = subprocess.run
) -> subprocess.CompletedProcess:
    """Run one allowlisted systemctl action. Never interpolates free-form input."""
    if service not in ALLOWED_SERVICES:
        raise ServiceError(f"service not allowed: {service!r}")
    if action not in ALLOWED_ACTIONS:
        raise ServiceError(f"action not allowed: {action!r}")
    if action == "stop" and service in PROTECTED_SERVICES:
        raise ServiceError(
            f"{service} may not be stopped from the recovery console -- "
            "it is the operator's only way back in"
        )
    cmd = ["systemctl", action, f"{service}.service"]
    try:
        return runner(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        # No systemd (or it is unreachable). Report it as a failed command
        # rather than a 500: the operator still needs the rest of the page.
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


def service_state(service: str, *, runner: Callable = subprocess.run) -> str:
    if service not in ALLOWED_SERVICES:
        raise ServiceError(f"service not allowed: {service!r}")
    try:
        proc = runner(
            ["systemctl", "is-active", f"{service}.service"],
            capture_output=True, text=True, check=False,
        )
        return (proc.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def journal_tail(
    service: str, lines: int = DEFAULT_LOG_LINES, *, runner: Callable = subprocess.run
) -> str:
    if service not in ALLOWED_SERVICES:
        raise ServiceError(f"service not allowed: {service!r}")
    lines = max(1, min(int(lines), MAX_LOG_LINES))
    try:
        proc = runner(
            ["journalctl", "-u", f"{service}.service", "-n", str(lines), "--no-pager"],
            capture_output=True, text=True, check=False,
        )
        return proc.stdout or proc.stderr or "(no output)"
    except Exception as exc:
        return f"(journalctl unavailable: {exc})"


# ---------------------------------------------------------------------------
# ANSI -> HTML
# ---------------------------------------------------------------------------

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_SGR_COLORS = {
    30: "#000000", 31: "#cc0000", 32: "#4e9a06", 33: "#c4a000",
    34: "#3465a4", 35: "#75507b", 36: "#06989a", 37: "#d3d7cf",
    90: "#555753", 91: "#ef2929", 92: "#8ae234", 93: "#fce94f",
    94: "#729fcf", 95: "#ad7fa8", 96: "#34e2e2", 97: "#eeeeec",
}


def ansi_to_html(text: str) -> str:
    """Render the tty1 startup-failure block as HTML, colours intact.

    main.py writes that block with SGR escapes (config_loader.ANSI_RED etc).
    Showing it verbatim is the point of /why: the operator sees the same text
    the camera would have shown on the monitor it is not connected to.
    """
    out: list[str] = []
    open_spans = 0
    pos = 0

    for match in _SGR_RE.finditer(text):
        out.append(html.escape(text[pos:match.start()]))
        pos = match.end()

        codes = [int(c) for c in match.group(1).split(";") if c.isdigit()]
        if not codes or 0 in codes:
            out.append("</span>" * open_spans)
            open_spans = 0
            codes = [c for c in codes if c != 0]
            if not codes:
                continue

        styles = []
        for code in codes:
            if code == 1:
                styles.append("font-weight:bold")
            elif code in _SGR_COLORS:
                styles.append(f"color:{_SGR_COLORS[code]}")
        if styles:
            out.append(f'<span style="{";".join(styles)}">')
            open_spans += 1

    out.append(html.escape(text[pos:]))
    out.append("</span>" * open_spans)
    return "".join(out)


# ---------------------------------------------------------------------------
# System facts for the dashboard
# ---------------------------------------------------------------------------

def read_hotspot_state(path: Path | None = None) -> dict | None:
    path = Path(path) if path is not None else HOTSPOT_STATE
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def read_uptime(path: str = "/proc/uptime") -> str:
    try:
        seconds = float(Path(path).read_text().split()[0])
    except Exception:
        return "unknown"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def read_disk_free(path: str = "/") -> str:
    try:
        usage = shutil.disk_usage(path)
    except Exception:
        return "unknown"
    free_gb = usage.free / (1024 ** 3)
    pct = 100.0 * usage.free / usage.total if usage.total else 0.0
    return f"{free_gb:.1f} GB free ({pct:.0f}%)"


def read_failure_block(path: Path | None = None) -> str | None:
    """The persisted tty1 failure block, or None when Cinemate started clean."""
    path = Path(path) if path is not None else FAILURE_FILE
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root {
  color-scheme: light dark;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --panel-soft: #eef2f5;
  --text: #18202a;
  --muted: #65707d;
  --border: #d7dde4;
  --accent: #087ea4;
  --accent-strong: #066782;
  --good: #2b7a0b;
  --bad: #b42318;
  --warn: #9a6700;
  --shadow: 0 8px 28px #0f172a12;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #11151b;
    --panel: #1a2028;
    --panel-soft: #202833;
    --text: #edf1f5;
    --muted: #aab3be;
    --border: #343e4b;
    --accent: #42b8df;
    --accent-strong: #75cbea;
    --good: #7ccf5b;
    --bad: #ff7b72;
    --warn: #e3b341;
    --shadow: 0 10px 34px #00000030;
  }
}
* { box-sizing: border-box; }
html { min-height: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  line-height: 1.45;
}
a { color: var(--accent); text-underline-offset: .16em; }
a:hover { color: var(--accent-strong); }
nav a.active {
  border-color: var(--accent);
  background: var(--panel-soft);
  color: var(--text);
}
.page-shell {
  width: min(calc(100% - 2rem), 112rem);
  margin: 0 auto;
  padding: clamp(.75rem, 1.5vw, 1.5rem);
}
.topbar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 1rem 2rem;
  margin-bottom: 1rem;
}
.brand h1 { margin: 0; font-size: clamp(1.25rem, 2vw, 1.7rem); line-height: 1.15; }
.brand p { margin: .3rem 0 0; color: var(--muted); font-size: .88rem; }
nav { display: flex; flex-wrap: wrap; gap: .35rem; justify-content: flex-end; }
nav a {
  display: inline-flex;
  align-items: center;
  min-height: 2.5rem;
  padding: .5rem .75rem;
  border: 1px solid var(--border);
  border-radius: .55rem;
  background: var(--panel);
  text-decoration: none;
  font-weight: 600;
}
main { min-width: 0; }
.recovery-form {
  display: grid;
  gap: 1rem;
  min-width: 0;
}
h2 { margin: 0 0 .65rem; font-size: 1.05rem; }
.section { min-width: 0; }
.card, .auth-panel, .banner {
  border: 1px solid var(--border);
  border-radius: .75rem;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.card { padding: 1rem; }
.auth-panel {
  display: grid;
  grid-template-columns: minmax(16rem, 1fr) minmax(19rem, 23rem);
  align-items: center;
  gap: .75rem 1.25rem;
  padding: .78rem 1rem;
}
.auth-copy strong { display: block; }
.auth-copy span { display: block; margin-top: .18rem; color: var(--muted); font-size: .82rem; }
.auth-control label { display: block; font-size: .78rem; color: var(--muted); margin-bottom: .25rem; }
input[type="password"] {
  width: 100%;
  min-height: 2.6rem;
  padding: .5rem .65rem;
  border: 1px solid var(--border);
  border-radius: .5rem;
  background: var(--panel-soft);
  color: var(--text);
  font: inherit;
}
.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.15fr) minmax(20rem, 1fr);
  gap: .9rem;
  align-items: start;
}
.service-list { overflow: hidden; padding: 0; }
.service-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: .75rem 1rem;
  min-height: 4.15rem;
  padding: .7rem .85rem;
  border-bottom: 1px solid var(--border);
}
.service-row:last-child { border-bottom: 0; }
.service-row button {
  min-width: 7rem;
  min-height: 2.35rem;
  padding: .4rem .75rem;
}
.service-line { display: flex; align-items: start; justify-content: space-between; gap: .75rem; }
.service-name { min-width: 0; overflow-wrap: anywhere; font-weight: 700; }
.eyebrow {
  display: block;
  margin-bottom: .18rem;
  color: var(--muted);
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.state-pill {
  flex: 0 0 auto;
  padding: .24rem .5rem;
  border-radius: 999px;
  background: var(--panel-soft);
  font-size: .78rem;
  font-weight: 800;
}
.ok { color: var(--good); }
.bad { color: var(--bad); }
.system-panel { padding: .25rem 1rem; }
.system-fact {
  padding: .85rem 0;
  border-bottom: 1px solid var(--border);
}
.system-fact:last-child { border-bottom: 0; }
.fact { min-width: 0; }
.fact-value { font-size: 1.08rem; font-weight: 750; overflow-wrap: anywhere; }
.fact-detail { margin-top: .35rem; color: var(--muted); font-size: .82rem; overflow-wrap: anywhere; }
button {
  min-height: 2.7rem;
  padding: .55rem .9rem;
  border: 1px solid var(--border);
  border-radius: .55rem;
  background: var(--panel-soft);
  color: var(--text);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}
button:hover { border-color: var(--accent); }
button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 3px solid var(--accent);
  outline-offset: 2px;
}
.actions { display: flex; flex-wrap: wrap; gap: .55rem; margin-top: .75rem; }
.banner { padding: .85rem 1rem; box-shadow: none; }
.red { background: #b4231814; border-color: var(--bad); }
.amber { background: #9a670014; border-color: var(--warn); }
.green { background: #2b7a0b14; border-color: var(--good); }
pre {
  max-width: 100%;
  margin: 0;
  padding: 1rem;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: .65rem;
  background: var(--panel);
  font-size: .82rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
textarea {
  width: 100%;
  min-height: clamp(22rem, 62vh, 48rem);
  resize: vertical;
  padding: .8rem;
  border: 1px solid var(--border);
  border-radius: .65rem;
  background: var(--panel);
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .82rem;
  line-height: 1.45;
}
.recovery-strip {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .65rem;
}
.recovery-item {
  padding: .68rem .8rem;
  border: 1px solid var(--border);
  border-radius: .6rem;
  background: var(--panel);
}
.recovery-item strong { display: block; margin-top: .12rem; }
.log-links { display: flex; flex-wrap: wrap; gap: .45rem; }
.log-links a { padding: .42rem .6rem; border: 1px solid var(--border); border-radius: .5rem; text-decoration: none; }
.muted { color: var(--muted); font-size: .85rem; }
footer { margin-top: 1rem; padding-top: .75rem; border-top: 1px solid var(--border); }
@media (max-width: 900px) {
  .topbar { align-items: start; flex-direction: column; }
  nav { justify-content: flex-start; }
  .dashboard-grid { grid-template-columns: 1fr; }
  .service-row { grid-template-columns: minmax(0, 1fr) auto; }
  .service-row button { grid-column: 1 / -1; width: 100%; }
  .recovery-strip { grid-template-columns: 1fr 1fr; }
  .auth-panel { grid-template-columns: 1fr; }
  input[type="password"] { width: 100%; }
}
@media (max-width: 620px) {
  .page-shell { width: 100%; padding: .7rem; }
  nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; }
  nav a { justify-content: center; text-align: center; }
  .service-row {
    grid-template-columns: minmax(0, 1fr) auto;
    min-height: 0;
    padding: .8rem;
  }
  .service-row button { grid-column: 1 / -1; width: 100%; }
  .recovery-strip { grid-template-columns: 1fr; }
  .actions button { width: 100%; }
  .actions { display: grid; grid-template-columns: 1fr; }
  .card, .auth-panel, .banner { border-radius: .6rem; }
}
@media (max-height: 520px) and (orientation: landscape) {
  .page-shell { padding-top: .55rem; padding-bottom: .55rem; }
  .topbar { margin-bottom: .6rem; }
  .brand p { display: none; }
  nav a { min-height: 2.2rem; padding-top: .35rem; padding-bottom: .35rem; }
  .recovery-form { gap: .65rem; }
  textarea { min-height: 68vh; }
}
"""


def nav_active(active: bool) -> str:
    return " class='active' aria-current='page'" if active else ""


def page(
    title: str,
    body: str,
    *,
    banner: str = "",
    cfg: ConsoleConfig | None = None,
) -> bytes:
    content = f"{banner}{body}"
    if cfg is not None:
        content = (
            "<form class='recovery-form' method='post'>"
            f"{token_field(cfg)}{content}</form>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        "<div class='page-shell'>"
        "<header class='topbar'><div class='brand'>"
        "<h1>Cinemate recovery console</h1>"
        "<p>Independent diagnostics and repair surface</p></div>"
        "<nav aria-label='Recovery navigation'>"
        f"<a href='/'{nav_active(title == 'Status')}>Status</a>"
        f"<a href='/why'{nav_active(title == 'Why it failed')}>Why it failed</a>"
        f"<a href='/log'{nav_active(title.startswith('Log:'))}>Log</a>"
        f"<a href='/edit/settings'{nav_active(title == 'Edit settings.json')}>settings.json</a></nav>"
        "</header><main>"
        f"{content}"
        "</main><footer>"
        f"<span class='muted'>{html.escape(utc_now())} &middot; "
        "recovery console, stdlib only</span>"
        "</footer></div></body></html>"
    ).encode("utf-8")


def token_field(cfg: ConsoleConfig) -> str:
    if not cfg.token:
        return (
            "<div class='banner red'><strong>Mutating actions locked.</strong> "
            "No recovery token is configured.</div>"
        )
    return (
        "<section class='auth-panel' aria-label='Recovery authorization'>"
        "<div class='auth-copy'><strong>Privileged actions</strong>"
        "<span>Enter the recovery token once for this page. It is not stored; "
        "navigation or reload clears it.</span></div>"
        "<div class='auth-control'><label for='recovery-token'>Access token</label>"
        "<input id='recovery-token' type='password' name='token' "
        "autocomplete='off' autocapitalize='none' spellcheck='false'></div>"
        "</section>"
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class RecoveryHandler(http.server.BaseHTTPRequestHandler):
    server_version = "cinemate-recovery"
    protocol_version = "HTTP/1.1"

    # Injected by make_server()
    config: ConsoleConfig = None
    # staticmethod, not a bare assignment: a plain function stored on a class
    # is a descriptor, so `self.runner(cmd)` would silently pass the handler
    # as subprocess.run's first argument. Found by the live smoke test, not
    # by the unit tests -- those call the module functions directly.
    runner = staticmethod(subprocess.run)

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def _send(self, body: bytes, status: int = 200, ctype="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_form(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def _authorised(self, form: dict, query: dict) -> bool:
        """Mutating routes only. Read-only routes stay open so a locked-out
        operator can always still diagnose (plan section 8)."""
        expected = self.config.token
        if not expected:
            return False
        supplied = (
            form.get("token")
            or query.get("token", [""])[0]
            or self.headers.get("X-Auth-Token", "")
        )
        return hmac.compare_digest(str(supplied), str(expected))

    def _audit(self, what: str):
        log.warning("ACTION %s from %s", what, self.client_address[0])

    def _banner(self) -> str:
        pending = read_pending()
        if not pending:
            return ""
        left = int(pending_remaining(pending))
        return (
            "<div class='banner red'><strong>config.txt change awaiting "
            f"confirmation.</strong><br>Reverting in {left}s and rebooting "
            "unless you confirm."
            "<div class='actions'>"
            "<button type='submit' formaction='/confirm-config'>KEEP THIS CONFIG</button>"
            "</div></div>"
        )

    # -- routing -----------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = url.path.rstrip("/") or "/"
        try:
            if route == "/health":
                return self._send(b"ok\n", ctype="text/plain; charset=utf-8")
            if route == "/":
                return self._send(self.view_status())
            if route == "/why":
                return self._send(self.view_why())
            if route == "/log":
                return self._send(self.view_log(query))
            if route == "/edit/settings":
                return self._send(self.view_edit_settings())
            if route == "/edit/config":
                return self._send(self.view_edit_config())
            return self._send(page("Not found", "<p>No such page.</p>"), 404)
        except Exception:
            log.exception("GET %s failed", self.path)
            return self._send(page("Error", "<p>Internal error; see journal.</p>"), 500)

    def do_POST(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        form = self._read_form()
        route = url.path.rstrip("/") or "/"

        if not self._authorised(form, query):
            self._audit(f"DENIED {route} (bad token)")
            return self._send(page("Denied", "<p>Invalid access token.</p>"), 403)

        try:
            if route.startswith("/service/"):
                return self._send(self.act_service(route))
            if route == "/edit/settings":
                return self._send(self.act_edit_settings(form))
            if route == "/edit/config":
                return self._send(self.act_edit_config(form))
            if route == "/confirm-config":
                return self._send(self.act_confirm_config())
            return self._send(page("Not found", "<p>No such action.</p>"), 404)
        except ServiceError as exc:
            self._audit(f"REFUSED {route}: {exc}")
            return self._send(page("Refused", f"<p>{html.escape(str(exc))}</p>"), 400)
        except Exception:
            log.exception("POST %s failed", self.path)
            return self._send(page("Error", "<p>Internal error; see journal.</p>"), 500)

    # -- views -------------------------------------------------------------

    def view_status(self) -> bytes:
        service_rows = []
        for svc in ALLOWED_SERVICES:
            state = service_state(svc, runner=self.runner)
            css = "ok" if state == "active" else "bad"
            service_rows.append(
                "<div class='service-row'>"
                "<div><span class='eyebrow'>Service</span>"
                f"<div class='service-name'>{html.escape(svc)}</div></div>"
                f"<span class='state-pill {css}'>{html.escape(state)}</span>"
                f"<button type='submit' formaction='/service/{svc}/restart'>Restart</button>"
                "</div>"
            )

        hotspot = read_hotspot_state()
        if hotspot:
            hotspot_value = html.escape(str(hotspot.get("ssid", "?")))
            hotspot_detail = (
                f"rung {html.escape(str(hotspot.get('rung', '?')))} · "
                f"{html.escape(str(hotspot.get('rung_name', '?')))}"
            )
        else:
            hotspot_value = "Unavailable"
            hotspot_detail = "wifi-hotspot.service has not written state yet"

        failure = read_failure_block()
        if failure:
            failure_value = "<a href='/why'>Recorded — inspect details</a>"
            failure_detail = "Cinemate persisted a startup failure"
        else:
            failure_value = "None"
            failure_detail = "No recorded startup failure"

        body = (
            "<section class='recovery-strip' aria-label='Recovery state'>"
            "<div class='recovery-item'><span class='eyebrow'>Hotspot state</span>"
            f"<strong>{hotspot_value}</strong>"
            f"<div class='fact-detail'>{hotspot_detail}</div></div>"
            "<div class='recovery-item'><span class='eyebrow'>Startup failure</span>"
            f"<strong>{failure_value}</strong>"
            f"<div class='fact-detail'>{failure_detail}</div></div>"
            "</section>"
            "<section class='dashboard-grid'>"
            "<div class='section'><h2>Services</h2>"
            f"<div class='card service-list'>{''.join(service_rows)}</div></div>"
            "<div class='section'><h2>System</h2>"
            "<div class='card system-panel'>"
            "<div class='system-fact'><span class='eyebrow'>Uptime</span>"
            f"<div class='fact-value'>{html.escape(read_uptime())}</div></div>"
            "<div class='system-fact'><span class='eyebrow'>System disk</span>"
            f"<div class='fact-value'>{html.escape(read_disk_free())}</div></div>"
            "<div class='system-fact'><span class='eyebrow'>Config rung</span>"
            f"<div class='fact-value'>{self.config.rung}</div>"
            f"<div class='fact-detail'>{html.escape(self.config.reason)}</div></div>"
            "</div></div></section>"
        )
        if self.config.allow_config_txt:
            body += "<div class='card'><a href='/edit/config'>Edit config.txt &rarr;</a></div>"
        return page("Status", body, banner=self._banner(), cfg=self.config)

    def view_why(self) -> bytes:
        block = read_failure_block()
        if block is None:
            body = (
                "<div class='card'><p>No startup failure recorded. Cinemate either "
                "started cleanly or has not run since the file was last cleared.</p></div>"
            )
        else:
            body = f"<pre>{ansi_to_html(block)}</pre>"
        return page("Why it failed", body, banner=self._banner(), cfg=self.config)

    def view_log(self, query: dict) -> bytes:
        service = query.get("service", ["cinemate-autostart"])[0]
        if service not in ALLOWED_SERVICES:
            service = "cinemate-autostart"
        try:
            lines = int(query.get("n", [DEFAULT_LOG_LINES])[0])
        except ValueError:
            lines = DEFAULT_LOG_LINES
        log_text = journal_tail(service, lines, runner=self.runner)
        links = "".join(
            f"<a href='/log?service={s}'>{html.escape(s)}</a>" for s in ALLOWED_SERVICES
        )
        body = f"<div class='log-links'>{links}</div><pre>{html.escape(log_text)}</pre>"
        return page(f"Log: {service}", body, banner=self._banner(), cfg=self.config)

    def view_edit_settings(self, message: str = "") -> bytes:
        try:
            settings_text = SETTINGS_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            settings_text = ""
            message += (
                f"<div class='banner amber'>Could not read {SETTINGS_PATH}: "
                f"{html.escape(str(exc))}</div>"
            )
        body = (
            f"{message}"
            "<section class='section'><h2>settings.json</h2>"
            f"<textarea name='content' spellcheck='false'>{html.escape(settings_text)}</textarea>"
            "<div class='actions'>"
            "<button type='submit' formaction='/edit/settings'>Save</button>"
            "<button type='submit' formaction='/edit/settings' name='restart' value='1'>"
            "Save and restart Cinemate</button></div></section>"
        )
        return page("Edit settings.json", body, banner=self._banner(), cfg=self.config)

    def view_edit_config(self, message: str = "") -> bytes:
        if not self.config.allow_config_txt:
            return page(
                "Disabled",
                "<div class='card'><p>config.txt editing is disabled. Set "
                "<code>system.recovery.allow_config_txt</code> to true in "
                "settings.json to enable it.</p></div>",
                cfg=self.config,
            )
        try:
            config_text = CONFIG_TXT.read_text(encoding="utf-8")
        except OSError as exc:
            config_text = ""
            message += (
                f"<div class='banner amber'>Could not read {CONFIG_TXT}: "
                f"{html.escape(str(exc))}</div>"
            )
        body = (
            "<div class='banner red'><strong>A bad config.txt can make this Pi "
            "unbootable, and nothing running on the Pi can recover that.</strong>"
            "<br>If it will not boot: power off, pull the SD card, mount the FAT "
            "boot partition on any Mac or Windows machine, and restore config.txt "
            f"from a <code>.bak</code> in <code>{BACKUP_DIR}</code>.<br>"
            f"After saving you have {self.config.config_confirm_timeout_s}s to "
            "confirm, or the change reverts and the Pi reboots.</div>"
            f"{message}"
            "<section class='section'><h2>config.txt</h2>"
            f"<textarea name='content' spellcheck='false'>{html.escape(config_text)}</textarea>"
            "<div class='actions'><button type='submit' formaction='/edit/config'>"
            "Save and arm revert</button></div></section>"
        )
        return page("Edit config.txt", body, banner=self._banner(), cfg=self.config)

    # -- actions -----------------------------------------------------------

    def act_service(self, route: str) -> bytes:
        parts = [p for p in route.split("/") if p]
        if len(parts) != 3:
            raise ServiceError("malformed service action")
        _, service, action = parts
        self._audit(f"systemctl {action} {service}")
        proc = systemctl(action, service, runner=self.runner)

        if service == "wifi-hotspot" and action == "restart":
            self._arm_hotspot_rearm()

        detail = (proc.stderr or proc.stdout or "").strip()
        css = "green" if proc.returncode == 0 else "red"
        body = (
            f"<div class='banner {css}'>systemctl {html.escape(action)} "
            f"{html.escape(service)} &rarr; exit {proc.returncode}</div>"
            + (f"<pre>{html.escape(detail)}</pre>" if detail else "")
            + "<p><a href='/'>Back to status</a></p>"
        )
        return page("Service", body, banner=self._banner(), cfg=self.config)

    def _arm_hotspot_rearm(self):
        """Restore the AP if a hotspot restart does not bring it back (4.7)."""
        def rearm():
            time.sleep(HOTSPOT_REARM_S)
            state = service_state("wifi-hotspot", runner=self.runner)
            if state != "active":
                log.error("Hotspot did not return after restart; re-arming")
                systemctl("start", "wifi-hotspot", runner=self.runner)

        threading.Thread(target=rearm, daemon=True).start()

    def act_edit_settings(self, form: dict) -> bytes:
        content = form.get("content", "")
        result = validate_settings_text(content, runner=self.runner)

        if not result.ok:
            msg = (f"<div class='banner red'><strong>Not saved.</strong> "
                   f"Rung {result.rung} validation failed:"
                   f"<pre>{html.escape(result.message)}</pre></div>")
            return self.view_edit_settings(msg)

        self._audit(f"write {SETTINGS_PATH} (rung {result.rung})")
        backup = write_config_file(SETTINGS_PATH, content)
        css = "green" if result.validated else "amber"
        msg = (f"<div class='banner {css}'>Saved. {html.escape(result.message)}<br>"
               f"<span class='muted'>Backup: {html.escape(str(backup))}</span></div>")

        if form.get("restart"):
            self._audit("systemctl restart cinemate-autostart (after settings save)")
            proc = systemctl("restart", "cinemate-autostart", runner=self.runner)
            msg += (f"<div class='banner green'>Restart requested &rarr; exit "
                    f"{proc.returncode}</div>")
        return self.view_edit_settings(msg)

    def act_edit_config(self, form: dict) -> bytes:
        if not self.config.allow_config_txt:
            raise ServiceError("config.txt editing is disabled")

        content = form.get("content", "")
        self._audit(f"write {CONFIG_TXT}")
        backup = write_config_file(CONFIG_TXT, content)
        if backup is None:
            return self.view_edit_config(
                "<div class='banner red'>Refused: could not back up config.txt "
                "first, and this edit is not safe without a backup.</div>"
            )
        arm_pending(backup, CONFIG_TXT, self.config.config_confirm_timeout_s)
        start_revert_watchdog(self.config)
        return self.view_edit_config(
            f"<div class='banner amber'>Saved and armed. Backup: "
            f"{html.escape(str(backup))}. Reboot to apply, then confirm.</div>"
        )

    def act_confirm_config(self) -> bytes:
        self._audit("confirm config.txt")
        cleared = clear_pending()
        body = ("<div class='banner green'>Configuration kept.</div>"
                if cleared else
                "<div class='banner amber'>Nothing was pending.</div>")
        return page("Confirmed", body + "<p><a href='/'>Back to status</a></p>", cfg=self.config)


# ---------------------------------------------------------------------------
# Revert watchdog
# ---------------------------------------------------------------------------

_watchdog_started = threading.Event()


def start_revert_watchdog(cfg: ConsoleConfig, *, path: Path = PENDING_PATH):
    """Countdown for an unconfirmed config.txt change.

    Deliberately NOT a second systemd unit (plan section 7): it lives in this
    process and inherits its Restart=always, so a crash re-reads the marker on
    the way back up and the countdown resumes.
    """
    if _watchdog_started.is_set():
        return
    pending = read_pending(path)
    if not pending:
        return
    _watchdog_started.set()

    def watch():
        try:
            while True:
                current = read_pending(path)
                if current is None:
                    log.info("config.txt change confirmed; watchdog standing down")
                    return
                if pending_remaining(current) <= 0:
                    revert_pending(current, path)
                    return
                time.sleep(1)
        finally:
            _watchdog_started.clear()

    threading.Thread(target=watch, daemon=True).start()
    log.warning("config.txt revert watchdog armed (%ss)", pending.timeout_s)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

class RecoveryHTTPServer(http.server.ThreadingHTTPServer):
    """Threaded HTTP server that ignores only routine client disconnect noise."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            log.debug("Client disconnected early: %s", client_address)
            return
        super().handle_error(request, client_address)


def make_server(cfg: ConsoleConfig, *, bind: str = "0.0.0.0"):
    handler = type("BoundRecoveryHandler", (RecoveryHandler,), {"config": cfg})
    server = RecoveryHTTPServer((bind, cfg.port), handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cinemate recovery console")
    parser.add_argument("--port", type=int, help="override the configured port")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--check", action="store_true",
                        help="resolve config, print it, and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s [recovery] %(levelname)s: %(message)s",
    )

    cfg = load_config()
    if args.port:
        cfg = cfg._replace(port=args.port)

    if args.check:
        print(json.dumps(cfg._asdict(), indent=2))
        return 0

    log.info("Config rung %d: %s", cfg.rung, cfg.reason)
    if not cfg.enabled:
        log.warning("Recovery console disabled in configuration; idling")
        # Idle rather than exit: exiting under Restart=always is a crash loop,
        # and the operator may re-enable it by editing settings.json.
        while True:
            time.sleep(3600)

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create %s: %s", STATE_DIR, exc)

    start_revert_watchdog(cfg)

    server = make_server(cfg, bind=args.bind)
    log.info("Listening on %s:%d (token %s, config.txt editing %s)",
             args.bind, cfg.port,
             "required" if cfg.token else "missing; mutations locked",
             "enabled" if cfg.allow_config_txt else "disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
