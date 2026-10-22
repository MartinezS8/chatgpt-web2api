"""Disposable Windows second-user access probe; never worker authorization.

Only for specially named throwaway probe roots. No account creation,
credential collection, elevation, actual Codex, or production workspace access.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import uuid
from pathlib import Path

_LABEL = re.compile(r"w2a-isolation-probe-[a-z0-9-]{6,40}\Z")
_MARKER = "probe-sentinel.bin"
_APPEND_MARKER = "probe-append-sentinel.bin"
_RENAME_MARKER = "probe-rename-sentinel.bin"
_DELETE_MARKER = "probe-delete-sentinel.bin"
_OWNER_TESTS = ("read", "append", "create", "rename", "delete")


def _probe_root(value: str | Path) -> Path:
    path = Path(value).expanduser()
    # Compare lexical elements; a restricted other account may not stat the
    # protected directory. This check grants no filesystem authority.
    if (not path.is_absolute() or path.parent.name.lower() != "chatgpt-web2api"
            or not _LABEL.fullmatch(path.name)
            or ".." in path.parts):
        raise ValueError("only a disposable w2a-isolation-probe-* workspace is supported")
    if path.is_symlink():
        raise ValueError("probe workspace must not be a symlink")
    if os.name == "nt":
        from .storage_hardening import reject_reparse_path

        # A junction somewhere above a synthetically named root must not
        # redirect destructive probe operations to another directory.
        reject_reparse_path(
            path, error_message="synthetic probe root traverses a reparse point",
        )
    return path


def current_windows_sid() -> str:
    if os.name != "nt":
        raise OSError("Windows-only identity probe")
    from .storage_hardening import parse_current_user_sid

    r = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return parse_current_user_sid(r.stdout)


def prepare_disposable_probe(label: str) -> dict:
    """Create a NEW private root and synthetic marker; never alter an existing root."""
    if os.name != "nt":
        raise OSError("Windows-only disposable root setup")
    if not _LABEL.fullmatch(label):
        raise ValueError("probe label must begin w2a-isolation-probe-")
    from .storage_hardening import create_private_windows_workspace

    workspace = create_private_windows_workspace(label)
    root = _probe_root(workspace.root)
    marker = root / _MARKER
    # Each potentially mutating access check has its OWN disposable marker.
    # The original read-only sentinel must survive even when isolation FAILS.
    for kind, filename in (
        ("read", _MARKER), ("append", _APPEND_MARKER),
        ("rename", _RENAME_MARKER), ("delete", _DELETE_MARKER),
    ):
        (root / filename).write_bytes(
            b"offline-second-user-probe:" + kind.encode("ascii") + b":"
            + uuid.uuid4().hex.encode("ascii")
        )
    return {
        "root": str(root), "controller_sid": current_windows_sid(),
        "synthetic_marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
        "operation_marker_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (_APPEND_MARKER, _RENAME_MARKER, _DELETE_MARKER)
        },
        "production_authorized": False,
        "instructions": "Run the separate --probe command under an EXISTING authorized "
                        "restricted second Windows identity; preserve both local receipts.",
    }


def _check(operation) -> str:
    try:
        operation()
    except PermissionError:
        return "DENIED"
    except (FileNotFoundError, NotADirectoryError):
        return "INCONCLUSIVE_MISSING"
    except OSError:
        return "INCONCLUSIVE_ERROR"
    return "ALLOWED"


def _assessment(results: dict) -> str:
    if any(value == "ALLOWED" for value in results.values()):
        return "FAIL_ACCESS_ALLOWED"
    if set(results) != set(_OWNER_TESTS):
        return "INCONCLUSIVE"
    if all(value == "DENIED" for value in results.values()):
        # This is still not a signed/externally attested identity & path pair.
        return "OBSERVED_DENIAL_REQUIRES_INDEPENDENT_ATTESTATION"
    return "INCONCLUSIVE"


def probe_disposable_root(root_value: str | Path, *, expected_controller_sid: str) -> dict:
    """Try read/write/create/rename/delete of SYNTHETIC files as a second user.

    The caller must intentionally run this process under an authorized OTHER
    Windows identity. If the SID is unchanged, stop before touching any file.
    """
    if os.name != "nt":
        raise OSError("Windows-only effective-access probe")
    root = _probe_root(root_value)
    sid = current_windows_sid()
    if not isinstance(expected_controller_sid, str) or not expected_controller_sid:
        raise ValueError("controller SID receipt is required")
    if sid == expected_controller_sid:
        return {"status": "FAIL_SAME_WINDOWS_IDENTITY", "probe_sid": sid,
                "different_identity": False, "checks": {},
                "live_send_permitted": False, "production_authorized": False}
    marker = root / _MARKER
    append_target = root / _APPEND_MARKER
    rename_target = root / _RENAME_MARKER
    delete_target = root / _DELETE_MARKER
    scratch = root / ("probe-attempt-" + uuid.uuid4().hex + ".tmp")
    moved = root / ("probe-renamed-" + uuid.uuid4().hex + ".tmp")

    def append_marker():
        # Do not create a missing marker: that is an inconclusive probe setup,
        # not evidence that append access to the prepared object was allowed.
        descriptor = os.open(append_target, os.O_WRONLY | os.O_APPEND | os.O_BINARY)
        with os.fdopen(descriptor, "ab") as f:
            f.write(b"x")

    def create_scratch():
        # x mode never overwrites anything; delete only the newly created file.
        with scratch.open("xb") as f:
            f.write(b"x")
        try:
            scratch.unlink()
        except OSError:
            # Creation already succeeded: do not disguise it as a denial.
            pass

    def rename_marker():
        rename_target.rename(moved)
        try:
            moved.rename(rename_target)
        except OSError:
            # The first rename already succeeded; report ALLOWED.
            pass

    results = {"read": _check(lambda: marker.read_bytes()),
               "append": _check(append_marker),
               "create": _check(create_scratch),
               "rename": _check(rename_marker),
               "delete": _check(delete_target.unlink)}
    return {
        "status": _assessment(results), "probe_sid": sid,
        "different_identity": True, "checks": results,
        "live_send_permitted": False, "production_authorized": False,
        "warning": "Only a disposable synthetic marker was touched. "
                   "Independent controller/root attestation is still required.",
    }
