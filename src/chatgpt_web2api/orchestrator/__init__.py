"""Local, transport-neutral multi-agent orchestration core.

No ChatGPT automation, account login, connector execution or web requests are
performed by this package. It is an additive overlay for an upstream fork.
"""
from .store import Store, TaskSpec, TaskState
from .controller import Controller, Transport, TransportResult, Verifier

__all__ = ["Store", "TaskSpec", "TaskState", "Controller", "Transport", "TransportResult", "Verifier"]