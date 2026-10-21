"""Pin main DB/parent, optionally also WAL/SHM, without delete sharing.

This closes one main-file replacement window. It is NOT handle-relative
SQLite I/O: ancestors, rollback journals, publication and file contents remain
separate threat surfaces. In-process Python code is trusted.
"""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

from .windows_acl import (
    read_windows_handle_descriptor,
    validate_private_child_descriptor,
    validate_private_descriptor,
)


def _database_initialization_mutex_name(database: Path, sid: str) -> str:
    normalized = os.path.normcase(os.path.abspath(str(database)))
    digest = hashlib.sha256(f"{sid}\0{normalized}".encode()).hexdigest()
    return f"Local\\chatgpt-web2api-store-init-{digest}"


@contextmanager
def serialize_database_initialization(
    database: Path, *, sid: str, timeout_ms: int = 60_000,
):
    """Serialize cooperating protected Store initializers for one DB path.

    This named mutex is process coordination, not a security boundary. Its
    default Windows DACL comes from the creating process token; another
    process can bypass it, pre-create it, or cause a bounded startup denial.
    """
    if os.name != "nt":
        raise OSError("database initialization mutex requires native Windows")
    database = Path(database)
    if not database.is_absolute() or ".." in database.parts:
        raise ValueError("database initialization requires an absolute path without traversal")
    if len(database.drive) != 2 or database.drive[1] != ":":
        raise ValueError("database initialization requires a local drive path")
    if not isinstance(sid, str) or not sid.startswith("S-1-"):
        raise ValueError("database initialization requires a validated current-user SID")
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms < 0:
        raise ValueError("database initialization timeout must be a nonnegative integer")

    import ctypes as c
    from ctypes import wintypes as w

    name = _database_initialization_mutex_name(database, sid)

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.ReleaseMutex.argtypes = [w.HANDLE]
    kernel.ReleaseMutex.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL

    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise c.WinError(c.get_last_error())

    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, timeout_ms)
        if result in (0x00000000, 0x00000080):  # WAIT_OBJECT_0 / WAIT_ABANDONED
            acquired = True
        elif result == 0x00000102:  # WAIT_TIMEOUT
            raise TimeoutError("timed out waiting for protected database initialization")
        elif result == 0xFFFFFFFF:  # WAIT_FAILED
            raise c.WinError(c.get_last_error())
        else:
            raise OSError(f"unexpected Windows mutex wait result: {result:#x}")
        # WAIT_ABANDONED still grants ownership. The Store performs its normal
        # SQLite integrity, foreign-key and schema checks while holding it.
        yield result == 0x00000080
    finally:
        error = None
        if acquired and not kernel.ReleaseMutex(handle):
            error = c.WinError(c.get_last_error())
        if not kernel.CloseHandle(handle) and error is None:
            error = c.WinError(c.get_last_error())
        if error is not None:
            raise error


@contextmanager
def pin_database(database: Path, *, create: bool = False, expected_sid: str | None = None,
                 pin_wal_sidecars: bool = False,
                 pin_rollback_journal: bool = False):
    """Pin a regular, singly linked DB (optionally create an empty file).

    Acquire pins before the caller repeats its native policy validation and
    before SQLite opens. Hold until AFTER SQLite closes, including on errors.
    No ACL changes, shell, inheritable handles, or permissive fallback.

    If ``pin_rollback_journal`` is requested, the caller must select a
    rollback-safe non-DELETE journal mode before migration writes. Protected
    Store initialization uses PERSIST for that scoped connection.
    """
    if os.name != "nt":
        raise OSError("database pinning requires native Windows")
    database = Path(database)
    if not database.is_absolute() or ".." in database.parts:
        raise ValueError("database pin requires an absolute path without traversal")
    # Protected SQLite WAL sessions are local-only. Do not accidentally claim
    # UNC/network or device namespace compatibility from a path-string match.
    if len(database.drive) != 2 or database.drive[1] != ":":
        raise ValueError("database pin requires a local drive path")
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p,
                                  w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.GetFileInformationByHandle.argtypes = [w.HANDLE, c.c_void_p]
    kernel.GetFileInformationByHandle.restype = w.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = w.DWORD

    class Info(c.Structure):
        _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME),
                    ("accessed", w.FILETIME), ("written", w.FILETIME),
                    ("volume", w.DWORD), ("size_high", w.DWORD),
                    ("size_low", w.DWORD), ("links", w.DWORD),
                    ("index_high", w.DWORD), ("index_low", w.DWORD)]

    handles = []

    def acquire(path, *, directory, may_create=False):
        # Actual READ access is essential. A metadata-only handle did not
        # enforce delete denial in the native regression probe.
        handle = kernel.CreateFileW(
            str(path), 0x80000000, 3, None, 4 if may_create else 3,
            0x00200000 | (0x02000000 if directory else 0), None,
        )
        if handle == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        handles.append(handle)
        info = Info()
        if not kernel.GetFileInformationByHandle(handle, c.byref(info)):
            raise c.WinError(c.get_last_error())
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise ValueError("database pin rejects reparse points and wrong object types")
        if not directory and info.links != 1:
            raise ValueError("database pin rejects multiply linked files")
        # Compare the opened object's reported path, not a later resolve().
        buffer = c.create_unicode_buffer(32768)
        count = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not count or count >= len(buffer):
            raise OSError("cannot obtain pinned object's final path")
        expected = "\\\\?\\" + str(path)
        if os.path.normcase(buffer.value) != os.path.normcase(expected):
            raise ValueError("database pin opened an unexpected final path")
        if expected_sid is not None:
            descriptor = read_windows_handle_descriptor(handle)
            if directory:
                validate_private_descriptor(descriptor, expected_sid)
            else:
                validate_private_child_descriptor(descriptor, expected_sid)
        return info.volume, info.index_high, info.index_low

    try:
        acquire(database.parent, directory=True)
        identity = acquire(database, directory=False, may_create=create)
        if pin_rollback_journal:
            # The protected Store migration uses PERSIST while this pin is
            # held. That keeps SQLite's rollback journal on disk for recovery
            # while avoiding DELETE-mode's path-based commit unlink.
            acquire(Path(str(database) + "-journal"), directory=False, may_create=True)
        if pin_wal_sidecars:
            # SQLite may create these lazily. Bind both names before its first
            # open, without pinning the DELETE-mode rollback journal (whose
            # deletion is part of commit). Keep all pins through SQLite close.
            for suffix in ("-wal", "-shm"):
                acquire(Path(str(database) + suffix), directory=False, may_create=True)
        yield identity
    finally:
        # Attempt every close, even if an unexpected native close fails.
        error = None
        for handle in reversed(handles):
            if not kernel.CloseHandle(handle) and error is None:
                error = c.WinError(c.get_last_error())
        if error is not None:
            raise error
