"""Explicit, offline-only local storage protection and SQLite snapshot helpers.

Never touches a browser, credentials, remote account or provider. Windows ACL
creation is *opt in* for a new empty workspace; existing directories are not
silently modified. This does not certify an existing Windows installation.
"""
from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import stat
import subprocess
from contextlib import closing, nullcontext
from dataclasses import dataclass
from pathlib import Path

from .stage_maintenance import create_managed_stage, stage_guard
from .windows_acl import read_windows_descriptor, validate_private_descriptor

_SID = re.compile(r"S-1-\d+(?:-\d+)+\Z")
_LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}\Z")


@dataclass(frozen=True)
class PrivateWorkspace:
    root: Path
    database: Path
    blobs: Path


def parse_current_user_sid(whoami_csv: str) -> str:
    """Read the SID, independent of a localized Windows account name."""
    rows = list(csv.reader(io.StringIO(whoami_csv.strip())))
    if len(rows) != 1 or len(rows[0]) != 2:
        raise ValueError("unable to determine exactly one Windows account SID")
    sid = rows[0][1].strip()
    if not _SID.fullmatch(sid):
        raise ValueError("invalid Windows account SID")
    return sid


def acl_commands(path: Path, sid: str) -> tuple[list[str], ...]:
    """Build argv, never shell code; keep SYSTEM for OS maintenance."""
    if not _SID.fullmatch(sid):
        raise ValueError("invalid Windows account SID")
    root = str(path)
    return (
        ["icacls.exe", root, "/inheritance:r"],
        ["icacls.exe", root, "/grant:r",
         f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
        # Python 3.12.4+ mkdir(0o700) adds explicit Administrators/Owner Rights
        # ACEs. Remove only these known creation grants on this new empty root.
        ["icacls.exe", root, "/remove:g", "*S-1-5-32-544", "*S-1-3-4"],
        ["icacls.exe", root, "/setowner", f"*{sid}"],
        ["icacls.exe", root, "/verify"],
    )


def reject_reparse_path(path: str | Path, *, error_message: str) -> None:
    """Reject symbolic links and reparse points in any existing path component.

    Python 3.11/3.12 report a Windows junction through ``st_file_attributes``
    but do not consistently expose ``Path.is_symlink()`` for it. The Windows
    FILE_ATTRIBUTE_REPARSE_POINT bit is 0x0400.
    """
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    if os.name != "nt":
        # macOS exposes many trusted temporary paths via /var -> /private/var.
        # Canonicalize these POSIX aliases before checking components. The
        # caller still verifies allowed_root containment on resolved paths,
        # and direct attachment symlinks are refused.
        absolute = absolute.resolve(strict=False)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        is_reparse_point = (
            os.name == "nt"
            and bool(getattr(info, "st_file_attributes", 0) & 0x0400)
        )
        if current.is_symlink() or is_reparse_point:
            raise ValueError(error_message)


def _reject_reparse(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("workspace path must not be a symlink")
    info = path.lstat()
    if info.st_mode and not stat.S_ISDIR(info.st_mode):
        raise ValueError("workspace path is not a directory")
    if os.name == "nt" and getattr(info, "st_file_attributes", 0) & 0x0400:
        raise ValueError("workspace path must not be a Windows reparse point")
    reject_reparse_path(
        path, error_message="workspace path must not traverse a reparse point"
    )


def create_private_windows_workspace(label: str) -> PrivateWorkspace:
    """Create a *new* protected workspace; fail closed if ACL setup fails.

    Only new, empty workspace directories are changed. Callers must explicitly
    opt in and then use the returned database/blob paths; legacy paths keep
    their previous behavior and are not automatically treated as protected.
    """
    if os.name != "nt":
        raise OSError("Windows ACL provisioning requires native Windows")
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ValueError("invalid private workspace label")
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OSError("LOCALAPPDATA is unavailable")
    supplied_local = Path(local).expanduser()
    reject_reparse_path(
        supplied_local, error_message="LOCALAPPDATA must not traverse a reparse point"
    )
    _reject_reparse(supplied_local)
    base = supplied_local.resolve(strict=True)
    _reject_reparse(base)
    product = base / "chatgpt-web2api"
    if product.exists():
        _reject_reparse(product)
    else:
        product.mkdir(mode=0o700)
    root = product / label
    # Exist-ok would risk rewriting ACLs of an existing user's data.
    root.mkdir(mode=0o700, exist_ok=False)

    try:
        completed = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        sid = parse_current_user_sid(completed.stdout)
        for argv in acl_commands(root, sid):
            subprocess.run(argv, capture_output=True, text=True,
                           timeout=15, check=True)
        _reject_reparse(root)
        validate_private_descriptor(read_windows_descriptor(root), sid)
        _reject_reparse(root)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Never leave files in a workspace whose ACL could not be established.
        # No secrets have been written to this new directory.
        try:
            root.rmdir()
        except OSError:
            # Removing inheritance can leave an empty directory with no ACE
            # that permits deletion. Restore the parent's ACL only to remove
            # this new, not-yet-populated directory; never reuse it on retry.
            try:
                subprocess.run(
                    ["icacls.exe", str(root), "/inheritance:e"],
                    capture_output=True, text=True, timeout=15, check=True,
                )
                root.rmdir()
            except (OSError, subprocess.SubprocessError):
                pass
        raise
    return PrivateWorkspace(root=root, database=root / "controller.sqlite3",
                            blobs=root / "blobs")


def snapshot_sqlite_same_directory(database: str | Path, filename: str, *, storage_policy=None) -> Path:
    """Create a no-clobber SQLite online backup alongside the source database.

    Backups must stay under the same OS-protected directory as the original
    file. Caller is responsible for provisioning/access-checking that folder.
    A hard-link publish fails instead of overwriting another backup.
    """
    if storage_policy is not None:
        from .storage_policy import checked_policy
        checked_policy(storage_policy).database(database)
    if not isinstance(filename, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.sqlite3", filename
    ):
        raise ValueError("backup must be a simple .sqlite3 filename")
    supplied = Path(database).expanduser()
    if supplied.is_symlink():
        raise ValueError("source database cannot be a symbolic link")
    reject_reparse_path(
        supplied, error_message="database path cannot traverse a reparse point"
    )
    src = supplied.resolve(strict=True)
    if not src.is_file():
        raise ValueError("source must be an existing regular SQLite file")
    parent = src.parent
    _reject_reparse(parent)
    dest = parent / filename
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("backup filename already exists")

    # The writer holds the cooperative directory lock until successful
    # publication or deletion. Recovery can only remove V2 stages after this
    # process has exited and the OS has released its lock.
    with stage_guard(parent, storage_policy=storage_policy):
        fd, stage = create_managed_stage(parent, "sqlite-snapshot")
        os.close(fd)
        try:
            pin = (storage_policy.database_session(src)
                   if storage_policy is not None else nullcontext())
            with pin, closing(sqlite3.connect(src)) as source:
                with closing(sqlite3.connect(stage)) as target:
                    source.backup(target)  # includes committed WAL transactions
                    check = target.execute("PRAGMA integrity_check").fetchone()
                    if check is None or check[0] != "ok":
                        raise ValueError("snapshot SQLite integrity check failed")
                    if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise ValueError("snapshot foreign key check failed")
            if os.name != "nt":
                os.chmod(stage, 0o600)
            with stage.open("r+b") as handle:
                os.fsync(handle.fileno())
            # Same-volume, no-clobber publish; no external provider actions.
            if storage_policy is not None:
                storage_policy.database(database)
            os.link(stage, dest)
            return dest
        finally:
            stage.unlink(missing_ok=True)
