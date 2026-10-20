"""Native DACL readback, not a path-race or effective-user-access attestation."""
from __future__ import annotations

import os
from pathlib import Path

_FULL_CONTROL = 0x1F01FF


def validate_private_descriptor(descriptor: dict, sid: str) -> None:
    """Accept only the exact owner/protected inheritable user+SYSTEM grants."""
    if descriptor.get("owner_sid") != sid or descriptor.get("protected") is not True:
        raise PermissionError("workspace owner or DACL protection is not private")
    expected = {(sid, _FULL_CONTROL, 3), ("S-1-5-18", _FULL_CONTROL, 3)}
    aces = descriptor.get("aces", [])
    if len(aces) != 2 or any(ace.get("type") != 0 for ace in aces):
        raise PermissionError("workspace has unexpected access control entries")
    observed = {(ace.get("sid"), ace.get("mask"), ace.get("flags")) for ace in aces}
    if observed != expected:
        raise PermissionError("workspace grants differ from private user/SYSTEM policy")


def read_windows_descriptor(path: str | Path) -> dict:
    """Read owner/DACL via Windows APIs without granting rights or elevation.

    This is a point-in-time, path-based observation. Callers must not infer
    handle-relative protection of later open/link/unlink operations from it.
    """
    if os.name != "nt":
        raise OSError("native DACL inspection requires Windows")
    import ctypes as c
    from ctypes import wintypes as w

    adv = c.WinDLL("advapi32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    ptr = c.c_void_p
    pp = c.POINTER(ptr)
    adv.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, c.c_int, w.DWORD,
                                         pp, pp, pp, pp, pp]
    adv.GetNamedSecurityInfoW.restype = w.DWORD
    adv.ConvertSidToStringSidW.argtypes = [ptr, c.POINTER(w.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = w.BOOL
    adv.GetSecurityDescriptorControl.argtypes = [ptr, c.POINTER(w.WORD),
                                                  c.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorControl.restype = w.BOOL
    adv.GetAce.argtypes = [ptr, w.DWORD, pp]
    adv.GetAce.restype = w.BOOL
    kernel.LocalFree.argtypes = [ptr]
    kernel.LocalFree.restype = ptr

    class ACL(c.Structure):
        _fields_ = [("revision", c.c_ubyte), ("reserved", c.c_ubyte),
                    ("size", w.WORD), ("count", w.WORD), ("reserved2", w.WORD)]

    owner, dacl, sd = ptr(), ptr(), ptr()
    error = adv.GetNamedSecurityInfoW(str(path), 1, 5, c.byref(owner), None,
                                     c.byref(dacl), None, c.byref(sd))
    if error:
        raise c.WinError(error)

    def sid_string(address):
        output = w.LPWSTR()
        if not adv.ConvertSidToStringSidW(address, c.byref(output)):
            raise c.WinError(c.get_last_error())
        try:
            return output.value
        finally:
            kernel.LocalFree(c.cast(output, ptr))

    try:
        if not owner or not dacl:
            raise PermissionError("workspace has absent owner or null DACL")
        control, revision = w.WORD(), w.DWORD()
        if not adv.GetSecurityDescriptorControl(sd, c.byref(control), c.byref(revision)):
            raise c.WinError(c.get_last_error())
        entries = []
        for index in range(c.cast(dacl, c.POINTER(ACL)).contents.count):
            ace = ptr()
            if not adv.GetAce(dacl, index, c.byref(ace)):
                raise c.WinError(c.get_last_error())
            address = ace.value
            kind = c.c_ubyte.from_address(address).value
            flags = c.c_ubyte.from_address(address + 1).value
            size = w.WORD.from_address(address + 2).value
            # Unknown ACE layouts must never be interpreted as ordinary grants.
            if kind != 0 or size < 16:
                raise PermissionError("workspace has unsupported ACE layout")
            entries.append({"type": kind, "flags": flags,
                            "mask": w.DWORD.from_address(address + 4).value,
                            "sid": sid_string(ptr(address + 8))})
        return {"owner_sid": sid_string(owner), "protected": bool(control.value & 0x1000),
                "aces": entries}
    finally:
        kernel.LocalFree(sd)
