"""Explicit Windows private-workspace binding for offline orchestrator CLI.

This is a point-in-time storage policy; it does NOT provide Windows
handle-relative protection against hostile simultaneous path replacement.
Legacy APIs remain available offline and carry no private-workspace assurance.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .storage_hardening import parse_current_user_sid, reject_reparse_path
from .windows_acl import read_windows_descriptor, validate_private_descriptor

_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z")
_ALLOWED_SIDS = {"S-1-5-18"}
_FULL_CONTROL = 0x1F01FF


@dataclass(frozen=True)
class PrivateStorageContext:
    root: Path
    database: Path
    blobs: Path

    def require_path(self, value: str | Path, *, directory: bool = False) -> Path:
        """Reject relative paths, aliases, symlinks, junctions and escapes."""
        supplied = Path(value).expanduser()
        if not supplied.is_absolute():
            raise ValueError("protected storage needs absolute input paths")
        if supplied != self.root and self.root not in supplied.parents:
            raise ValueError("protected input must stay inside the private workspace")
        # Check each part INSIDE the already verified root. On POSIX the
        # legacy reparse helper canonicalizes trusted /var aliases first;
        # this strict protected-input rule must still reject interior links.
        current = supplied
        while current != self.root:
            if current.is_symlink():
                raise ValueError("protected input traverses a reparse point")
            current = current.parent
        reject_reparse_path(
            supplied, error_message="protected input traverses a reparse point"
        )
        resolved = supplied.resolve(strict=True)
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("protected input must stay inside the private workspace")
        info = resolved.stat()
        if directory and not stat.S_ISDIR(info.st_mode):
            raise ValueError("protected input must be a directory")
        if not directory and not stat.S_ISREG(info.st_mode):
            raise ValueError("protected input must be a regular file")
        return resolved

    def require_staging_root(self, value: str | Path) -> Path:
        resolved = self.require_path(value, directory=True)
        if resolved not in (self.root, self.blobs):
            raise ValueError("protected staging audit requires workspace root or blobs")
        return resolved

    def require_blob_root(self, value: str | Path) -> Path:
        resolved = self.require_path(value, directory=True)
        if resolved != self.blobs:
            raise ValueError("protected worker blob root does not match workspace")
        return resolved


def _check_child_acl(path: Path, sid: str) -> None:
    """Existing SQLite/blob child must not grant any unrelated principal."""
    if not path.exists():
        return
    reject_reparse_path(
        path, error_message="private workspace child traverses reparse point"
    )
    desc = read_windows_descriptor(path)
    if desc.get("owner_sid") != sid:
        raise PermissionError("private workspace child has an unexpected owner")
    aces = desc.get("aces", [])
    wanted = {sid, *_ALLOWED_SIDS}
    if (not aces or {a.get("sid") for a in aces} != wanted
            or any(a.get("type") != 0 or not isinstance(a.get("mask"), int)
                   or a["mask"] & ~_FULL_CONTROL for a in aces)):
        raise PermissionError("private workspace child grants unexpected access")


def load_private_workspace(label: str) -> PrivateStorageContext:
    """Reopen one *existing* Windows-only provisioned workspace, without repair.

    Refuse an arbitrary --db/--blob-root instead of granting it a private
    assurance. Check DACLs before CLI dispatch, but do not claim race immunity.
    """
    if os.name != "nt":
        raise OSError("protected private workspaces require native Windows")
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ValueError("invalid private workspace label")
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OSError("LOCALAPPDATA is unavailable")
    base = Path(local).expanduser()
    reject_reparse_path(base, error_message="LOCALAPPDATA traverses reparse point")
    root = base / "chatgpt-web2api" / label
    reject_reparse_path(root, error_message="private root traverses reparse point")
    if not root.is_dir() or root.is_symlink():
        raise ValueError("private workspace must already exist; provision explicitly")
    canonical = root.resolve(strict=True)
    sid_result = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    sid = parse_current_user_sid(sid_result.stdout)
    validate_private_descriptor(read_windows_descriptor(canonical), sid)
    database = canonical / "controller.sqlite3"
    blobs = canonical / "blobs"
    for path, is_directory in ((database, False), (blobs, True)):
        reject_reparse_path(path, error_message="private child traverses reparse point")
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not (stat.S_ISDIR(info.st_mode) if is_directory
                else stat.S_ISREG(info.st_mode)):
            raise ValueError("private workspace child has wrong type")
        _check_child_acl(path, sid)
    return PrivateStorageContext(canonical, database, blobs)
