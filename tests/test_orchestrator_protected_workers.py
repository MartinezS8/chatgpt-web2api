"""Policy-bound worker scheduling and dispatch recovery, using only mock workers."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

import chatgpt_web2api.orchestrator.storage_policy as storage_policy_module
from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.private_workspace import PrivateStorageContext
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec


@pytest.mark.parametrize("worker_count", (1, 2, 5))
def test_protected_mock_workers_claim_unique_slots_and_never_resend_unknown(
    tmp_path, monkeypatch, worker_count
):
    root = tmp_path / "private-workspace"
    root.mkdir()
    root = root.resolve(strict=True)
    blobs = root / "blobs"
    blobs.mkdir()
    inputs = root / "inputs"
    inputs.mkdir()
    context = PrivateStorageContext(root, root / "controller.sqlite3", blobs)

    def fake_native_loader(label: str) -> PrivateStorageContext:
        assert label == "portable-test"
        return context

    monkeypatch.setattr(
        storage_policy_module, "load_private_workspace", fake_native_loader
    )
    policy = storage_policy_module.PrivateStoragePolicy.open("portable-test")

    store = Store(context.database, storage_policy=policy)
    packages = TaskPackages(store, context.blobs)
    workers = WorkerRegistry(store)
    for index in range(worker_count):
        assert workers.register(
            WorkerSpec(
                f"worker-{index}", "account", "project", "implement", "mock",
                f"fake:worker-{index}",
            )
        )

    package_hashes: dict[str, str] = {}
    expected_attachment_hashes: dict[str, str] = {}
    for index in range(worker_count + 1):
        task_id = f"task-{index}"
        prompt = f"synthetic prompt {index}"
        store.create(TaskSpec(task_id, "project", "implement", prompt))
        source = inputs / f"{task_id}.txt"
        content = f"synthetic attachment {index}".encode()
        source.write_bytes(content)

        sealed = packages.seal(task_id, prompt, [source], allowed_root=inputs)
        reopened_package = packages.read(task_id, verify_blobs=True)
        expected_blob_hash = hashlib.sha256(content).hexdigest()
        assert sealed["package_sha256"] == reopened_package["package_sha256"]
        assert reopened_package["attachments"][0]["sha256"] == expected_blob_hash
        package_hashes[task_id] = sealed["package_sha256"]
        expected_attachment_hashes[task_id] = expected_blob_hash

    assert len(set(package_hashes.values())) == worker_count + 1
    assert len(set(expected_attachment_hashes.values())) == worker_count + 1

    scheduler = Scheduler(store, workers, packages)
    with ThreadPoolExecutor(max_workers=5) as pool:
        candidates = list(
            pool.map(
                lambda _index: scheduler.claim_next(
                    "account", "project", max_slots=worker_count
                ),
                range(worker_count + 2),
            )
        )
    claims = [claim for claim in candidates if claim is not None]

    assert len(claims) == worker_count
    assert len({claim["task"]["task_id"] for claim in claims}) == worker_count
    assert len({claim["task"]["claim_token"] for claim in claims}) == worker_count
    assert len({claim["worker_id"] for claim in claims}) == worker_count
    assert sorted(claim["task"]["slot"] for claim in claims) == list(
        range(1, worker_count + 1)
    )
    assert all(claim["remote_send_permitted"] is False for claim in claims)

    outbox = DispatchOutbox(store, packages)
    receipts: dict[str, dict] = {}
    for claim in claims:
        task = claim["task"]
        task_id = task["task_id"]
        assert packages.read(task_id)["package_sha256"] == package_hashes[task_id]
        arguments = {
            "task_id": task_id,
            "worker_id": claim["worker_id"],
            "claim_token": task["claim_token"],
        }
        receipt = outbox.begin_mock_for_assignment(**arguments)
        assert receipt["new_send_permit"] is True
        assert receipt["remote_send_permitted"] is False
        assert receipt["status"] == "intent"
        repeated = outbox.begin_mock_for_assignment(**arguments)
        assert repeated["attempt_id"] == receipt["attempt_id"]
        assert repeated["new_send_permit"] is False
        assert repeated["remote_send_permitted"] is False
        assert outbox.get(receipt["attempt_id"])["package_sha256"] == package_hashes[
            task_id
        ]
        assert outbox.mark_unknown(receipt["attempt_id"])
        receipts[task_id] = {**receipt, **arguments}

    pending_ids = {f"task-{index}" for index in range(worker_count + 1)} - set(
        receipts
    )
    assert len(pending_ids) == 1
    pending_id = pending_ids.pop()
    assert store.get(pending_id)["state"] == TaskState.QUEUED.value
    assert all(
        store.get(task_id)["state"] == TaskState.UNKNOWN_DELIVERY.value
        for task_id in receipts
    )

    reopened_store = Store(context.database, storage_policy=policy)
    reopened_packages = TaskPackages(reopened_store, context.blobs)
    reopened_workers = WorkerRegistry(reopened_store)
    reopened_outbox = DispatchOutbox(reopened_store, reopened_packages)
    for task_id, receipt in receipts.items():
        arguments = {
            "task_id": task_id,
            "worker_id": receipt["worker_id"],
            "claim_token": receipt["claim_token"],
        }
        reopened_package = reopened_packages.read(task_id, verify_blobs=True)
        assert reopened_package["package_sha256"] == package_hashes[task_id]
        repeated = reopened_outbox.begin_mock_for_assignment(**arguments)
        assert repeated["attempt_id"] == receipt["attempt_id"]
        assert repeated["status"] == "unknown"
        assert repeated["new_send_permit"] is False
        assert repeated["remote_send_permitted"] is False
        assert reopened_outbox.get(receipt["attempt_id"])["package_sha256"] == (
            package_hashes[task_id]
        )

    assert len(reopened_outbox.events()) == worker_count * 2
    assert sum(event["kind"] == "dispatch.intent" for event in reopened_outbox.events()) == worker_count
    assert sum(event["kind"] == "delivery.unknown" for event in reopened_outbox.events()) == worker_count
    assert Scheduler(reopened_store, reopened_workers, reopened_packages).claim_next(
        "account", "project", max_slots=worker_count
    ) is None
