"""Synthetic completion is distinct from production finalization."""
from contextlib import contextmanager

import pytest

from chatgpt_web2api.orchestrator.mock_sandbox import MockSandbox
from chatgpt_web2api.orchestrator.offline_demo import execute_demo
from chatgpt_web2api.orchestrator.private_workspace import PrivateStorageContext
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store
from chatgpt_web2api.orchestrator.task_packages import TaskPackages


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    # Unit contract only: real SQLite and services, native ACL/pin layer stubbed.
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    context = PrivateStorageContext(tmp_path, tmp_path / "controller.sqlite3", blobs)
    monkeypatch.setattr("chatgpt_web2api.orchestrator.storage_policy.load_private_workspace",
                        lambda label: context)

    @contextmanager
    def checked_session(self, path, **kwargs):
        self.database(path)
        yield

    monkeypatch.setattr(PrivateStoragePolicy, "database_session", checked_session)
    monkeypatch.setattr(PrivateStoragePolicy, "database_initialization", checked_session)
    policy = PrivateStoragePolicy.open("unit-demo")
    store = Store(context.database, storage_policy=policy)
    packages = TaskPackages(store, blobs)
    demo = MockSandbox(store, packages, nonce="unit-nonce", create=True)
    demo.initialize()
    return demo


def test_five_distinct_workers_and_synthetic_completion_without_finalizer(sandbox):
    result = sandbox.run()
    assert result["status"] == "demo_complete"
    assert result["mock_completed"] == 5
    assert result["workers_used"] == 5
    assert result["production_finalization_permitted"] is False
    assert len(sandbox.workers.list("offline-demo")) == 5
    assert {row["state"] for row in sandbox.store.all("offline-demo")} == {"verified"}
    assert len({row["slot"] for row in sandbox.store.all("offline-demo")}) == 5
    with pytest.raises(PermissionError):
        sandbox.store.finalize_verified("01-a", claim_token="fake", reviewer_ref="fake",
                                        approved_by="fake")


def test_restart_idempotence_and_event_cursor(sandbox):
    first = sandbox.run()
    event_count = len(sandbox.outbox.events())
    reopened = MockSandbox(sandbox.store, sandbox.packages, nonce="unit-nonce")
    again = reopened.run()
    assert again["status"] == "demo_complete"
    assert first["event_cursor"] == again["event_cursor"]
    assert len(reopened.outbox.events()) == event_count
    assert reopened.outbox.consumer_events("offline-demo") == []


def test_unknown_delivery_survives_restart_without_new_intent(sandbox):
    claimed = sandbox.claim_wave()[0]
    intent = sandbox.prepare_intent(claimed)
    assert intent["new_send_permit"]
    reopened = MockSandbox(sandbox.store, sandbox.packages, nonce="unit-nonce")
    result = reopened.run()
    assert result["status"] == "needs_human"
    assert reopened.store.get(claimed["task"]["task_id"])["state"] == "unknown_delivery"
    assert not reopened.outbox.begin_mock_for_assignment(
        task_id=claimed["task"]["task_id"], worker_id=claimed["worker_id"],
        claim_token=claimed["task"]["claim_token"])["new_send_permit"]
    events = len(reopened.outbox.events())
    assert reopened.run()["status"] == "needs_human"
    assert len(reopened.outbox.events()) == events


def test_default_scheduler_never_uses_synthetic_completion(sandbox):
    wave = sandbox.claim_wave()
    assert len(wave) == 2
    for claim in wave:
        sandbox.execute_claim(claim)
    default = Scheduler(sandbox.store, sandbox.workers, sandbox.packages)
    assert default.claim_next("offline-demo", "offline-demo") is None
    assert len(sandbox.claim_wave()) == 2


def test_legacy_store_and_forged_sandbox_rejected(tmp_path, sandbox):
    legacy = Store(tmp_path / "legacy.sqlite3")
    with pytest.raises(ValueError, match="protected"):
        MockSandbox(legacy, TaskPackages(legacy, tmp_path / "legacy-blobs"), nonce="x")
    with pytest.raises((TypeError, ValueError)):
        Scheduler(sandbox.store, sandbox.workers, sandbox.packages).claim_next(
            "offline-demo", "offline-demo", mock_sandbox=object())
    with pytest.raises(ValueError, match="nonce"):
        MockSandbox(sandbox.store, sandbox.packages, nonce="wrong")


@pytest.mark.parametrize("table,field", [
    ("tasks", "claim_version"), ("orchestrator_worker_assignments", "claim_version")])
def test_changed_fence_invalidates_synthetic_dependency(sandbox, table, field):
    for claim in sandbox.claim_wave():
        sandbox.execute_claim(claim)
    with sandbox.store._connect() as db:
        db.execute(f"UPDATE {table} SET {field}={field}+1 WHERE task_id='01-a'")
    assert sandbox.run()["status"] == "needs_human"
    assert len(sandbox.outbox.events()) == 6


def test_mismatched_session_cannot_upload_or_create_intent(sandbox):
    claim = sandbox.claim_wave()[0]
    claim["session_key"] = "fake:wrong-session"
    with pytest.raises(ValueError, match="session snapshot"):
        sandbox.prepare_intent(claim)
    assert sandbox.preflight.intents.get(claim["task"]["task_id"]) is None
    assert sandbox.outbox.events() == []


def test_changed_snapshot_on_restart_is_rejected_before_any_new_intent(sandbox):
    sandbox.run()
    blob = next(path for path in sandbox.packages.blob_root.iterdir() if len(path.name) == 64)
    blob.write_bytes(b"changed")
    events = len(sandbox.outbox.events())
    with pytest.raises(ValueError, match="snapshot|content"):
        sandbox.run()
    assert len(sandbox.outbox.events()) == events


def test_no_demo_lock_or_db_mutation_without_owned_marker(sandbox):
    root = sandbox.store.storage_policy.context.root
    before = sandbox.store.storage_policy.context.database.read_bytes()
    with pytest.raises(FileNotFoundError):
        execute_demo(action="status", label="unit-demo")
    assert not (root / ".offline-demo.lock").exists()
    assert sandbox.store.storage_policy.context.database.read_bytes() == before


@pytest.mark.parametrize("mutation", ["worker_session", "attempt_conversation", "task_delivery"])
def test_session_or_delivery_drift_invalidates_demo_receipts(sandbox, mutation):
    sandbox.run()
    with sandbox.store._connect() as db:
        if mutation == "worker_session":
            db.execute("UPDATE orchestrator_workers SET session_key='fake:drifted' WHERE worker_id='mock-1'")
        elif mutation == "attempt_conversation":
            db.execute("UPDATE orchestrator_dispatch_attempts SET conversation_id='fake:drifted' WHERE task_id='01-a'")
        else:
            db.execute("UPDATE tasks SET delivery_id='fake:drifted' WHERE task_id='01-a'")
        assert "01-a" not in sandbox.completed_locked(db, "offline-demo")
    assert sandbox.run()["status"] == "needs_human"
