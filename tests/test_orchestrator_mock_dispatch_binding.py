"""Assignment-bound offline dispatch intents: no real provider calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec


@pytest.fixture
def assigned(tmp_path):
    store = Store(tmp_path / "orchestrator.sqlite")
    workers = WorkerRegistry(store)
    packages = TaskPackages(store, tmp_path / "blobs")
    assert store.create(TaskSpec("task-1", "project-1", "implement", "safe mock prompt"))
    assert workers.register(
        WorkerSpec("worker-1", "account-1", "project-1", "implement",
                   "mock", "fake:worker-1")
    )
    packages.seal("task-1", "safe mock prompt")
    claimed = Scheduler(store, workers, packages).claim_next("account-1", "project-1")
    assert claimed is not None
    assert claimed["worker_id"] == "worker-1"
    return store, workers, DispatchOutbox(store, packages), claimed["task"]["claim_token"]


def _begin(assigned, *, worker_id="worker-1", claim_token=None):
    _, _, outbox, token = assigned
    return outbox.begin_mock_for_assignment(
        task_id="task-1", worker_id=worker_id,
        claim_token=token if claim_token is None else claim_token
    )


def test_valid_assignment_creates_exactly_one_offline_intent(assigned):
    store, _, outbox, _ = assigned
    first = _begin(assigned)
    assert first["new_send_permit"] is True
    assert first["remote_send_permitted"] is False
    assert first["assurance"] == "offline_mock_only"
    assert store.get("task-1")["state"] == TaskState.DISPATCHING.value
    again = _begin(assigned)
    assert again["attempt_id"] == first["attempt_id"]
    assert again["new_send_permit"] is False
    assert again["remote_send_permitted"] is False
    assert len(outbox.events()) == 1


@pytest.mark.parametrize("worker_id", ["other-worker", "", "worker-2"])
def test_wrong_or_missing_worker_never_starts_dispatch(assigned, worker_id):
    store, _, outbox, _ = assigned
    with pytest.raises(ValueError):
        _begin(assigned, worker_id=worker_id)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value
    assert outbox.events() == []


def test_disabled_worker_fails_closed_but_assignment_is_preserved(assigned):
    store, workers, outbox, _ = assigned
    assert workers.set_enabled("worker-1", False)
    with pytest.raises(ValueError, match="enabled matching mock worker"):
        _begin(assigned)
    assert len(workers.assignments("account-1")) == 1
    assert store.get("task-1")["state"] == TaskState.RESERVED.value
    assert outbox.events() == []
    assert workers.set_enabled("worker-1", True)
    assert _begin(assigned)["new_send_permit"] is True
    assert workers.set_enabled("worker-1", False)
    with pytest.raises(ValueError, match="enabled matching mock worker"):
        _begin(assigned)


def test_released_or_wrong_role_assignment_is_rejected(assigned):
    store, _, outbox, _ = assigned
    with store._connect() as db:
        db.execute("UPDATE orchestrator_worker_assignments SET state='released' "
                   "WHERE task_id='task-1'")
    with pytest.raises(ValueError, match="enabled matching mock worker"):
        _begin(assigned)
    assert outbox.events() == []


def test_wrong_role_or_project_on_worker_is_rejected(assigned):
    store, _, outbox, _ = assigned
    with store._connect() as db:
        db.execute("UPDATE orchestrator_workers SET role='review' "
                   "WHERE worker_id='worker-1'")
    with pytest.raises(ValueError, match="enabled matching mock worker"):
        _begin(assigned)
    assert outbox.events() == []


def test_stale_assignment_claim_version_cannot_issue_intent(assigned):
    store, _, outbox, _ = assigned
    with store._connect() as db:
        db.execute("UPDATE orchestrator_worker_assignments "
                   "SET claim_version=claim_version+1 WHERE task_id='task-1'")
    with pytest.raises(ValueError, match="claim version mismatch"):
        _begin(assigned)
    assert outbox.events() == []


def test_expired_reservation_cannot_issue_intent(assigned):
    store, _, outbox, _ = assigned
    with store._connect() as db:
        db.execute("UPDATE tasks SET lease_until=0 WHERE task_id='task-1'")
    with pytest.raises(ValueError, match="fenced and unexpired"):
        _begin(assigned)
    assert outbox.events() == []


def test_two_threads_create_one_fenced_mock_intent(assigned):
    _, _, outbox, _ = assigned
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _begin(assigned), range(2)))
    assert sum(bool(item["new_send_permit"]) for item in outcomes) == 1
    assert all(item["remote_send_permitted"] is False for item in outcomes)
    assert len({item["attempt_id"] for item in outcomes}) == 1
    assert len(outbox.events()) == 1


def test_wrong_claim_does_not_observe_prior_mock_intent(assigned):
    store, _, _, _ = assigned
    first = _begin(assigned)
    with pytest.raises(ValueError, match="different claim"):
        _begin(assigned, claim_token="incorrect-claim")
    assert first["new_send_permit"] is True
    assert store.get("task-1")["state"] == TaskState.DISPATCHING.value
