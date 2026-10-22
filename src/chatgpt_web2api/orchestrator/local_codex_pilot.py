"""Explicitly opted-in ONE-TURN local Codex App Server hobby pilot.

This is a disposable diagnostic, NOT the canonical multi-worker delivery path.
No retries and no auto tool approvals. Only a new receipt directory is written.
The operator must choose an empty scratch cwd with no sensitive files.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .local_codex_discovery import _pairs_no_duplicates, discover_local_codex
from .local_pilot_doctor import local_pilot_doctor

_FRAME_MAX = 64 * 1024
_EOF = object()
_WIRE_METHODS = frozenset({"initialize", "initialized", "thread/start", "turn/start"})


class _OneTurnWire:
    """Sequential responses and buffered notifications, even before turn ACK."""

    def __init__(self, process, *, timeout: int):
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("local Codex stdio unavailable")
        self._p = process
        self._timeout = timeout
        self._frames = queue.Queue(maxsize=64)
        self._overflow = threading.Event()
        self._notifications: list[dict] = []
        self._frames_seen = 0
        self._turn_start_attempts = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        try:
            while True:
                frame = self._p.stdout.readline(_FRAME_MAX + 1)
                if not frame:
                    self._enqueue(_EOF)
                    return
                if len(frame) > _FRAME_MAX or not frame.endswith(b"\n"):
                    self._enqueue(RuntimeError("oversized or truncated local app-server frame"))
                    return
                self._enqueue(frame)
                if self._overflow.is_set():
                    return
        except Exception:
            self._enqueue(RuntimeError("local app-server output reader failed"))

    def _enqueue(self, frame):
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            self._overflow.set()

    def _send(self, method: str, params: dict, *, request_id: int | None = None):
        if method not in _WIRE_METHODS:
            raise PermissionError("method is not in the single-turn allowlist")
        if request_id is None and method != "initialized":
            raise PermissionError("only initialized may be a notification")
        if request_id is not None and method == "initialized":
            raise PermissionError("initialized must be a notification")
        if method == "turn/start":
            if self._turn_start_attempts:
                raise PermissionError("second turn/start is never permitted")
            # Treat any attempted pipe write as possibly delivered; no replay.
            self._turn_start_attempts += 1
        message = {"method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        data = (json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(data) > _FRAME_MAX:
            raise ValueError("outbound single-turn request exceeded limit")
        try:
            self._p.stdin.write(data)
            self._p.stdin.flush()
        except (OSError, ValueError):
            raise RuntimeError("single-turn pipe write uncertain; do not retry") from None

    def _next(self, deadline: float):
        while True:
            if self._overflow.is_set():
                raise RuntimeError("local app-server output overflow")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("single-turn app-server response timed out")
            try:
                frame = self._frames.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            self._frames_seen += 1
            if self._frames_seen > 512:
                raise RuntimeError("single-turn event limit exceeded")
            if frame is _EOF:
                raise RuntimeError("app-server closed with delivery status unknown")
            if isinstance(frame, Exception):
                raise frame
            try:
                message = json.loads(frame.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
            except (UnicodeError, ValueError):
                raise RuntimeError("malformed local app-server frame") from None
            if not isinstance(message, dict):
                raise RuntimeError("local app-server message must be a JSON object")
            if "id" in message and "method" in message:
                raise RuntimeError("server-initiated request needs human review; no auto-approval")
            if "id" not in message and not isinstance(message.get("method"), str):
                raise RuntimeError("unrecognized local app-server notification")
            return message

    def rpc(self, request_id: int, method: str, params: dict) -> dict:
        if method == "initialized":
            raise ValueError("initialized is not a request")
        self._send(method, params, request_id=request_id)
        deadline = time.monotonic() + self._timeout
        while True:
            message = self._next(deadline)
            if "id" not in message:
                if len(self._notifications) >= 128:
                    raise RuntimeError("too many pre-ack notifications")
                self._notifications.append(message)
                continue
            if (type(message.get("id")) is not int or message["id"] != request_id
                    or "error" in message or not isinstance(message.get("result"), dict)):
                raise RuntimeError("uncorrelated or rejected local app-server response")
            return message["result"]

    def initialized(self):
        self._send("initialized", {})

    def wait_terminal(self, *, thread_id: str, turn_id: str) -> str:
        deadline = time.monotonic() + self._timeout
        buffered = self._notifications
        self._notifications = []
        while True:
            message = buffered.pop(0) if buffered else self._next(deadline)
            if "id" in message:
                raise RuntimeError("unexpected extra app-server RPC result")
            method = message["method"]
            if method != "turn/completed":
                if method.startswith(("turn/", "item/")):
                    params = message.get("params")
                    if not isinstance(params, dict) or params.get("threadId") != thread_id:
                        raise RuntimeError("foreign or malformed turn notification")
                    foreign = params.get("turnId")
                    if foreign is not None and foreign != turn_id:
                        raise RuntimeError("notification belongs to another turn")
                continue
            params = message.get("params")
            turn = params.get("turn") if isinstance(params, dict) else None
            if (not isinstance(params, dict) or params.get("threadId") != thread_id
                    or not isinstance(turn, dict) or turn.get("id") != turn_id
                    or turn.get("status") not in {"completed", "failed", "interrupted"}):
                raise RuntimeError("unmatched or malformed turn completion")
            return turn["status"]


def _create_intent(folder: Path, *, prompt: str, model: str, effort: str, cwd: Path):
    if not folder.is_absolute() or folder.exists() or not folder.parent.is_dir():
        raise ValueError("receipt directory must be new and have an existing parent")
    folder.mkdir(exist_ok=False)
    record = {
        "status": "possible_send_not_yet_verified",
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "model": model, "effort": effort, "cwd": str(cwd),
        "max_turn_starts": 1, "retry_permitted": False,
        "created_unix": time.time(),
    }
    _write_new_json(folder / "intent.json", record)


def _write_new_json(path: Path, payload: dict):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _stop(proc):
    try:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    if proc.stdout is not None:
        proc.stdout.close()


def run_one_local_pilot(
    executable: str | Path, schema_root: str | Path, cwd: str | Path,
    prompt_file: str | Path, receipt_dir: str | Path, *,
    model: str, effort: str, allow_one_turn: bool = False, timeout: int = 90,
) -> dict:
    """Run ONE explicitly allowed local turn; no retry, even on lost ACK."""
    if allow_one_turn is not True:
        raise PermissionError("explicit --allow-one-turn required before any live action")
    if type(timeout) is not int or not 10 <= timeout <= 180:
        raise ValueError("pilot timeout must be 10..180 seconds")
    if any(type(x) is not str or not x.strip() or len(x) > 256 for x in (model, effort)):
        raise ValueError("explicit model and effort are required")
    prompt_path, root = Path(prompt_file).expanduser(), Path(cwd).expanduser()
    if not prompt_path.is_file() or prompt_path.stat().st_size > 4096:
        raise ValueError("prompt file must exist and contain at most 4 KiB")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not 1 <= len(prompt) <= 2000:
        raise ValueError("prompt must be non-empty, at most 2000 characters")
    # The doctor verifies binary SHA/version and schema; no provider action.
    doctor = local_pilot_doctor(executable, schema_root, root)
    # An explicit live-turn opt-in also allows account/model discovery.
    offered = discover_local_codex(
        executable, schema_root, root, allow_account_discovery=True,
    )
    if not any(
        entry["id"] == model and effort in entry["supported_efforts"]
        for entry in offered["models"]
    ):
        raise ValueError("live pilot model/effort not in account catalog")
    if not offered["account_present"]:
        raise ValueError("Codex account is not logged in")
    exe = Path(executable).expanduser()
    receipts = Path(receipt_dir).expanduser()
    _create_intent(receipts, prompt=prompt, model=model, effort=effort, cwd=root)
    process = None
    try:
        process = subprocess.Popen(
            [str(exe), "app-server"], cwd=str(root),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0,
        )
        wire = _OneTurnWire(process, timeout=timeout)
        hello = wire.rpc(1, "initialize", {"clientInfo": {
            "name": "w2a_manual_single_turn", "title": "W2A local hobby pilot",
            "version": "0.1.0",
        }})
        if not isinstance(hello.get("userAgent"), str):
            raise RuntimeError("app-server initialize result invalid")
        wire.initialized()
        thread_response = wire.rpc(2, "thread/start", {
            "model": model, "cwd": str(root),
            "approvalPolicy": "never", "sandbox": "read-only",
            "serviceName": "w2a_local_one_turn",
        })
        thread = thread_response.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise RuntimeError("thread/start did not return a thread id")
        thread_id = thread["id"]
        response = wire.rpc(3, "turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "model": model, "effort": effort, "cwd": str(root),
            "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"},
        })
        turn = response.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise RuntimeError("turn/start acknowledgement lacks turn id")
        turn_id = turn["id"]
        terminal = wire.wait_terminal(thread_id=thread_id, turn_id=turn_id)
        result = {
            "status": "transport_completed_unreviewed" if terminal == "completed"
                      else "turn_ended_needs_review",
            "turn_terminal_status": terminal,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "live_turn_started": True,
            "retry_permitted": False,
            "production_finalization_permitted": False,
            "codex_version": doctor["codex_version"],
        }
        _write_new_json(receipts / "result.json", result)
        return result
    except Exception as exc:
        _write_new_json(receipts / "quarantine.json", {
            "status": "needs_human_unknown_or_unverified_delivery",
            "error_type": type(exc).__name__,
            "retry_permitted": False,
            "receipt_requires_manual_review": True,
        })
        raise
    finally:
        if process is not None:
            _stop(process)
