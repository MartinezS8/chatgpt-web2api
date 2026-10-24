"""Bind reviewed metadata to one binary, CWD, inventory and local source files.

This is a drift detector, not a signed provenance receipt or OS isolation.
It covers only the listed sources, not every managed/remote config layer.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .schema_fixture_audit import _digest
from .storage_hardening import reject_reparse_path


def _hash_metadata(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_fingerprint(path: Path) -> str | None:
    if not path.is_absolute():
        raise ValueError("snapshot source must be absolute")
    reject_reparse_path(path, error_message="snapshot source traverses reparse point")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("snapshot source must be a bounded regular file")
    return _digest(path)


def capture_snapshot(exe: Path, cwd: Path, inventory: dict, sources: list[Path]) -> dict:
    if len(sources) > 128:
        raise ValueError("too many snapshot sources")
    result = subprocess.run(
        [str(exe), "--version"], cwd=cwd, capture_output=True, text=True,
        timeout=20, check=False,
    )
    if (result.returncode or not result.stdout.startswith("codex-cli ")
            or len(result.stdout) > 128):
        raise ValueError("Codex version could not be pinned")
    return {
        "schema_version": 1,
        "codex_binary_sha256": _digest(exe),
        "codex_version": result.stdout.strip(),
        "cwd_sha256": _hash_metadata(str(cwd)),
        "inventory_sha256": _hash_metadata(inventory),
        "source_files": [
            {"path": str(p), "sha256": source_fingerprint(p)}
            for p in sorted(set(sources))
        ],
    }


def verify_snapshot(snapshot: object, exe: Path, cwd: Path, inventory: dict) -> None:
    keys = {"schema_version", "codex_binary_sha256", "codex_version", "cwd_sha256",
            "inventory_sha256", "source_files"}
    if (type(snapshot) is not dict or set(snapshot) != keys
            or type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1
            or type(snapshot["source_files"]) is not list
            or len(snapshot["source_files"]) > 128):
        raise ValueError("MCP snapshot structure invalid")
    sources = []
    for item in snapshot["source_files"]:
        if (type(item) is not dict or set(item) != {"path", "sha256"}
                or type(item["path"]) is not str):
            raise ValueError("MCP snapshot source invalid")
        sources.append(Path(item["path"]))
    if capture_snapshot(exe, cwd, inventory, sources) != snapshot:
        raise ValueError("MCP configuration snapshot changed; regenerate and review locally")
