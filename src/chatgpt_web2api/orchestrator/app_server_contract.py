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
    requested_cwd: str | None = field(default=None, init=False)
    early_turn_id: str | None = field(default=None, init=False)
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
        self.requested_cwd = cwd
        return self._request(
            "thread/start",
            {"model": self.model, "cwd": cwd, "sandbox": "read-only",
             "approvalPolicy": "on-request"},
            "thread_pending",
        )

    def turn_start(self, prompt: str) -> dict:
        if self.state != "thread_ready" or not _nonempty(prompt):
            self._reject("turn requires a thread and nonempty test input")
        return self._request(
            "turn/start",
            {"threadId": self.thread_id, "input": [{"type": "text", "text": prompt}],
             "model": self.model, "effort": self.effort,
             "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
             "approvalPolicy": "on-request"},
            "turn_pending",
        )

    def _verify_initialize(self, payload: Any) -> None:
        required = ("codexHome", "platformFamily", "platformOs", "userAgent")
        if not isinstance(payload, dict) or any(not _nonempty(payload.get(k)) for k in required):
            self._reject("initialize response does not match the generated schema")

    def _verify_model(self, payload: Any) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            self._reject("model/list response has no capability list")
        offered = [entry for entry in payload["data"]
                   if isinstance(entry, dict) and
                   entry.get("id") == self.model and entry.get("model") == self.model]
        if len(offered) != 1:
            self._reject("requested model is unavailable or ambiguous")
        model = offered[0]
        if (model.get("hidden") is not False or type(model.get("isDefault")) is not bool
                or not _nonempty(model.get("displayName"))
                or not _nonempty(model.get("description"))
                or not _nonempty(model.get("defaultReasoningEffort"))):
            self._reject("model catalog entry does not match the generated schema")
        efforts = model.get("supportedReasoningEfforts")
        if not isinstance(efforts, list):
            self._reject("server did not attest supported reasoning efforts")
        if any(not isinstance(entry, dict)
               or not _nonempty(entry.get("reasoningEffort"))
               or not _nonempty(entry.get("description")) for entry in efforts):
            self._reject("model effort entry does not match the generated schema")
        names = [entry["reasoningEffort"] for entry in efforts]
        if self.effort not in names:
            self._reject("requested reasoning effort was not attested")

    def _verify_thread(self, payload: Any) -> None:
        required = ("approvalPolicy", "cwd", "model", "modelProvider", "sandbox", "thread")
        if (not isinstance(payload, dict) or any(key not in payload for key in required)
                or "approvalsReviewer" not in payload):
            self._reject("thread/start response does not match the generated schema")
        if (payload["cwd"] != self.requested_cwd or payload["model"] != self.model
                or payload["sandbox"] != "read-only"
                or payload["approvalPolicy"] != "on-request"
                or not _nonempty(payload["modelProvider"])):
            self._reject("thread/start response does not match the requested binding")
        thread = payload["thread"]
        if (not isinstance(thread, dict) or not _nonempty(thread.get("id"))
                or not _nonempty(thread.get("sessionId"))):
            self._reject("thread/start did not return valid thread and session ids")
        if self.thread_id is not None:
            self._reject("cannot replace an existing thread")
        self.thread_id = thread["id"]
        self.session_id = thread["sessionId"]

    def _verify_turn(self, payload: Any) -> None:
        turn = payload.get("turn") if isinstance(payload, dict) else None
        if (not isinstance(turn, dict) or not _nonempty(turn.get("id"))
                or turn.get("status") != "inProgress" or not isinstance(turn.get("items"), list)):
            self._reject("turn was not acknowledged with a valid in-progress response")
        if self.early_turn_id is not None and self.early_turn_id != turn["id"]:
            self._reject("pre-ack turn notification id mismatch")
        self.turn_id = turn["id"]
        self.early_turn_id = None

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
            self._verify_initialize(result)
            next_state = "initialize_ack"
        elif method == "model/list":
            self._verify_model(result)
            next_state = "model_verified"
        elif method == "thread/start":
            self._verify_thread(result)
            next_state = "thread_ready"
        elif method == "turn/start":
            self._verify_turn(result)
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
        # Validate thread association even on progress/approval-adjacent events.
        if ("threadId" in params and self.thread_id is not None
                and params["threadId"] != self.thread_id):
            self._reject("notification belongs to a different thread")
        if (method.startswith(("turn/", "item/"))
                and (self.thread_id is None or params.get("threadId") != self.thread_id)):
            self._reject("notification is missing its bound thread id")
        event_turn_id = params.get("turnId")
        expected_turn_id = self.turn_id or self.early_turn_id
        if (event_turn_id is not None and expected_turn_id is not None
                and event_turn_id != expected_turn_id):
            self._reject("notification belongs to a different turn")
        if method.startswith("item/") and (
            expected_turn_id is None or event_turn_id != expected_turn_id
        ):
            self._reject("item notification is missing its bound turn id")
        if method == "turn/started" and self.state == "turn_pending":
            turn = params.get("turn")
            if (params.get("threadId") != self.thread_id or not isinstance(turn, dict)
                    or not _nonempty(turn.get("id"))
                    or turn.get("status") != "inProgress"
                    or not isinstance(turn.get("items"), list)):
                self._reject("invalid pre-ack turn notification")
            if self.early_turn_id is not None and self.early_turn_id != turn["id"]:
                self._reject("inconsistent pre-ack turn ids")
            self.early_turn_id = turn["id"]
            return "pending_turn_ack"
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
