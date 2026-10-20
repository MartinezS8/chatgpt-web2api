"""Crash-conservative staging lifetime protocol (no remote actions).

Only V2 stages created while holding the same directory lock are eligible for
cleanup. Historical .staged-* and .sqlite-snapshot-* are never removed.
"""
from __future__ import annotations

import math
import os
import re
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK_NAME = ".orchestrator-stage.lock"
_LOCAL_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.Lock] = {}


def _local_stage_lock(directory: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(directory))
    with _LOCAL_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.Lock())


_MANAGED = re.compile(r"\.(?:staged|sqlite-snapshot)-v2-[0-9a-f]{32}\Z")
_LEGACY = (".staged-", ".sqlite-snapshot-")


def _validate_times(min_age_seconds: float, now: float | None) -> float:
    if not math.isfinite(min_age_seconds) or min_age_seconds < 0:
        raise ValueError("minimum age must be finite and nonnegative")
    observed = time.time() if now is None else now
    if not math.isfinite(observed):
        raise ValueError("inspection time must be finite")
    return observed


def _regular(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and not (
        os.name == "nt" and getattr(info, "st_file_attributes", 0) & 0x400
    )


def _safe_directory(root: str | Path) -> Path:
    directory = Path(root).expanduser()
    info = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise ValueError("staging root must be an existing real directory")
    if os.name == "nt" and getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("staging root cannot be a Windows reparse point")
    return directory


@contextmanager
def stage_guard(directory: str | Path):
    """Hold an OS-level cross-process lock throughout staging/publishing.

    The lock is automatically released when a writer process exits hard.
    This protocol only protects cooperating V2 writers in a controlled root.
    """
    directory = _safe_directory(directory)
    # Protect threads in the same process as well as separate processes.
    with _local_stage_lock(directory):
        path = directory / _LOCK_NAME
        if path.is_symlink():
            raise ValueError("staging lock cannot be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("staging lock is not a regular file")
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def create_managed_stage(directory: str | Path, kind: str) -> tuple[int, Path]:
    """Call only under stage_guard; guard is held until publish or unlink."""
    if kind not in ("staged", "sqlite-snapshot"):
        raise ValueError("unknown managed stage kind")
    directory = _safe_directory(directory)
    for _ in range(3):
        path = directory / f".{kind}-v2-{secrets.token_hex(16)}"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            return fd, path
        except FileExistsError:
            continue
    raise FileExistsError("unable to allocate unique managed stage")


def inspect_stages(directory: str | Path, *, min_age_seconds: float = 3600,
                   now: float | None = None) -> list[dict]:
    """Read-only inventory. File age alone is NOT evidence of abandonment."""
    now = _validate_times(min_age_seconds, now)
    directory = _safe_directory(directory)
    result = []
    for path in sorted(directory.iterdir()):
        if not path.name.startswith(_LEGACY):
            continue
        try:
            info = path.lstat()
        except FileNotFoundError:
            # Inventory races with publication/removal; absence is not an error.
            continue
        managed = _MANAGED.fullmatch(path.name) is not None
        regular = _regular(info)
        eligible = managed and regular
        result.append({"name": path.name,
                       "kind": "managed_v2" if managed else "legacy_unmanaged",
                       "size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
                       "entry_type": "regular_file" if regular else "non_regular",
                       "disposition": "cooperative_locked_review" if eligible
                       else "manual_review_only",
                       "age_seconds": max(0.0, now - info.st_mtime),
                       "eligible_for_locked_review": bool(
                           eligible and max(0.0, now - info.st_mtime) >= min_age_seconds
                       ), "deleted": False})
    return result


def cleanup_managed_stages(directory: str | Path, *, min_age_seconds: float = 3600,
                           dry_run: bool = True, now: float | None = None) -> dict:
    """Remove only managed V2 crash leftovers while no cooperating writer runs.

    Existing pre-V2 files are always preserved. Callers must explicitly opt
    into deletion; the default is inspection only. A malicious non-cooperating
    process with write access to the root is out of scope: use private ACLs.
    """
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")
    now = _validate_times(min_age_seconds, now)
    if dry_run:
        # A real read-only inspection must not create a persistent lockfile.
        return {"dry_run": True, "removed": [],
                "legacy_files_never_deleted": True,
                "requires_cooperative_writers": True,
                "inventory": inspect_stages(directory, min_age_seconds=min_age_seconds,
                                            now=now)}
    with stage_guard(directory) as root:
        examined = inspect_stages(root, min_age_seconds=min_age_seconds, now=now)
        removed = []
        for item in examined:
            if not item["eligible_for_locked_review"] or dry_run:
                continue
            path = root / item["name"]
            try:
                before = path.lstat()
                after = path.lstat()
            except FileNotFoundError:
                continue
            if not _regular(before) or not _regular(after):
                continue
            if max(0.0, now - after.st_mtime) < min_age_seconds:
                continue
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
            ):
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            item["deleted"] = True
            removed.append(path.name)
        return {"dry_run": dry_run, "removed": removed,
                "legacy_files_never_deleted": True,
                "requires_cooperative_writers": True, "inventory": examined}
