#!/usr/bin/env python3
"""Safely edit CineMate's strict-JSON settings file."""

from __future__ import annotations

import argparse
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from module.config_loader import SettingsLoadError, load_settings

DEFAULT_SETTINGS = SRC_DIR / "settings.json"
BACKUP_KEEP = 10


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def default_backup_dir() -> Path:
    state_root = Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
    )
    return state_root / "cinemate" / "settings-backups"


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


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
        tmp_name = None
        _fsync_directory(path.parent)
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def backup_paths(backup_dir: Path) -> list[Path]:
    try:
        return sorted(
            p
            for p in Path(backup_dir).iterdir()
            if p.name.startswith("settings.json.") and p.name.endswith(".bak")
        )
    except OSError:
        return []


def prune_backups(backup_dir: Path, keep: int = BACKUP_KEEP) -> None:
    existing = backup_paths(backup_dir)
    if len(existing) <= keep:
        return
    oldest, rest = existing[0], existing[1:]
    survivors = rest[-(keep - 1):] if keep > 1 else []
    for path in rest:
        if path in survivors:
            continue
        try:
            path.unlink()
        except OSError:
            pass


def backup_file(path: Path, backup_dir: Path, *, keep: int = BACKUP_KEEP) -> Path:
    data = Path(path).read_bytes()
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"settings.json.{utc_stamp()}.bak"
    atomic_write_bytes(backup, data, mode=0o600)
    prune_backups(backup_dir, keep)
    return backup


def editor_command(explicit: str | None = None) -> list[str]:
    raw = explicit or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    command = shlex.split(raw)
    if not command:
        raise ValueError("Editor command is empty")
    return command


def validate_candidate(path: Path) -> tuple[bool, str]:
    try:
        load_settings(path)
    except SettingsLoadError as exc:
        return False, exc.format_for_cli(use_color=sys.stdout.isatty())
    except Exception as exc:
        return (
            False,
            "CineMate validator failed unexpectedly; refusing to save.\n"
            f"{type(exc).__name__}: {exc}",
        )
    return True, "Valid strict JSON."


def _preserve_rejected_candidate(temp_path: Path, backup_dir: Path) -> Path | None:
    try:
        data = temp_path.read_bytes()
        rejected_dir = Path(backup_dir).parent / "rejected-settings"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        target = rejected_dir / f"settings.json.{utc_stamp()}.rejected"
        atomic_write_bytes(target, data, mode=0o600)
        return target
    except OSError:
        return None


def edit_settings(
    path: Path = DEFAULT_SETTINGS,
    *,
    backup_dir: Path | None = None,
    editor: str | None = None,
    runner: Callable = subprocess.run,
    input_fn: Callable[[str], str] = input,
    interactive_retry: bool = True,
    output: Callable[[str], None] = print,
) -> int:
    path = Path(path)
    backup_dir = Path(backup_dir) if backup_dir is not None else default_backup_dir()

    try:
        original = path.read_bytes()
        original_stat = path.stat()
    except OSError as exc:
        output(f"Cannot read {path}: {exc}")
        return 1

    if not os.access(path.parent, os.W_OK):
        output(
            f"Refusing to edit: {path.parent} is not writable by the current user. "
            "Fix ownership/permissions instead of running the editor as root."
        )
        return 1

    command = editor_command(editor)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=".settings-edit-",
            suffix=".json",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(original)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_path, stat.S_IMODE(original_stat.st_mode))

        while True:
            proc = runner([*command, str(tmp_path)], check=False)
            if proc.returncode != 0:
                output(f"Editor exited with status {proc.returncode}; live settings unchanged.")
                return proc.returncode or 1

            candidate = tmp_path.read_bytes()
            if candidate == original:
                output("No changes; live settings unchanged.")
                return 0

            ok, message = validate_candidate(tmp_path)
            if ok:
                break

            output("\nValidation failed. The live settings file was NOT changed.")
            output(message)
            if interactive_retry and sys.stdin.isatty():
                answer = input_fn("Press Enter to edit again, or type q to abort: ")
                if answer.strip().lower() not in {"q", "quit", "a", "abort"}:
                    continue

            rejected = _preserve_rejected_candidate(tmp_path, backup_dir)
            if rejected is not None:
                output(f"Rejected candidate preserved at: {rejected}")
            return 2

        try:
            current = path.read_bytes()
        except OSError as exc:
            output(f"Cannot re-read live settings before commit: {exc}")
            return 1

        if current != original:
            rejected = _preserve_rejected_candidate(tmp_path, backup_dir)
            output(
                "Refusing to overwrite settings.json because it changed while the "
                "editor was open. Re-run editsettings against the newer file."
            )
            if rejected is not None:
                output(f"Your candidate was preserved at: {rejected}")
            return 3

        try:
            backup = backup_file(path, backup_dir)
        except OSError as exc:
            output(f"Backup failed; live settings were NOT changed: {exc}")
            return 1

        if path.read_bytes() != original:
            rejected = _preserve_rejected_candidate(tmp_path, backup_dir)
            output(
                "Refusing to overwrite settings.json because it changed during "
                "the save operation. Live settings remain untouched."
            )
            if rejected is not None:
                output(f"Your candidate was preserved at: {rejected}")
            return 3

        with tmp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(tmp_path, stat.S_IMODE(original_stat.st_mode))
        os.replace(tmp_path, path)
        tmp_path = None
        _fsync_directory(path.parent)

        output(f"Saved {path}")
        output(f"Backup: {backup}")
        output("Restart CineMate for settings changes to take effect.")
        return 0
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Safely edit CineMate strict-JSON settings")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--editor")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args(argv)
    return edit_settings(args.path, backup_dir=args.backup_dir, editor=args.editor)


if __name__ == "__main__":
    raise SystemExit(main())
