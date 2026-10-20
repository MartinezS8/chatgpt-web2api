"""Read-only listing of temporary files left by interrupted local writes.

A candidate is NEVER automatically safe to delete: another process can own
it, even if its modification time is old. No unlink, rename, chmod, writes,
or network operations occur.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .storage_hardening import reject_reparse_path

_PREFIXES = (".staged-", ".sqlite-snapshot-")


@dataclass(frozen=True)
class StagingCandidate:
    path: str
    kind: str
    bytes: int
    modified_ns: int
    disposition: str = "manual_review_only"


def inspect_staging_directory(directory: str | Path) -> tuple[StagingCandidate, ...]:
    """List candidate metadata; never infer ownership or delete files."""
    supplied = Path(directory).expanduser()
    reject_reparse_path(supplied, error_message="staging directory traverses reparse point")
    root = supplied.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("staging audit needs an existing regular directory")
    candidates = []
    with os.scandir(root) as entries:
        for entry in entries:
            kind = next((x for x in _PREFIXES if entry.name.startswith(x)), None)
            if kind is None:
                continue
            info = entry.stat(follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or entry.is_symlink()
                    or (os.name == "nt" and getattr(info, "st_file_attributes", 0) & 0x0400)):
                continue
            candidates.append(
                StagingCandidate(str(root / entry.name), kind, info.st_size, info.st_mtime_ns)
            )
    return tuple(sorted(candidates, key=lambda c: c.path))
