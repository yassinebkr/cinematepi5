"""Small helpers for degraded/no-camera runtime decisions."""

from __future__ import annotations

import json
from typing import Any


def camera_present_from_cameras_value(raw: Any) -> bool:
    """Return True only when the Redis cameras value contains a camera.

    CinePi writes the cameras key before returning from camera discovery.
    The normal serialized form is a JSON list.  Be conservative for malformed
    or missing values: degraded boot should not start camera-only work.
    """
    if raw is None:
        return False

    if isinstance(raw, (list, tuple)):
        return len(raw) > 0

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return False

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return False
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            return False
        return isinstance(value, list) and len(value) > 0

    return False
