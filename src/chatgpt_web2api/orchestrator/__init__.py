"""Local, transport-neutral multi-agent orchestration core.

No ChatGPT automation, account login, connector execution or web requests are
performed by this package. It is an additive overlay for an upstream fork.
"""
from .callback_policy import Callback, CallbackPolicy
from .controller import Controller, Transport, TransportResult, Verifier
from .evidence import CheckEvidence, EvidenceReader, EvidenceVerdict, PullRequestEvidence, ReviewEvidence
from .review_policy import ReviewPolicy, ReviewRequest
from .outbox import DispatchOutbox
from .resource_registry import ResourceIdentity, ResourceRegistry
from .scheduler import Scheduler
from .store import Store, TaskSpec, TaskState
from .supervisor import Supervisor
from .task_packages import TaskPackages
from .worker_registry import WorkerRegistry, WorkerSpec

__all__ = [
    "Controller", "DispatchOutbox", "ResourceIdentity", "ResourceRegistry",
    "Store", "TaskPackages", "TaskSpec", "TaskState", "Transport",
    "TransportResult", "Verifier", "Scheduler", "Supervisor", "WorkerRegistry", "WorkerSpec",
    "Callback", "CallbackPolicy", "CheckEvidence", "EvidenceReader", "EvidenceVerdict",
    "PullRequestEvidence", "ReviewEvidence", "ReviewPolicy", "ReviewRequest",
]