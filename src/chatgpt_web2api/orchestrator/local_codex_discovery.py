"""Opt-in LOCAL Codex app-server handshake/account/model discovery without turns.

Hobby-friendly one-shot CLI; this is not a worker and has no dispatch API.
Only fixed initialize, initialized, account/read and model/list frames can be
written. The local native exe and captured schema bundle are SHA-pinned.
Never prints account email, auth tokens, raw server frames, or stderr.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .schema_fixture_audit import _digest, verified_bundle
from .storage_hardening import reject_reparse_path

_MAX_FRAME = 65536
_MAX_EVENTS = 512
_ALLOWED_REQUESTS = frozenset({"initialize", "account/read", "model/list"})
_ALLOWED_NOTIFICATIONS = frozenset({"initialized"})
_EOF = object()


def _pairs_no_duplicates(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate app-server JSON key")
        output[key] = value
    return output


class _DiscoverySession:
    def __init__(self, process, *, timeout: float):
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("app-server stdio unavailable")
        self._process = process
        self._timeout = timeout
        self._output = queue.Queue(maxsize=64)
        self._overflow = threading.Event()
        self._read_count = 0
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self):
        try:
            while True:
                line = self._process.stdout.readline(_MAX_FRAME + 1)
                if not line:
                    self._enqueue(_EOF)
                    return
                if len(line) > _MAX_FRAME or not line.endswith(b"\n"):
                    self._enqueue(RuntimeError("app-server frame exceeded limit"))
                    return
                self._enqueue(line)
                if self._overflow.is_set():
                    return
        except Exception:
            self._enqueue(RuntimeError("app-server stdout read failed"))

    def _enqueue(self, frame):
        try:
            self._output.put_nowait(frame)
        except queue.Full:
            self._overflow.set()

    def _send(self, message: dict):
        method = message.get("method")
        if ("id" in message and method not in _ALLOWED_REQUESTS) or (
            "id" not in message and method not in _ALLOWED_NOTIFICATIONS
        ):
            raise PermissionError("discovery refuses requests that can start work")
        encoded = (json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(encoded) > _MAX_FRAME:
            raise ValueError("discovery request too large")
        try:
            self._process.stdin.write(encoded)
            self._process.stdin.flush()
        except (OSError, BrokenPipeError, ValueError):
            raise RuntimeError("app-server request could not be delivered") from None

    def request(self, request_id: int, method: str, params: dict) -> dict:
        if method not in _ALLOWED_REQUESTS:
            raise PermissionError("discovery method is not read-only allowlisted")
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self._timeout
        while True:
            if self._overflow.is_set():
                raise RuntimeError("app-server output queue overflow")
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("app-server discovery response timed out")
            try:
                frame = self._output.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            self._read_count += 1
            if self._read_count > _MAX_EVENTS:
                raise RuntimeError("app-server discovery event limit exceeded")
            if frame is _EOF:
                raise RuntimeError("app-server terminated during discovery")
            if isinstance(frame, Exception):
                raise frame
            try:
                message = json.loads(frame.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
            except (UnicodeError, ValueError):
                raise RuntimeError("malformed app-server response") from None
            if not isinstance(message, dict):
                raise RuntimeError("app-server message must be an object")
            if "id" not in message:
                if not isinstance(message.get("method"), str):
                    raise RuntimeError("unexpected server traffic without method")
                # Notifications may contain account-specific data; ignore them.
                continue
            if (type(message["id"]) is not int or message["id"] != request_id
                    or "error" in message or not isinstance(message.get("result"), dict)
                    or "method" in message):
                raise RuntimeError("unexpected or failed app-server request correlation")
            return message["result"]

    def notification(self, method: str, params: dict) -> None:
        if method not in _ALLOWED_NOTIFICATIONS:
            raise PermissionError("discovery notification is not allowlisted")
        self._send({"method": method, "params": params})


def _model_summary(record: Any) -> dict:
    if type(record) is not dict:
        raise ValueError("malformed Codex model catalog item")
    mid = record.get("id")
    if not isinstance(mid, str) or not mid or len(mid) > 256:
        raise ValueError("model id is missing")
    efforts = record.get("supportedReasoningEfforts")
    if not isinstance(efforts, list) or len(efforts) > 32:
        raise ValueError("model reasoning efforts missing or excessive")
    names = []
    for entry in efforts:
        effort = entry.get("reasoningEffort") if isinstance(entry, dict) else None
        if not isinstance(effort, str) or not effort or len(effort) > 64:
            raise ValueError("model effort is malformed")
        if effort in names:
            raise ValueError("duplicate model effort")
        names.append(effort)
    default = record.get("defaultReasoningEffort")
    if default is not None and default not in names:
        raise ValueError("model default effort not offered")
    return {
        "id": mid,
        "display_name": record.get("displayName") if isinstance(record.get("displayName"), str) else mid,
        "default_effort": default,
        "supported_efforts": names,
        "is_default": record.get("isDefault") is True,
    }


def discover_local_codex(
    executable: str | Path, schema_root: str | Path, cwd: str | Path, *,
    allow_account_discovery: bool = False, response_timeout: int = 15,
) -> dict:
    """Launch a pinned local executable ONLY when account discovery is opted in."""
    if allow_account_discovery is not True:
        raise PermissionError("pass explicit --allow-account-discovery to start app-server")
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise OSError("Codex discovery is for Windows 11 / Python 3.12")
    if type(response_timeout) is not int or not 2 <= response_timeout <= 60:
        raise ValueError("timeout must be an integer 2..60")
    exe = Path(executable).expanduser()
    working = Path(cwd).expanduser()
    if not exe.is_absolute() or exe.suffix.lower() != ".exe" or not exe.is_file():
        raise ValueError("explicit absolute native Codex .exe required")
    if not working.is_absolute() or not working.is_dir():
        raise ValueError("existing explicit work directory required")
    reject_reparse_path(exe, error_message="Codex exe traverses reparse path")
    reject_reparse_path(working, error_message="Codex cwd traverses reparse path")
    receipt, _schemas = verified_bundle(schema_root)
    if _digest(exe) != receipt["codex_binary_sha256"]:
        raise ValueError("Codex binary changed since pinned schema generation")
    version = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, check=True, timeout=20,
    ).stdout.strip()
    if version != receipt["codex_version"]:
        raise ValueError("Codex version changed since pinned schema generation")
    process = subprocess.Popen(
        [str(exe), "app-server"],
        cwd=str(working), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, bufsize=0,
    )
    try:
        session = _DiscoverySession(process, timeout=response_timeout)
        hello = session.request(1, "initialize", {
            "clientInfo": {"name": "w2a_local_discovery", "title": "W2A local diagnostic",
                           "version": "0.1.0"},
        })
        if not isinstance(hello.get("userAgent"), str):
            raise RuntimeError("Codex initialization response not recognized")
        session.notification("initialized", {})
        account = session.request(2, "account/read", {"refreshToken": False})
        info = account.get("account")
        if info is not None and not isinstance(info, dict):
            raise RuntimeError("Codex account response malformed")
        if type(account.get("requiresOpenaiAuth")) is not bool:
            raise RuntimeError("Codex auth requirement missing")
        auth_type = info.get("type") if isinstance(info, dict) else None
        if auth_type is not None and not isinstance(auth_type, str):
            raise RuntimeError("invalid auth type")
        models = []
        seen_ids = set()
        cursor = None
        for index in range(8):
            params = {"limit": 100, "includeHidden": False}
            if cursor is not None:
                params["cursor"] = cursor
            response = session.request(3 + index, "model/list", params)
            data = response.get("data")
            if not isinstance(data, list) or len(data) > 100:
                raise RuntimeError("invalid or excessive model list")
            for item in data:
                summary = _model_summary(item)
                if summary["id"] in seen_ids:
                    raise RuntimeError("duplicate model id across pages")
                seen_ids.add(summary["id"])
                models.append(summary)
            next_cursor = response.get("nextCursor")
            if next_cursor is None:
                break
            if (not isinstance(next_cursor, str) or not next_cursor
                    or len(next_cursor) > 1024 or next_cursor == cursor):
                raise RuntimeError("invalid model list cursor")
            cursor = next_cursor
        else:
            raise RuntimeError("model discovery exceeded bounded pagination")
        return {
            "codex_version": version,
            "binary_sha256": receipt["codex_binary_sha256"],
            "account_present": info is not None,
            "account_type": auth_type,
            "requires_openai_auth": account["requiresOpenaiAuth"],
            "models": models,
            "model_count": len(models),
            "account_email_returned": False,
            "thread_started": False,
            "turn_started": False,
            "provider_inference_performed": False,
        }
    finally:
        # EOF is the documented local stdio lifecycle, never an RPC shutdown.
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if process.stdout is not None:
            process.stdout.close()
