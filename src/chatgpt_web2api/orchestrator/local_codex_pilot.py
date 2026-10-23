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
from .local_pilot_messages import read_pilot_prompt, thread_start_params, turn_start_params
from .local_wire_schema import LocalWireSchemas
from .mcp_process_guard import verify_mcp_disabled
from .mcp_runtime_fence import require_external_tools_disabled
from .pilot_repeat_guard import reserve_local_pilot_once
from .storage_hardening import reject_reparse_path

_FRAME_MAX = 64 * 1024
_EOF = object()
_WIRE_METHODS = frozenset({
    "initialize", "initialized", "mcpServerStatus/list", "app/installed",
    "thread/start", "turn/start",
})


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
        self._final_answers: list[str] = []
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
                notification = message["method"]
                if (method != "turn/start" and
                        notification.startswith(("turn/", "item/"))):
                    raise RuntimeError("turn event appeared before turn/start was attempted")
                if method == "initialize" and notification.startswith("thread/"):
                    raise RuntimeError("thread event appeared before thread/start")
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
            if method == "model/rerouted":
                raise RuntimeError("model rerouting is not accepted by the pinned pilot")
            if method == "item/completed":
                params = message.get("params")
                if not isinstance(params, dict) or params.get("threadId") != thread_id:
                    raise RuntimeError("foreign or malformed agent message")
                if params.get("turnId") != turn_id:
                    raise RuntimeError("agent message belongs to another turn")
                item = params.get("item")
                if not isinstance(item, dict):
                    raise RuntimeError("completed item must be an object")
                if item.get("type") == "agentMessage":
                    text = item.get("text")
                    if not isinstance(text, str) or len(text) > 8192:
                        raise RuntimeError("agent message missing or exceeds bounded size")
                    if item.get("phase") in (None, "final_answer"):
                        if len(self._final_answers) >= 8:
                            raise RuntimeError("excessive final agent messages")
                        self._final_answers.append(text)
            if method != "turn/completed":
                if method.startswith(("turn/", "item/")):
                    params = message.get("params")
                    if not isinstance(params, dict) or params.get("threadId") != thread_id:
                        raise RuntimeError("foreign or malformed turn notification")
                    foreign = params.get("turnId")
                    if foreign is not None and foreign != turn_id:
                        raise RuntimeError("notification belongs to another turn")
                    nested = params.get("turn")
                    if (isinstance(nested, dict) and "id" in nested
                            and nested["id"] != turn_id):
                        raise RuntimeError("nested notification belongs to another turn")
                continue
            params = message.get("params")
            turn = params.get("turn") if isinstance(params, dict) else None
            if (not isinstance(params, dict) or params.get("threadId") != thread_id
                    or not isinstance(turn, dict) or turn.get("id") != turn_id
                    or turn.get("status") not in {"completed", "failed", "interrupted"}):
                raise RuntimeError("unmatched or malformed turn completion")
            return turn["status"], (self._final_answers[-1] if self._final_answers else None)



