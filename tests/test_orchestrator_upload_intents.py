from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.upload_intents import UploadIntents


class SealedFakePackages:
    def __init__(self, store, root, attachments=None):
        self.store, self.blob_root = store, root
        self.attachments = attachments if attachments is not None else [
            {"name": "first.md", "sha256": "a" * 64, "size": 4, "media_type": "text/markdown"},
            {"name": "second.py", "sha256": "b" * 64, "size": 8, "media_type": "text/x-python"},
        ]

    def read(self, task_id, verify_blobs=True):
        assert verify_blobs
        return {"package_sha256": "c" * 64, "attachments": self.attachments}


@pytest.fixture
def item(tmp_path):
    db = Store(tmp_path / "controller.sqlite")
    db.create(TaskSpec("task-1", "project", "implement", "prompt"))
    with db._connect() as con:
        con.executescript("""CREATE TABLE orchestrator_workers (
          worker_id TEXT PRIMARY KEY, role TEXT, transport TEXT, enabled INTEGER);
          CREATE TABLE orchestrator_worker_assignments (task_id TEXT,worker_id TEXT,state TEXT);
        """)
        con.execute("INSERT INTO orchestrator_workers VALUES('worker-1','implement','mock',1)")
        con.execute("INSERT INTO orchestrator_worker_assignments VALUES('task-1','worker-1','active')")
    token = db.claim("project")["claim_token"]
    packages = SealedFakePackages(db,tmp_path)
    gate = UploadIntents(db, packages)
    return SimpleNamespace(db=db, token=token, packages=packages, gate=gate, path=db.path)


def reserve(i):
    return i.gate.reserve(task_id="task-1", worker_id="worker-1", claim_token=i.token)


def nextpart(i, uid):
    return i.gate.reserve_next(task_id="task-1", upload_id=uid, worker_id="worker-1", claim_token=i.token)


def ack(i, uid, att, **override):
    receipt = {"remote_id":"fake:"+att["sha256"],"sha256":att["sha256"],
               "media_type":att["media_type"],"size":att["size"]}
    receipt.update(override)
    return i.gate.acknowledge(task_id="task-1",upload_id=uid,worker_id="worker-1",
                              claim_token=i.token,attachment_sha256=att["sha256"],receipt=receipt)


def test_reserve_has_no_live_send_permission(item):
    a=reserve(item)
    assert a["created"] and not a["live_send_permitted"]
    assert a["assurance"] == "offline_mock_only"
    assert reserve(item)["created"] is False
    assert reserve(item)["upload_id"] == a["upload_id"]


def test_two_files_sequentially_acknowledged(item):
    uid=reserve(item)["upload_id"]
    a=nextpart(item,uid)
    with pytest.raises(ValueError, match="already in flight"):
        nextpart(item,uid)
    assert ack(item,uid,a)
    assert not ack(item,uid,a)
    b=nextpart(item,uid)
    assert b["sha256"] != a["sha256"]
    assert ack(item,uid,b)
    assert nextpart(item,uid) is None
    assert item.gate.get("task-1")["status"] == "ready_mock"
    assert all(r["state"]=="acked" for r in item.gate.receipts("task-1"))


def test_wrong_receipt_does_not_ack_or_unlock(item):
    uid=reserve(item)["upload_id"]
    att=nextpart(item,uid)
    with pytest.raises(ValueError,match="mismatched"):
        ack(item,uid,att,sha256="z"*64)
    assert item.gate.receipts("task-1")[0]["state"] == "inflight"
    assert item.gate.quarantine(task_id="task-1",upload_id=uid)
    assert not item.gate.quarantine(task_id="task-1",upload_id=uid)
    with pytest.raises(ValueError,match="reconciliation"):
        nextpart(item,uid)
    with pytest.raises(ValueError,match="not authorized"):
        ack(item,uid,att)
    assert reserve(item)["status"] == "unknown"


