"""Offline-only Codex App Server protocol contract.

No IO, process invocation, GitHub mutations, approvals, dispatch permits,
or persistence. A future transport must persist correlation and authorization
*before* writing any wire bytes and treat ambiguous delivery as unknown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ProtocolRejected(ValueError):
    """Untrusted or out-of-order app-server traffic is not accepted."""


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass
class OfflineAppServerContract:
    """In-memory verifier for one synthetic thread and one synthetic turn.

    Generated request dictionaries are test fixtures, not permissions to send.
    Terminal completion is never code evidence, review, or task finalization.
    """

    model: str
    effort: str
    state: str = field(default="new", init=False)
    pending: tuple[int, str] | None = field(default=None, init=False)
    thread_id: str | None = field(default=None, init=False)
    turn_id: str | None = field(default=None, init=False)
    session_id: str | None = field(default=None, init=False)
    terminal_status: str | None = field(default=None, init=False)
    sequence: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not _nonempty(self.model) or not _nonempty(self.effort):
            raise ProtocolRejected("exact requested model and effort are required")

    @property
    def live_send_permitted(self) -> bool:
        return False

    @property
    def production_finalization_permitted(self) -> bool:
        return False

    def _reject(self, why: str) -> None:
        self.state = "needs_human"
        self.pending = None
        raise ProtocolRejected(why)

    def _request(self, method: str, params: dict, target_state: str) -> dict:
        if self.pending is not None:
            self._reject("previous request has no confirmed response")
        self.sequence += 1
        self.pending = (self.sequence, method)
        self.state = target_state
        return {"id": self.sequence, "method": method, "params": params}

    def initialize(self) -> dict:
        if self.state != "new":
            self._reject("initialize is only legal once")
        return self._request(
            "initialize",
            {"clientInfo": {"name": "local_orchestrator_offline_contract",
                            "title": "Offline Orchestrator Contract", "version": "0.1.0"}},
            "initialize_pending",
        )

    def initialized(self) -> dict:
        if self.state != "initialize_ack" or self.pending is not None:
            self._reject("initialized notification requires successful handshake")
        self.state = "ready_for_models"
        return {"method": "initialized", "params": {}}

    def model_list(self) -> dict:
        if self.state != "ready_for_models":
            self._reject("model discovery must follow initialization")
        return self._request(
            "model/list", {"limit": 100, "includeHidden": False}, "models_pending"
        )

    def thread_start(self, *, cwd: str) -> dict:
        if self.state != "model_verified" or not _nonempty(cwd):
            self._reject("thread requires exact model/effort and explicit cwd")
        return self._request(
            "thread/start",
            {"model": self.model, "cwd": cwd, "sandbox": "readOnly"},
            "thread_pending",
        )

    def turn_start(self, prompt: str) -> dict:
        if self.state != "thread_ready" or not _nonempty(prompt):
            self._reject("turn requires a thread and nonempty test input")
        return self._request(
            "turn/start",
            {"threadId": self.thread_id, "input": [{"type": "text", "text": prompt}],
             "model": self.model, "effort": self.effort,
             "sandboxPolicy": {"type": "readOnly"}, "approvalPolicy": "never"},
            "turn_pending",
        )

    def _verify_model(self, payload: Any) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            self._reject("model/list response has no capability list")
        offered = [entry for entry in payload["data"]
                   if isinstance(entry, dict) and
                   entry.get("model", entry.get("id")) == self.model and
                   entry.get("hidden") is not True]
        if len(offered) != 1:
            self._reject("requested model is unavailable or ambiguous")
        efforts = offered[0].get("supportedReasoningEfforts")
        if not isinstance(efforts, list):
            self._reject("server did not attest supported reasoning efforts")
        names = [entry.get("reasoningEffort") for entry in efforts
                 if isinstance(entry, dict)]
        if self.effort not in names:
            self._reject("requested reasoning effort was not attested")

    def receive_response(self, message: Any) -> str:
        if not isinstance(message, dict) or self.pending is None:
            self._reject("unexpected app-server response")
        request_id, method = self.pending
        if type(message.get("id")) is not int or message["id"] != request_id:
            self._reject("app-server response id mismatch")
        if "error" in message or not isinstance(message.get("result"), dict):
            self._reject("server rejected request or omitted result")
        result = message["result"]
        if method == "initialize":
            next_state = "initialize_ack"
        elif method == "model/list":
            self._verify_model(result)
            next_state = "model_verified"
        elif method == "thread/start":
            thread = result.get("thread")
            if not isinstance(thread, dict) or not _nonempty(thread.get("id")):
                self._reject("thread/start did not return a thread id")
            if self.thread_id is not None:
                self._reject("cannot replace an existing thread")
            self.thread_id = thread["id"]
            sid = thread.get("sessionId", thread["id"])
            if not _nonempty(sid):
                self._reject("invalid session id")
            self.session_id = sid
            next_state = "thread_ready"
        elif method == "turn/start":
            turn = result.get("turn")
            if not isinstance(turn, dict) or not _nonempty(turn.get("id")):
                self._reject("turn/start did not return a turn id")
            if turn.get("status") != "inProgress":
                self._reject("turn was not acknowledged as in progress")
            self.turn_id = turn["id"]
            next_state = "turn_active"
        else:
            self._reject("unknown pending request")
        self.pending = None
        self.state = next_state
        return next_state

    def receive_event(self, message: Any) -> str:
        if not isinstance(message, dict) or not _nonempty(message.get("method")):
            self._reject("invalid app-server event")
        if "id" in message:
            self._reject("server-initiated request requires explicit approval handling")
        method = message["method"]
        params = message.get("params")
        if not isinstance(params, dict):
            self._reject("event must contain params")
        # Other progress notifications may contain model output or secrets:
        # do not persist or return their content from this contract.
        if method != "turn/completed":
            return "ignored_unverified"
        if self.state != "turn_active":
            self._reject("completion without acknowledged active turn")
        turn = params.get("turn")
        if (params.get("threadId") != self.thread_id or not isinstance(turn, dict)
                or turn.get("id") != self.turn_id):
            self._reject("completion belongs to a different thread or turn")
        status = turn.get("status")
        if status not in {"completed", "failed", "interrupted"}:
            self._reject("unknown terminal turn status")
        self.terminal_status = status
        self.state = ("transport_completed_unverified" if status == "completed"
                      else "needs_human")
        return self.state
