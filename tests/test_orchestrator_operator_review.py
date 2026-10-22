"""Read-only operator reconciliation queue and preview; no approval authority."""
from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.app_server_delivery import AppServerDeliveryLedger
from chatgpt_web2api.orchestrator.app_server_fake import (
    AttemptBinding,
    FakeAppServerScenario,
    OfflineFakeAppServer,
    UnknownDelivery,
)
from chatgpt_web2api.orchestrator.cli import build_parser, execute
from chatgpt_web2api.orchestrator.observer import Observer
from chatgpt_web2api.orchestrator.operator_review import OperatorReviewBoard
from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec


@pytest.fixture
def unknown(tmp_path):
    store = Store(tmp_path / "controller.sqlite3")
    workers = WorkerRegistry(store)
    packages = TaskPackages(store, tmp_path / "blobs")
    store.create(TaskSpec("task-review", "project-review", "implement", "synthetic review"))
    workers.register(WorkerSpec(
        "worker-review", "account-review", "project-review", "implement",
        "mock", "fake:worker-review",
    ))
    packages.seal("task-review", "synthetic review")
    claimed = Scheduler(store, workers, packages).claim_next(
        "account-review", "project-review",
    )
    outbox = DispatchOutbox(store, packages)
    attempt = outbox.begin_mock_for_assignment(
        task_id="task-review", worker_id="worker-review",
        claim_token=claimed["task"]["claim_token"],
    )
    binding = AttemptBinding(
        controller_id="controller-review", worker_id="worker-review",
        account_id="account-review", project_id="project-review",
        task_id="task-review", attempt_id=attempt["attempt_id"],
    )
    ledger = AppServerDeliveryLedger(outbox)
    fake = OfflineFakeAppServer(
        binding, scenario=FakeAppServerScenario.TIMEOUT_AFTER_TURN_REQUEST,
    )
    with pytest.raises(UnknownDelivery):
        ledger.run_fake(
            fake, claim_token=claimed["task"]["claim_token"],
            prompt="synthetic review", cwd="C:/synthetic/worktree",
        )
    assert ledger.get(binding.attempt_id)["status"] == "unknown_delivery"
    return store, binding.attempt_id, ledger


def _review_hash(store):
    with store._connect() as db:
        return {
            "task": tuple(db.execute(
                "SELECT state,claim_version,evidence_ref,approved_by FROM tasks "
                "WHERE task_id='task-review'",
            ).fetchone()),
            "attempts": [tuple(row) for row in db.execute(
                "SELECT attempt_id,status FROM orchestrator_app_server_attempts",
            )],
            "dispatches": [tuple(row) for row in db.execute(
                "SELECT attempt_id,status FROM orchestrator_dispatch_attempts",
            )],
            "annotations": db.execute(
                "SELECT COUNT(*) FROM orchestrator_app_server_operator_dispositions",
            ).fetchone()[0],
        }


def test_queue_shows_quarantine_without_prompts_or_claim_tokens(unknown):
    store, attempt, _ = unknown
    board = OperatorReviewBoard(Observer(store.path))
    data = board.queue()
    assert len(data["items"]) == 1
    assert data["items"][0]["attempt_id"] == attempt
    assert data["items"][0]["status"] == "unknown_delivery"
    assert data["items"][0]["task_state"] == TaskState.UNKNOWN_DELIVERY.value
    assert data["operator_authenticated"] is False
    assert data["resolution_permitted"] is False
    assert data["live_send_permitted"] is False
    serialized = repr(data)
    assert "synthetic review" not in serialized
    assert "fake:worker-review" not in serialized
    assert "claim_token" not in serialized


@pytest.mark.parametrize("disposition", [
    "delivery_unresolved", "delivery_confirmed", "non_delivery_confirmed",
])
def test_every_preview_is_read_only_and_non_authorizing(unknown, disposition):
    store, attempt, _ = unknown
    before = _review_hash(store)
    data = OperatorReviewBoard(Observer(store.path)).preview(
        attempt, disposition=disposition,
    )
    assert data["requested_disposition"] == disposition
    assert data["operator_authenticated"] is False
    assert data["evidence_verified"] is False
    assert data["resolution_permitted"] is False
    assert data["new_attempt_permitted"] is False
    assert data["live_send_permitted"] is False
    assert data["finalization_permitted"] is False
    assert _review_hash(store) == before


def test_previews_never_trust_existing_unauthenticated_annotation(unknown):
    store, attempt, ledger = unknown
    ledger.record_operator_disposition(
        attempt, operator_ref="caller-assertion",
        disposition="delivery_confirmed",
        reason_code="external_evidence_reviewed",
    )
    data = OperatorReviewBoard(Observer(store.path)).preview(
        attempt, disposition="delivery_confirmed",
    )
    assert data["existing_annotation"] is True
    assert data["operator_authenticated"] is False
    assert data["resolution_permitted"] is False
    assert data["evidence_verified"] is False
    assert ledger.get(attempt)["status"] == "unknown_delivery"


def test_cli_queue_and_preview_are_read_only(unknown):
    store, attempt, _ = unknown
    before = _review_hash(store)
    args = build_parser().parse_args([
        "--db", str(store.path), "operator-review-queue", "--limit", "10",
    ])
    assert execute(args)["items"][0]["attempt_id"] == attempt
    args = build_parser().parse_args([
        "--db", str(store.path), "operator-review-preview",
        "--attempt-id", attempt, "--disposition", "non_delivery_confirmed",
    ])
    assert execute(args)["new_attempt_permitted"] is False
    assert _review_hash(store) == before


def test_missing_database_is_not_created_by_review(tmp_path):
    path = tmp_path / "nonexistent.sqlite3"
    args = build_parser().parse_args([
        "--db", str(path), "operator-review-queue",
    ])
    with pytest.raises(FileNotFoundError):
        execute(args)
    assert not path.exists()


def test_missing_ledger_is_empty_in_existing_database(tmp_path):
    store = Store(tmp_path / "existing.sqlite3")
    board = OperatorReviewBoard(Observer(store.path))
    assert board.queue()["items"] == []


@pytest.mark.parametrize("limit", [0, -1, 51, True, 1.5, "10"])
def test_invalid_limits_are_rejected_before_sql(unknown, limit):
    store, _, _ = unknown
    with pytest.raises(ValueError, match="limit"):
        OperatorReviewBoard(Observer(store.path)).queue(limit=limit)


def test_missing_attempt_and_invalid_dispositions_are_rejected(unknown):
    store, attempt, _ = unknown
    board = OperatorReviewBoard(Observer(store.path))
    with pytest.raises(ValueError, match="not found"):
        board.preview("not-an-attempt", disposition="delivery_unresolved")
    with pytest.raises(ValueError, match="unsupported"):
        board.preview(attempt, disposition="approved")


def test_board_requires_genuine_observer(unknown):
    with pytest.raises(TypeError, match="canonical"):
        OperatorReviewBoard(object())
