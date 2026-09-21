#!/usr/bin/env python3
"""Show, create or rotate the CineMate settings-editor token."""

from __future__ import annotations

import argparse
import grp
import os
import secrets
import tempfile
from pathlib import Path

CONF_PATH = Path("/etc/cinemate-settings-editor.conf")


def read_token(path: Path = CONF_PATH) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc
    for raw in lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        if key.strip() == "token" and value.strip():
            return value.strip()
    raise RuntimeError(f"No token configured in {path}")


def _require_root() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("This operation requires root; rerun it with sudo.")


def write_token(token: str, *, path: Path = CONF_PATH, group: str = "pi") -> None:
    _require_root()
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError as exc:
        raise RuntimeError(f"Group {group!r} does not exist") from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".cinemate-settings-editor-", suffix=".conf.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("# CineMate settings editor authentication\n")
            handle.write("token=" + token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(tmp_name, 0, gid)
        os.chmod(tmp_name, 0o640)
        os.replace(tmp_name, path)
        tmp_name = ""
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def ensure(*, path: Path = CONF_PATH, group: str = "pi") -> tuple[str, bool]:
    _require_root()
    try:
        token = read_token(path)
        return token, False
    except RuntimeError:
        token = secrets.token_urlsafe(24)
        write_token(token, path=path, group=group)
        return token, True


def rotate(*, path: Path = CONF_PATH, group: str = "pi") -> str:
    token = secrets.token_urlsafe(24)
    write_token(token, path=path, group=group)
    return token


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=CONF_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show")

    p_ensure = sub.add_parser("ensure")
    p_ensure.add_argument("--group", default="pi")

    p_rotate = sub.add_parser("rotate")
    p_rotate.add_argument("--group", default="pi")

    args = parser.parse_args(argv)
    try:
        if args.command == "show":
            print(read_token(args.path))
        elif args.command == "ensure":
            token, created = ensure(path=args.path, group=args.group)
            print(token)
            print("created" if created else "preserved")
        elif args.command == "rotate":
            print(rotate(path=args.path, group=args.group))
    except RuntimeError as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
