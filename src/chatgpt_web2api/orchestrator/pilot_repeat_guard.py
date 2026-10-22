"""Durable local hobby replay reservation shared by separately named receipts.

This is NOT an authoritative provider-delivery ledger; it prevents accidental
duplicate manual launches under the same Windows user, model, prompt and CWD.
Only called after --allow-one-turn. Conservative policy: no auto-replay.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from .storage_hardening import reject_reparse_path


def reserve_local_pilot_once(
    *, receipt_dir: Path, cwd: Path, model_slug: str, effort: str,
    prompt_sha256: str, codex_binary_sha256: str,
) -> None:
    """Atomically reserve an attempt key; duplicate means manual review."""
    if any(
        type(item) is not str or not item or len(item) > 256
        for item in (model_slug, effort, prompt_sha256, codex_binary_sha256)
    ):
        raise ValueError("malformed local attempt identity")
    localappdata = os.environ.get("LOCALAPPDATA")
    base = Path(localappdata) if localappdata else receipt_dir.parent
    if not base.is_absolute() or not base.is_dir():
        raise ValueError("local replay registry base must already exist")
    reject_reparse_path(base, error_message="replay registry base is redirected")
    database = base / "w2a-codex-pilot-replay.sqlite3"
    if database.exists():
        reject_reparse_path(database, error_message="replay registry is redirected")
        if not database.is_file() or database.is_symlink():
            raise ValueError("replay registry is not a regular file")
    fingerprint = hashlib.sha256(json.dumps({
        "cwd": str(cwd.resolve()),
        "model_slug": model_slug,
        "effort": effort,
        "prompt_sha256": prompt_sha256,
        "codex_binary_sha256": codex_binary_sha256,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    with sqlite3.connect(database, timeout=30, isolation_level=None) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS pilot_one_turn_reservations(
            fingerprint TEXT PRIMARY KEY,
            receipt_path TEXT NOT NULL,
            created_unix INTEGER NOT NULL DEFAULT (unixepoch())
        )""")
        try:
            conn.execute(
                "INSERT INTO pilot_one_turn_reservations(fingerprint,receipt_path) "
                "VALUES (?,?)", (fingerprint, str(receipt_dir)),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            raise PermissionError(
                "this one-turn pilot is already recorded locally; "
                "inspect the prior receipt before any new attempt"
            ) from None
        conn.commit()
