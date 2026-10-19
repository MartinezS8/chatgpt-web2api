"""Local, transport-neutral multi-agent orchestration core.

No ChatGPT automation, account login, connector execution or web requests are
performed by this package. It is an additive overlay for an upstream fork.
"""
from .callback_inbox import CallbackInbox
from .controller import Controller, Transport, TransportResult, Verifier
from .evidence import EvidenceLedger, GitHubEvidenceProbe
from .planner import Planner
from .provider_evidence import ProviderEvidenceLedger
from .github_readonly_reviews import GitHubReadOnlyReviews, GitHubReviewsHTTP, ReviewObservation
from .review_policy import ReviewLedger
from .outbox import DispatchOutbox
from .resource_registry import ResourceIdentity, ResourceRegistry
from .scheduler import Scheduler
from .store import Store, TaskSpec, TaskState
from .supervisor import Supervisor
from .task_packages import TaskPackages
from .upload_intents import UploadIntents
from .upload_preflight import UploadPreflight
from .worker_registry import WorkerRegistry, WorkerSpec

__all__ = [
    "UploadPreflight", "CallbackInbox", "EvidenceLedger", "GitHubEvidenceProbe", "Planner", "ReviewLedger",
    "Controller", "DispatchOutbox", "ProviderEvidenceLedger", "GitHubReadOnlyReviews", "GitHubReviewsHTTP",
    "ReviewObservation", "ResourceIdentity", "ResourceRegistry",
    "Store", "TaskPackages", "TaskSpec", "TaskState", "Transport",
    "TransportResult", "Verifier", "Scheduler", "Supervisor", "WorkerRegistry", "WorkerSpec", "UploadIntents",
]