def test_unique_reservation_under_concurrency(item):
    with ThreadPoolExecutor(max_workers=8) as pool:
        res=list(pool.map(lambda _:reserve(item),range(16)))
    assert sum(bool(r["created"]) for r in res)==1
    assert len({r["upload_id"] for r in res})==1
    uid=res[0]["upload_id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        res2=list(pool.map(lambda _: _attempt_next(item,uid),range(16)))
    assert sum(r=="reserved" for r in res2)==1
    assert sum(r=="busy" for r in res2)==15


def _attempt_next(item,uid):
    try:
        p=nextpart(item,uid)
        return "reserved" if p else "none"
    except ValueError as exc:
        if "already in flight" in str(exc):
            return "busy"
        raise


def test_crash_restart_never_reallocates_upload(item):
    uid=reserve(item)["upload_id"]
    first=nextpart(item,uid)
    after=UploadIntents(item.db,item.packages)
    assert after.get("task-1")["upload_id"]==uid
    with pytest.raises(ValueError,match="already in flight"):
        after.reserve_next(task_id="task-1",upload_id=uid,worker_id="worker-1",claim_token=item.token)
    assert after.quarantine(task_id="task-1",upload_id=uid)
    with pytest.raises(ValueError,match="reconciliation"):
        nextpart(item,uid)


def test_rejects_stale_claim(item):
    uid=reserve(item)["upload_id"]
    with pytest.raises(ValueError,match="stale reservation"):
        item.gate.reserve(task_id="task-1",worker_id="worker-1",claim_token="other")
    with item.db._connect() as db:
        db.execute("UPDATE tasks SET claim_token='rotated' WHERE task_id='task-1'")
    with pytest.raises(ValueError,match="stale reservation"):
        nextpart(item,uid)


def test_rejects_disabled_worker(item):
    with item.db._connect() as db:
        db.execute("UPDATE orchestrator_workers SET enabled=0")
    with pytest.raises(ValueError,match="untrusted mock"):
        reserve(item)


def test_no_files_is_ready_but_never_live(item):
    item.packages.attachments=[]
    a=reserve(item)
    assert a["status"]=="ready_mock" and not a["live_send_permitted"]
    assert nextpart(item,a["upload_id"]) is None
    assert item.gate.receipts("task-1")==[]


def test_prevent_duplicate_remote_id(item):
    uid=reserve(item)["upload_id"]
    first=nextpart(item,uid)
    assert ack(item,uid,first)
    second=nextpart(item,uid)
    with pytest.raises(Exception):
        ack(item,uid,second,remote_id="fake:"+first["sha256"])
    assert item.gate.receipts("task-1")[1]["state"] == "inflight"


def test_invalid_manifest_fail_closed(item):
    item.packages.attachments.append(dict(item.packages.attachments[0]))
    with pytest.raises(ValueError,match="duplicate attachment"):
        reserve(item)
    assert item.gate.get("task-1") is None

class MockUploader:
    def __init__(self, *, fail=False):
        self.fail=fail
        self.calls=[]

    def upload(self, att, path):
        self.calls.append((att["sha256"],path))
        if self.fail:
            raise TimeoutError("acknowledgment lost after potential remote commit")
        return {"remote_id": "fake:"+att["sha256"], "sha256":att["sha256"],
                "media_type":att["media_type"], "size":att["size"]}


def test_perform_mock_uploads_is_sequential_and_once(item):
    adapter=MockUploader()
    replies=item.gate.perform_mock(task_id="task-1",worker_id="worker-1",
                                   claim_token=item.token,uploader=adapter)
    assert len(replies)==2
    assert len(adapter.calls)==2
    another=MockUploader()
    with pytest.raises(ValueError,match="no re-upload"):
        item.gate.perform_mock(task_id="task-1",worker_id="worker-1",
                               claim_token=item.token,uploader=another)
    assert another.calls==[]


def test_perform_mock_timeout_quarantines_and_never_resends(item):
    first=MockUploader(fail=True)
    with pytest.raises(TimeoutError):
        item.gate.perform_mock(task_id="task-1",worker_id="worker-1",
                               claim_token=item.token,uploader=first)
    assert len(first.calls)==1
    assert item.gate.get("task-1")["status"]=="unknown"
    next_attempt=MockUploader()
    with pytest.raises(ValueError,match="no re-upload"):
        item.gate.perform_mock(task_id="task-1",worker_id="worker-1",
                               claim_token=item.token,uploader=next_attempt)
    assert next_attempt.calls==[]
