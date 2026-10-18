"""Transport-neutral controller. No browser driver is imported or invoked."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .store import Store, TaskState


@dataclass(frozen=True)
class DeliveryAck:
    conversation_id: str
    delivery_id: str


@dataclass(frozen=True)
class TransportResult:
    status: Literal["running", "completed", "unknown"]
    conversation_id: str
    delivery_id: str
    evidence_ref: str | None = None


class Transport(Protocol):
    def send(self, task: dict, prompt: str) -> DeliveryAck:
        """Use exactly one bound session and return a confirmed user message ID."""

    def poll(self, task: dict) -> TransportResult:
        """Read a previously confirmed session; NEVER cause a new send."""


class Verifier(Protocol):
    def verify(self, task: dict, result: TransportResult) -> bool:
        """Verify independent immutable evidence (commit SHA / CI / DB)."""


class RejectByDefaultVerifier:
    def verify(self, task: dict, result: TransportResult) -> bool:
        # Do NOT accept self-reported completion as proof of code changes.
        return False


class Controller:
    def __init__(self, store: Store, transport: Transport,
                 verifier: Verifier | None = None):
        self.store = store
        self.transport = transport
        self.verifier = verifier or RejectByDefaultVerifier()

    def dispatch(self, project_id: str, prompt_by_task_id: dict[str, str], max_slots: int = 5):
        """Dispatch one task. Call in an event loop, not an unbounded busy loop."""
        task = self.store.claim(project_id, max_slots=max_slots)
        if task is None:
            return None
        task_id = task["task_id"]
        expected_prompt = prompt_by_task_id.get(task_id)
        if not expected_prompt:
            # Never send a missing/wrong prompt. This becomes an explicit
            # operator intervention, rather than silently substituting text.
            self.store.transition(task_id, TaskState.RESERVED, TaskState.NEEDS_HUMAN,
                                  error="prompt package missing before send")
            return task_id
        import hashlib
        if hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest() != task["prompt_sha"]:
            self.store.transition(task_id, TaskState.RESERVED, TaskState.NEEDS_HUMAN,
                                  error="prompt checksum mismatch; nothing sent")
            return task_id
        self.store.transition(task_id, TaskState.RESERVED, TaskState.DISPATCHING)
        try:
            ack = self.transport.send(task, expected_prompt)
            if not ack.conversation_id or not ack.delivery_id:
                raise RuntimeError("ambiguous send acknowledgment")
            self.store.transition(task_id, TaskState.DISPATCHING, TaskState.IN_PROGRESS,
                                  conversation_id=ack.conversation_id,
                                  delivery_id=ack.delivery_id)
        except Exception as exc:
            # This may have happened after the website accepted the request.
            # Never automatically re-send; reconcile by inspecting the chat.
            self.store.transition(task_id, TaskState.DISPATCHING, TaskState.UNKNOWN_DELIVERY,
                                  error=f"send uncertain: {type(exc).__name__}")
        return task_id

    def poll(self, project_id: str):
        completed = []
        for task in self.store.all(project_id):
            if task["state"] != TaskState.IN_PROGRESS.value:
                continue
            try:
                result = self.transport.poll(task)
            except Exception:
                # A failed poll is not proof of failed generation or delivery.
                continue
            if (result.conversation_id != task["conversation_id"] or
                    result.delivery_id != task["delivery_id"]):
                self.store.transition(task["task_id"], TaskState.IN_PROGRESS,
                                      TaskState.UNKNOWN_DELIVERY,
                                      error="result correlation mismatch")
                continue
            if result.status != "completed":
                continue
            self.store.transition(task["task_id"], TaskState.IN_PROGRESS,
                                  TaskState.RESULT_RECEIVED, evidence_ref=result.evidence_ref)
            try:
                verified = bool(result.evidence_ref and self.verifier.verify(task, result))
            except Exception:
                verified = False
            if verified:
                self.store.transition(task["task_id"], TaskState.RESULT_RECEIVED,
                                      TaskState.VERIFIED)
                # Implementation finished means evidence validated, NOT approved
                # for merging. Independent review and PR gates remain external.
                self.store.transition(task["task_id"], TaskState.VERIFIED,
                                      TaskState.FINISHED)
                completed.append(task["task_id"])
            else:
                self.store.transition(task["task_id"], TaskState.RESULT_RECEIVED,
                                      TaskState.NEEDS_HUMAN,
                                      error="independent evidence verification missing/failed")
        return completed