def _verify_effective_thread_settings(response: dict, *, model: str, cwd: Path) -> None:
    """Never conflate JSON-schema shape with effective local Codex settings.

    The real app-server returns top-level model, cwd, approvalPolicy and sandbox.
    Missing or mismatched effective values reject the pilot before turn/start.
    """
    sandbox = response.get("sandbox")
    read_only = sandbox == "read-only"
    if type(sandbox) is dict and set(sandbox).issubset({"type", "networkAccess"}):
        network_access = sandbox.get("networkAccess", False)
        read_only = (
            sandbox.get("type") == "readOnly"
            and type(network_access) is bool
            and network_access is False
        )
    if (response.get("model") != model
            or response.get("approvalPolicy") != "never"
            or not read_only
            or response.get("cwd") != str(cwd)):
        raise RuntimeError("Codex effective thread model/cwd/approval/sandbox differs")
    thread = response.get("thread")
    if isinstance(thread, dict):
        if thread.get("model") is not None and thread["model"] != model:
            raise RuntimeError("Codex embedded thread model differs")



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
    return hashlib.sha256((folder / "intent.json").read_bytes()).hexdigest()


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
    model: str, effort: str, schema_selectors: dict[str, str] | None = None,
    mcp_source_map: str | Path | None = None,
    allow_readonly_builtin_tools: bool = False,
    allow_one_turn: bool = False, timeout: int = 90,
) -> dict:
    """Run ONE explicitly allowed local turn; no retry, even on lost ACK."""
    if allow_one_turn is not True:
        raise PermissionError("explicit --allow-one-turn required before any live action")
    if type(timeout) is not int or not 10 <= timeout <= 180:
        raise ValueError("pilot timeout must be 10..180 seconds")
    if any(type(x) is not str or not x.strip() or len(x) > 256 for x in (model, effort)):
        raise ValueError("explicit model and effort are required")
    root = Path(cwd).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("pilot scratch cwd must be an existing absolute directory")
    reject_reparse_path(root, error_message="pilot cwd traverses reparse path")
    prompt = read_pilot_prompt(prompt_file)
    # Do not run account discovery until the four chosen wire schemas are
    # present and pinned. Missing selectors are a hard error, not a fallback.
    wire_schemas = LocalWireSchemas(schema_root, selections=schema_selectors)
    # The doctor verifies binary SHA/version and schema; no provider action.
    doctor = local_pilot_doctor(executable, schema_root, root)
    if wire_schemas.codex_version != doctor["codex_version"]:
        raise ValueError("pilot wire schema version differs from pinned executable")
    if mcp_source_map is None:
        raise PermissionError("explicit local MCP source map required before live operation")
    if allow_readonly_builtin_tools is not True:
        raise PermissionError(
            "explicit acceptance of unverified built-in read-only tool exposure required"
        )
    # Two configuration-only reads: fail before any local app-server or account.
    mcp_policy = verify_mcp_disabled(executable, root, mcp_source_map)
    offered = discover_local_codex(
        executable, schema_root, root, allow_account_discovery=True,
        mcp_source_map=mcp_source_map,
    )
    choices = [
        entry for entry in offered["models"]
        if entry["id"] == model and effort in entry["supported_efforts"]
    ]
    if len(choices) != 1:
        raise ValueError("live pilot model/effort not in account catalog")
    selection = choices[0]
    if selection.get("hidden") is True or selection.get("supports_text") is False:
        raise ValueError("selected model is hidden or does not support text input")
    if not offered["account_present"]:
        raise ValueError("Codex account is not logged in")
    if offered.get("account_mode") != "chatgpt":
        raise PermissionError("manual hobby pilot requires explicit ChatGPT login, not API-key billing")
    wire_model = selection.get("model_slug", model)
    if not isinstance(wire_model, str) or not wire_model:
        raise ValueError("catalog model slug is invalid")
    exe = Path(executable).expanduser()
    receipts = Path(receipt_dir).expanduser()
    intent_sha = _create_intent(
        receipts, prompt=prompt, model=model, effort=effort, cwd=root,
    )
    process = None
    wire = None
    try:
        reserve_local_pilot_once(
            receipt_dir=receipts, cwd=root, model_slug=wire_model, effort=effort,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            codex_binary_sha256=doctor["binary_sha256"],
        )
        process = subprocess.Popen(
            [str(exe), *mcp_policy.args, "app-server"], cwd=str(root),
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
        # Query the very same App Server that will later submit the turn.
        mcp_status = wire.rpc(
            4, "mcpServerStatus/list", {"limit": 100, "detail": "toolsAndAuthOnly"},
        )
        installed_apps = wire.rpc(5, "app/installed", {"forceRefresh": False})
        external_tool_state = require_external_tools_disabled(mcp_status, installed_apps)
        thread_params = thread_start_params(model=wire_model, cwd=str(root))
        wire_schemas.require("thread_params", thread_params)
        thread_response = wire.rpc(2, "thread/start", thread_params)
        wire_schemas.require("thread_result", thread_response)
        _verify_effective_thread_settings(thread_response, model=wire_model, cwd=root)
        thread = thread_response.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise RuntimeError("thread/start did not return a thread id")
        thread_id = thread["id"]
        turn_params = turn_start_params(
            thread_id=thread_id, prompt=prompt, model=wire_model, effort=effort, cwd=str(root),
        )
        wire_schemas.require("turn_params", turn_params)
        response = wire.rpc(3, "turn/start", turn_params)
        wire_schemas.require("turn_result", response)
        turn = response.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise RuntimeError("turn/start acknowledgement lacks turn id")
        turn_id = turn["id"]
        terminal, answer = wire.wait_terminal(thread_id=thread_id, turn_id=turn_id)
        answer_matches = terminal == "completed" and answer == "ORCH_TEST_OK"
        result = {
            "status": "transport_completed_unreviewed" if terminal == "completed"
                      else "turn_ended_needs_review",
            "turn_terminal_status": terminal,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "live_turn_started": True,
            "retry_permitted": False,
            "intent_sha256": intent_sha,
            "production_finalization_permitted": False,
            "codex_version": doctor["codex_version"],
            "local_replay_reservation_recorded": True,
            "mcp_process_config_verified": True,
            "external_tool_state": external_tool_state,
            "builtin_readonly_tool_exposure_acknowledged": True,
            "selected_catalog_id": model,
            "effective_model_slug": wire_model,
            "effective_thread_settings_verified": True,
            "assistant_message_observed": answer is not None,
            "assistant_output_sha256": (
                hashlib.sha256(answer.encode("utf-8")).hexdigest()
                if answer is not None else None
            ),
            "assistant_output_preview": answer[:1024] if answer is not None else None,
            "expected_output": "ORCH_TEST_OK",
            "assistant_output_matches_expected": answer_matches,
            "content_verified_by_operator": False,
        }
        _write_new_json(receipts / "result.json", result)
        return result
    except BaseException as exc:
        # KeyboardInterrupt/SystemExit also need durable uncertainty receipts.
        # Hard power loss cannot execute Python handlers: intent-only remains
        # INCOMPLETE_OR_INTERRUPTED in the read-only receipt doctor.
        turn_attempted = wire is not None and wire._turn_start_attempts > 0
        _write_new_json(receipts / "quarantine.json", {
            "status": ("needs_human_unknown_or_unverified_delivery" if turn_attempted
                       else "pre_turn_failure_no_turn_start_attempted"),
            "error_type": type(exc).__name__,
            "turn_start_may_have_been_sent": turn_attempted,
            "retry_permitted": False,
            "receipt_requires_manual_review": True,
            "intent_sha256": intent_sha,
        })
        raise
    finally:
        if process is not None:
            _stop(process)
