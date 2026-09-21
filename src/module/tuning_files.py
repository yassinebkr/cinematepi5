"""Validation helpers for libcamera PiSP tuning-file overrides.

A configured custom tuning file must never be passed blindly to cinepi-raw.
A missing, malformed, or VC4/Pi-4 tuning file can make libcamera camera
registration fail even though camera discovery succeeded.  The caller can
therefore fall back to the auto-detected sensor tuning before launch.

This module deliberately depends only on the Python standard library so it can
be reused later by settings/UI code without importing the camera runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional


def tuning_json_problem(data: Any) -> Optional[str]:
    """Return None for a minimally valid PiSP v2 tuning document.

    The check is intentionally structural rather than sensor-specific.  A
    custom file may tune any sensor, but on the Pi 5/PiSP path it must declare
    target "pisp" and expose the v2 "algorithms" list.
    """
    if not isinstance(data, dict):
        return "top-level JSON value is not an object"

    target = data.get("target")
    if target != "pisp":
        return (
            f'target is "{target}", expected "pisp" '
            "(a Pi 4 / VC4 tuning cannot load on the Pi 5 PiSP pipeline)"
        )

    algorithms = data.get("algorithms")
    if not isinstance(algorithms, list):
        return 'no "algorithms" list (not a version 2 tuning file)'

    return None


def resolve_tuning_override(
    override: Mapping[str, Any] | None,
    repo_root: Path,
) -> tuple[Optional[Path], str]:
    """Resolve and validate a configured tuning override.

    Relative paths are interpreted relative to *repo_root*, not the process
    working directory.  The returned reason is suitable for a human-readable
    log message.
    """
    if not isinstance(override, Mapping):
        return None, "disabled"

    if not bool(override.get("enabled")):
        return None, "disabled"

    raw_path = override.get("path")
    if raw_path is None or not str(raw_path).strip():
        return None, "enabled but no path set"

    candidate = Path(str(raw_path).strip()).expanduser()
    resolved = candidate if candidate.is_absolute() else Path(repo_root) / candidate

    try:
        resolved = resolved.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return None, f"cannot resolve path: {exc}"

    if not resolved.is_file():
        return None, f"file not found: {resolved}"

    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, f"unreadable as UTF-8: {exc}"

    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"not valid JSON: {exc}"

    problem = tuning_json_problem(data)
    if problem:
        return None, problem

    return resolved, "ok"
