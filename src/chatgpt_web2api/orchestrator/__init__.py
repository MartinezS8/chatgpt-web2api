"""Local, transport-neutral multi-agent orchestration core.

No ChatGPT automation, account login, connector execution or web requests are
performed by this package. It is an additive overlay for an upstream fork.
"""
from .callback_inbox import CallbackInbox
from .controller import Controller, Transport, TransportResult, Verifier
from .evidence import EvidenceLedger, GitHubEvidenceProbe
from .github_readonly_reviews import GitHubReadOnlyReviews, GitHubReviewsHTTP, ReviewObservation
from .implementer_provenance import GitHubSignedCommitReader, ImplementerProvenanceLedger
from .outbox import DispatchOutbox
from .planner import Planner
from .provider_evidence import ProviderEvidenceLedger
from .resource_registry import ResourceIdentity, ResourceRegistry
from .review_policy import ReviewLedger
from .scheduler import Scheduler
from .store import Store, TaskSpec, TaskState
from .supervisor import Supervisor
from .task_packages import TaskPackages
from .task_review_evidence import TaskReviewEvidenceLedger
from .upload_intents import UploadIntents
from .upload_preflight import UploadPreflight
from .worker_registry import WorkerRegistry, WorkerSpec
from .workflow_source_pin import WorkflowSourceObservation, WorkflowSourcePin

__all__ = [
    "UploadPreflight", "CallbackInbox", "EvidenceLedger", "GitHubEvidenceProbe", "Planner", "ReviewLedger",
    "Controller", "DispatchOutbox", "ProviderEvidenceLedger", "GitHubSignedCommitReader", "ImplementerProvenanceLedger", "GitHubReadOnlyReviews", "GitHubReviewsHTTP", "TaskReviewEvidenceLedger",
    "ReviewObservation", "ResourceIdentity", "ResourceRegistry",
    "Store", "TaskPackages", "TaskSpec", "TaskState", "Transport",
    "TransportResult", "Verifier", "Scheduler", "Supervisor", "WorkerRegistry", "WorkerSpec", "UploadIntents",
    "WorkflowSourcePin", "WorkflowSourceObservation",
]