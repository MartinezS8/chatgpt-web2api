"""Local immutable task packages and content-addressed attachment snapshots.

No upload, browser access, connector write, or model invocation is performed.
Store both prompt and immutable binary snapshots locally. Keep the controller
DB and artifact root accessible only to the intended OS account.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import stat
import time
from pathlib import Path

from .stage_maintenance import create_managed_stage, stage_guard
from .storage_hardening import reject_reparse_path
from .store import Store

_MAX_PROMPT = 1024 * 1024
_MAX_FILES = 12
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 48 * 1024 * 1024
_ALLOWED_EXT = frozenset({".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".yml", ".yaml", ".sql", ".csv", ".pdf", ".png", ".jpg", ".jpeg"})


def _stable_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TaskPackages:
    def __init__(self, store: Store, blob_root: str | Path):
        self.store = store
        self.storage_policy = store.storage_policy
        self._check_storage(blob_root)
        root = Path(blob_root).expanduser()
        if root.is_symlink():
            raise ValueError("artifact root cannot be a symbolic link")
        reject_reparse_path(
            root, error_message="artifact root cannot traverse a reparse point"
        )
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        reject_reparse_path(
            root, error_message="artifact root cannot traverse a reparse point"
        )
        self.blob_root = root.resolve(strict=True)
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_task_packages (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                package_sha256 TEXT NOT NULL, prompt TEXT NOT NULL,
                attachments_json TEXT NOT NULL, sealed_at REAL NOT NULL)""")

    def _check_storage(self, blob_root=None):
        if self.store.storage_policy is not self.storage_policy:
            raise ValueError("package storage mode changed")
        if self.storage_policy is not None:
            from .storage_policy import checked_policy
            policy = checked_policy(self.storage_policy)
            policy.database(self.store.path)
            policy.blobs(self.blob_root if blob_root is None else blob_root)

    def _store_blob(self, path: Path, initial: os.stat_result) -> dict:
        """Snapshot via an inode-checked source fd and cooperative stage lock.

        A source-file swap after the initial seal() stat is rejected by fstat.
        No complete Win32 reparse TOCTOU guarantee is claimed for paths writable
        by another principal: callers must use a private allowed_root.
        """
        h = hashlib.sha256()
        self._check_storage()
        if self.storage_policy is not None:
            self.storage_policy.source(path)
        with stage_guard(self.blob_root, storage_policy=self.storage_policy):
            reject_reparse_path(
                path, error_message="attachment path cannot traverse a reparse point"
            )
            fd, name = create_managed_stage(self.blob_root, "staged")
            try:
                with os.fdopen(fd, "wb") as target, path.open("rb") as source:
                    opened = os.fstat(source.fileno())
                    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
                    if any(getattr(opened, key) != getattr(initial, key) for key in identity):
                        raise ValueError("attachment identity changed before snapshot")
                    size = 0
                    while True:
                        data = source.read(64 * 1024)
                        if not data:
                            break
                        size += len(data)
                        if size > _MAX_FILE_BYTES or size > initial.st_size:
                            raise ValueError("attachment mutated or exceeds size budget")
                        h.update(data)
                        target.write(data)
                    final = os.fstat(source.fileno())
                    if size != initial.st_size or any(
                        getattr(final, key) != getattr(opened, key) for key in identity
                    ):
                        raise ValueError("attachment modified while snapshotting")
                    target.flush()
                    os.fsync(target.fileno())
                digest = h.hexdigest()
                self._check_storage()
                dest = self.blob_root / digest
                if dest.is_symlink():
                    raise ValueError("content-addressed target is symbolic link")
                if dest.exists():
                    if not dest.is_file() or _digest(dest.read_bytes()) != digest:
                        raise ValueError("existing blob has corrupted content")
                else:
                    os.replace(name, dest)
                    name = None
                    if os.name != "nt":
                        os.chmod(dest, 0o600)
                return {"name": path.name, "sha256": digest, "size": size,
                        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}
            finally:
                if name is not None:
                    name.unlink(missing_ok=True)

    def seal(self, task_id: str, prompt: str, attachments: list[str | Path] | tuple[str | Path, ...] = (),
             *, allowed_root: str | Path | None = None) -> dict:
        self._check_storage()
        if self.storage_policy is not None:
            if allowed_root is not None:
                self.storage_policy.source(allowed_root, directory=True)
            for attachment in attachments:
                self.storage_policy.source(attachment)
        task = self.store.get(task_id)
        if task is None:
            raise ValueError("task must exist before sealing package")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > _MAX_PROMPT:
            raise ValueError("invalid task prompt")
        if _digest(prompt.encode("utf-8")) != task["prompt_sha"]:
            raise ValueError("prompt does not match registered task hash")
        if len(attachments) > _MAX_FILES:
            raise ValueError("too many attachments")
        if attachments and allowed_root is None:
            raise ValueError("allowed_root is mandatory when sealing attachments")
        if allowed_root:
            supplied_allowed = Path(allowed_root).expanduser()
            reject_reparse_path(
                supplied_allowed, error_message="allowed_root cannot traverse a reparse point"
            )
            allowed = supplied_allowed.resolve(strict=True)
        else:
            allowed = None
        if allowed is not None and not allowed.is_dir():
            raise ValueError("allowed_root must be a directory")
        checked: list[tuple[Path, os.stat_result]] = []
        total = 0
        for supplied in attachments:
            raw = Path(supplied).expanduser()
            if raw.is_symlink():
                raise ValueError("symlink attachments are forbidden")
            reject_reparse_path(
                raw, error_message="attachment path cannot traverse a reparse point"
            )
            try:
                real = raw.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("attachment path missing or invalid") from exc
            if allowed is None or real == allowed or allowed not in real.parents:
                raise ValueError("attachment must be under allowed_root")
            if real.suffix.lower() not in _ALLOWED_EXT:
                raise ValueError("unsupported attachment extension")
            info = real.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("attachment is not a regular file")
            if info.st_size > _MAX_FILE_BYTES:
                raise ValueError("attachment too large")
            total += info.st_size
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("attachment package too large")
            checked.append((real, info))
        records = [self._store_blob(path, info) for path, info in checked]
        if len(set(r["sha256"] for r in records)) != len(records):
            raise ValueError("duplicate attachment content")
        manifest = {"schema": 1, "task_id": task_id, "prompt_sha256": task["prompt_sha"], "attachments": records}
        sha = _digest(_stable_json(manifest).encode("utf-8"))
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT package_sha256,prompt FROM orchestrator_task_packages WHERE task_id=?", (task_id,)).fetchone()
            if existing:
                if existing["package_sha256"] != sha or existing["prompt"] != prompt:
                    raise ValueError("task package sealed with different contents")
                return {**manifest, "package_sha256": sha, "created": False}
            db.execute("INSERT INTO orchestrator_task_packages VALUES (?,?,?,?,?)",
                       (task_id, sha, prompt, _stable_json(records), time.time()))
            self.store._event(db, task_id, "package.sealed", sha)
        return {**manifest, "package_sha256": sha, "created": True}

    def read(self, task_id: str, *, verify_blobs: bool = True) -> dict:
        self._check_storage()
        with self.store._connect() as db:
            p = db.execute("SELECT * FROM orchestrator_task_packages WHERE task_id=?", (task_id,)).fetchone()
            if p is None:
                raise ValueError("task package not sealed")
            task = db.execute("SELECT prompt_sha FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise ValueError("orphan package")
        records = json.loads(p["attachments_json"])
        manifest = {"schema": 1, "task_id": task_id, "prompt_sha256": task["prompt_sha"], "attachments": records}
        if _digest(p["prompt"].encode("utf-8")) != task["prompt_sha"]:
            raise ValueError("prompt integrity failed")
        if _digest(_stable_json(manifest).encode("utf-8")) != p["package_sha256"]:
            raise ValueError("manifest integrity failed")
        if verify_blobs:
            for attachment in records:
                blob = self.blob_root / attachment["sha256"]
                if self.storage_policy is not None:
                    self.storage_policy.source(blob)
                if blob.is_symlink() or not blob.is_file() or blob.stat().st_size != attachment["size"]:
                    raise ValueError("missing/changed attachment snapshot")
                with blob.open("rb") as f:
                    h = hashlib.sha256()
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                    if h.hexdigest() != attachment["sha256"]:
                        raise ValueError("attachment content differs from manifest")
        return {**manifest, "prompt": p["prompt"], "package_sha256": p["package_sha256"]}
