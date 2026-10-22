"""Synthetic, local-only JSONL peer for the offline app-server harness.

This module is launched only by :mod:`app_server_fake`. It never imports the
Codex CLI, reads credentials, opens a network connection, or writes prompts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_MAX_FRAME_BYTES = 65_536
_MODEL = "offline-fake-model-0.157"
_THREAD_ID = "fake-thread-48b"
_SESSION_ID = "fake-session-48b"
_TURN_ID = "fake-turn-48b"


def _emit(value: dict, *, partial: bool = True) -> None:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > _MAX_FRAME_BYTES:
        raise ValueError("fake response exceeds frame limit")
    if not partial or len(data) < 4:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    cut1 = max(1, len(data) // 3)
    cut2 = max(cut1 + 1, 2 * len(data) // 3)
    for chunk in (data[:cut1], data[cut1:cut2], data[cut2:]):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        time.sleep(0.002)


def _response(request_id: int, result: dict) -> dict:
    return {"id": request_id, "result": result}


def _model_list(model: str = _MODEL) -> dict:
    return {
        "data": [
            {
                "id": model,
                "model": model,
                "displayName": "Offline synthetic model",
                "description": "Test fixture only; not a provider capability receipt.",
                "hidden": False,
                "defaultReasoningEffort": "medium",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "medium", "description": "Synthetic effort"}
                ],
                "isDefault": False,
            }
        ],
        "nextCursor": None,
    }


def _thread_start(request: dict) -> dict:
    params = request.get("params")
    if not isinstance(params, dict):
        raise ValueError("invalid thread request")
    model = params.get("model")
    cwd = params.get("cwd")
    if (model != _MODEL or not isinstance(cwd, str) or not cwd
            or params.get("sandbox") != "read-only"
            or params.get("approvalPolicy") != "on-request"):
        raise ValueError("unsafe or malformed fake thread request")
    now = int(time.time())
    thread = {
        "cliVersion": "0.157.0",
        "createdAt": now,
        "cwd": cwd,
        "ephemeral": True,
        "id": _THREAD_ID,
        "modelProvider": "offline-fake",
        "preview": "",
        "projectId": None,
        "sessionId": _SESSION_ID,
        "source": "offline-fake-app-server",
        "status": {"type": "idle"},
        "turns": [],
        "updatedAt": now,
    }
    return {
        "approvalPolicy": "on-request",
        "approvalsReviewer": None,
        "cwd": cwd,
        "model": model,
        "modelProvider": "offline-fake",
        "sandbox": "read-only",
        "thread": thread,
    }


def _event(method: str, params: dict) -> dict:
    return {"method": method, "params": params}


def serve(scenario: str) -> int:
    initialized = False
    for raw in sys.stdin.buffer:
        if len(raw) > _MAX_FRAME_BYTES or not raw.endswith(b"\n"):
            return 2
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 2
        if not isinstance(request, dict) or not isinstance(request.get("method"), str):
            return 2
        method = request["method"]
        request_id = request.get("id")
        params = request.get("params", {})
        if method == "initialized":
            if request_id is not None or initialized:
                return 2
            initialized = True
            continue
        if method == "initialize":
            if initialized or type(request_id) is not int:
                return 2
            _emit(_response(request_id, {
                "codexHome": os.path.abspath(os.getcwd()),
                "platformFamily": "windows",
                "platformOs": "windows",
                "userAgent": "offline-fake/0.157.0",
            }))
            continue
        if not initialized or type(request_id) is not int or not isinstance(params, dict):
            return 2
        if method == "model/list":
            if scenario == "truncated_jsonl":
                sys.stdout.buffer.write(b'{"id":')
                sys.stdout.buffer.flush()
                return 0
            if scenario == "duplicate_json_keys":
                sys.stdout.buffer.write(b'{"id":2,"id":2,"result":{}}\n')
                sys.stdout.buffer.flush()
                return 0
            if scenario == "malformed_json":
                sys.stdout.buffer.write(b"{bad-json\n")
                sys.stdout.buffer.flush()
                return 0
            if scenario == "oversized_output":
                sys.stdout.buffer.write(b"x" * (_MAX_FRAME_BYTES + 1) + b"\n")
                sys.stdout.buffer.flush()
                return 0
            if scenario == "output_flood":
                for index in range(128):
                    _emit(_event("synthetic/progress", {"sequence": index}))
            model = "different-offline-model" if scenario == "model_mismatch" else _MODEL
            _emit(_response(request_id, _model_list(model)))
            continue
        if method == "thread/start":
            _emit(_response(request_id, _thread_start(request)))
            if scenario == "broken_pipe_before_turn":
                return 0
            continue
        if method != "turn/start":
            return 2
        if (params.get("threadId") != _THREAD_ID
                or params.get("model") != _MODEL
                or params.get("effort") != "medium"
                or params.get("approvalPolicy") != "on-request"
                or params.get("sandboxPolicy") != {"type": "readOnly", "networkAccess": False}):
            return 2
        input_items = params.get("input")
        if (not isinstance(input_items, list) or not input_items
                or not isinstance(input_items[0], dict)
                or input_items[0].get("type") != "text"
                or not isinstance(input_items[0].get("text"), str)):
            return 2
        if scenario == "die_after_turn_request":
            return 0
        if scenario == "timeout_after_turn_request":
            time.sleep(10)
            return 0
        turn = {"id": _TURN_ID, "items": [], "status": "inProgress"}
        _emit(_event("turn/started", {"threadId": _THREAD_ID, "turn": turn}))
        if scenario == "foreign_thread":
            _emit(_event("item/started", {
                "threadId": "foreign-thread-48b", "turnId": _TURN_ID,
                "item": {"id": "item-48b", "type": "agentMessage"},
            }))
            return 0
        if scenario == "foreign_turn":
            _emit(_event("item/started", {
                "threadId": _THREAD_ID, "turnId": "foreign-turn-48b",
                "item": {"id": "item-48b", "type": "agentMessage"},
            }))
            return 0
        delta = input_items[0]["text"] if scenario == "echo_prompt" else "synthetic progress"
        _emit(_event("item/agentMessage/delta", {
            "threadId": _THREAD_ID, "turnId": _TURN_ID, "delta": delta,
        }))
        if scenario == "approval_request":
            _emit({
                "id": 9001,
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": _THREAD_ID, "reason": "synthetic approval request"},
            })
            return 0
        response_id = request_id + 1 if scenario == "wrong_request_id" else request_id
        _emit(_response(response_id, {"turn": turn}))
        if scenario == "foreign_turn_after_ack":
            _emit(_event("turn/started", {
                "threadId": _THREAD_ID,
                "turn": {"id": "foreign-turn-48b", "items": [], "status": "inProgress"},
            }))
            return 0
        status = "interrupted" if scenario == "interrupted" else "completed"
        terminal = _event("turn/completed", {
            "threadId": _THREAD_ID,
            "turn": {"id": _TURN_ID, "items": [], "status": status},
        })
        _emit(terminal)
        if scenario == "duplicate_terminal":
            _emit(terminal)
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args(argv)
    allowed = {
        "success", "malformed_json", "oversized_output", "wrong_request_id",
        "truncated_jsonl", "duplicate_json_keys",
        "approval_request", "foreign_thread", "foreign_turn", "duplicate_terminal",
        "foreign_turn_after_ack",
        "broken_pipe_before_turn", "partial_client_send_before_turn",
        "die_after_turn_request", "timeout_after_turn_request",
        "interrupted", "echo_prompt", "model_mismatch", "output_flood",
    }
    if args.scenario not in allowed:
        return 2
    try:
        return serve(args.scenario)
    except Exception:
        # Keep fixture output silent and sanitized; the parent reports a fixed error.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
