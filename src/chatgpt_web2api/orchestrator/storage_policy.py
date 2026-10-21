"""Explicit Windows private-root policy; no hostile path-swap guarantee.

The label is configuration, never authority: every use reloads native ACLs.
Python code executing in this process is trusted, not a sandboxed principal.
"""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from .private_workspace import PrivateStorageContext, load_private_workspace


def _private_database_pin(path, *, create):
    """Acquire native pins with a fresh current-principal owner/DACL check."""
    from .storage_hardening import parse_current_user_sid
    from .windows_database_pin import pin_database

    result = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    sid = parse_current_user_sid(result.stdout)
    return pin_database(path, create=create, expected_sid=sid)


@dataclass(frozen=True)
class PrivateStoragePolicy:
    label: str
    context: PrivateStorageContext

    @classmethod
    def open(cls, label: str) -> PrivateStoragePolicy:
        return cls(label, load_private_workspace(label))

    def check(self) -> PrivateStorageContext:
        if type(self.context) is not PrivateStorageContext:
            raise TypeError("private context must be revalidated, not asserted")
        current = load_private_workspace(self.label)
        if current != self.context:
            raise PermissionError("private workspace binding changed")
        return current

    def database(self, path) -> Path:
        current = self.check()
        supplied = Path(path)
        if not supplied.is_absolute() or ".." in supplied.parts or supplied != current.database:
            raise ValueError("protected database must match workspace database")
        return supplied

    def blobs(self, path) -> Path:
        current = self.check()
        supplied = Path(path)
        if not supplied.is_absolute() or ".." in supplied.parts or supplied != current.blobs:
            raise ValueError("protected blobs must match workspace blobs")
        return current.require_blob_root(supplied)

    @contextmanager
    def database_session(self, path, *, create=False):
        """Recheck binding while Windows pins the main DB and direct parent.

        A native policy cannot open on other platforms. The null context only
        supports portable contract tests that replace the native loader.
        This is not a hostile-race boundary for SQLite sidecars or ancestors.
        """
        supplied = self.database(path)
        pin = nullcontext()
        if os.name == "nt":
            pin = _private_database_pin(supplied, create=create)
        with pin:
            self.database(supplied)
            yield

    def source(self, path, *, directory=False) -> Path:
        if ".." in Path(path).parts:
            raise ValueError("protected traversal forbidden")
        return self.check().require_path(path, directory=directory)

    def staging(self, path) -> Path:
        return self.check().require_staging_root(path)


def checked_policy(policy) -> PrivateStoragePolicy:
    if type(policy) is not PrivateStoragePolicy:
        raise TypeError("protected operations require a native-validated storage policy")
    policy.check()
    return policy
