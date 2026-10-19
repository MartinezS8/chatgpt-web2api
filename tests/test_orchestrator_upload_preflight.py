from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.upload_preflight import UploadPreflight

SHA="a"*64


class FakePackages:
    def __init__(self,store,root):self.store,self.blob_root=store,root
    def read(self,task_id,verify_blobs=True):
        assert verify_blobs
        return {"package_sha256":"b"*64,"attachments":[
            {"name":"a.md","sha256":SHA,"size":4,"media_type":"text/markdown"},
            {"name":"b.py","sha256":"c"*64,"size":8,"media_type":"text/x-python"}]}

class Caps:
    def __init__(self,**changes):self.changes=changes
    def snapshot(self,worker_id,task_id):
        d={"transport":"mock","worker_id":worker_id,"model":"GPT-6","effort":"High",
           "upload_supported":True,"available_apps":["GitHub"],
           "selected_apps_this_message":["GitHub"],"user_approval_pending":False}
        d.update(self.changes);return d

class Uploader:
    def __init__(self,corrupt=False):self.corrupt=corrupt;self.seen=[]
    def upload(self,att,path):
        self.seen.append(path)
        return {"remote_id":"fake:"+att["sha256"],"sha256":("oops" if self.corrupt else att["sha256"]),
                "size":att["size"],"media_type":att["media_type"]}

@pytest.fixture
def inputs(tmp_path):
    store=Store(tmp_path/"db.sqlite")
    store.create(TaskSpec("t1","p","implement","prompt"))
    with store._connect() as d:
        d.executescript("""CREATE TABLE orchestrator_workers(worker_id TEXT PRIMARY KEY,transport TEXT,enabled INTEGER);
            CREATE TABLE orchestrator_worker_assignments(task_id TEXT,worker_id TEXT,state TEXT);""")
        d.execute("INSERT INTO orchestrator_workers VALUES('w1','mock',1)")
        d.execute("INSERT INTO orchestrator_worker_assignments VALUES('t1','w1','active')")
    # Use an actual fenced pre-send claim; a manually asserted 'reserved'
    # state lacks the token/lease required by the upload intent ledger.
    assert store.claim("p") is not None
    root=tmp_path/"blobs";root.mkdir()
    return store,UploadPreflight(store,FakePackages(store,root))


def run(gate,caps=None,uploader=None):
    return gate.check_mock(task_id="t1",worker_id="w1",model="GPT-6",effort="High",
        required_apps=("GitHub",),capability=caps or Caps(),uploader=uploader or Uploader())


def test_exact_two_file_mock_receipt_and_seal(inputs):
    _,gate=inputs;uploader=Uploader()
    result=run(gate,uploader=uploader)
    assert result["created"] and not result["live_send_permitted"]
    assert result["attachment_count"]==2
    assert all(str(gate.packages.blob_root) in p for p in uploader.seen)
    assert not run(gate)["created"]
    assert gate.get("t1")["assurance"]=="offline_mock_only"


def test_repeat_sealed_mock_preflight_never_reuploads(inputs):
    _, gate = inputs
    initial = Uploader()
    assert run(gate, uploader=initial)["created"]
    assert len(initial.seen) == 2
    repeated = Uploader()
    result = run(gate, uploader=repeated)
    assert result["created"] is False
    assert result["attachment_count"] == 2
    assert repeated.seen == []


def test_changed_preflight_capabilities_rejected_before_reupload(inputs):
    _, gate = inputs
    assert run(gate, uploader=Uploader())["created"]
    changed = Uploader()
    with pytest.raises(ValueError, match="sealed preflight"):
        run(gate, caps=Caps(available_apps=["GitHub", "ExtraMockApp"]),
            uploader=changed)
    assert changed.seen == []


@pytest.mark.parametrize("caps,match",[
    (Caps(model="GPT-5.6"),"model/effort"),
    (Caps(effort="Medium"),"model/effort"),
    (Caps(available_apps=[]),"required apps"),
    (Caps(selected_apps_this_message=[]),"required apps"),
    (Caps(user_approval_pending=True),"interactive approval"),
    (Caps(transport="chatgpt_ui"),"nonmock"),
    (Caps(upload_supported=False),"does not support uploads")])
def test_unknown_capability_blocks_before_remote_upload(inputs,caps,match):
    _,gate=inputs;upload=Uploader()
    with pytest.raises(ValueError,match=match):run(gate,caps=caps,uploader=upload)
    assert upload.seen==[]


def test_corrupt_receipt_denied(inputs):
    _,gate=inputs
    with pytest.raises(ValueError,match="mismatched"):
        run(gate,uploader=Uploader(corrupt=True))
    assert gate.get("t1") is None


def test_unassigned_or_disabled_mock_worker_denied(inputs):
    store,gate=inputs
    with store._connect() as d:d.execute("UPDATE orchestrator_workers SET enabled=0 WHERE worker_id='w1'")
    with pytest.raises(ValueError,match="not assigned"):
        run(gate)


def test_reservation_changed_rejects_receipts(inputs):
    store,gate=inputs
    class Disruption(Uploader):
        def upload(self,att,path):
            with store._connect() as d:d.execute("UPDATE tasks SET state='needs_human' WHERE task_id='t1'")
            return super().upload(att,path)
    with pytest.raises(ValueError,match="stale reservation"):
        run(gate,uploader=Disruption())
    assert gate.get("t1") is None



def test_parallel_preflight_only_one_mock_upload_sequence(inputs):
    import time
    from concurrent.futures import ThreadPoolExecutor

    _, gate = inputs
    class SlowUploader(Uploader):
        def upload(self, att, path):
            time.sleep(0.015)
            return super().upload(att, path)

    uploader = SlowUploader()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _try_mock_preflight(gate, uploader), range(16)))
    assert sum(isinstance(x, dict) and x["created"] for x in results) == 1
    assert len(uploader.seen) == 2  # exactly one 2-file sequence
    assert all(isinstance(x, dict) or "reconciliation" in x for x in results)
    assert gate.get("t1")["assurance"] == "offline_mock_only"


def _try_mock_preflight(gate, uploader):
    try:
        return run(gate, uploader=uploader)
    except ValueError as exc:
        return str(exc)


def test_uncertain_mock_upload_never_retries(inputs):
    _, gate = inputs
    class TimeoutUploader(Uploader):
        def upload(self, att, path):
            self.seen.append(path)
            raise TimeoutError("remote may have accepted file")

    uploader = TimeoutUploader()
    with pytest.raises(TimeoutError):
        run(gate, uploader=uploader)
    assert len(uploader.seen) == 1
    assert gate.intents.get("t1")["status"] == "unknown"
    retry = Uploader()
    with pytest.raises(ValueError, match="reconciliation"):
        run(gate, uploader=retry)
    assert retry.seen == []
    assert gate.get("t1") is None


def test_stale_claim_cannot_replay_previous_mock_receipts(inputs):
    store, gate = inputs
    assert run(gate)["created"]
    with store._connect() as db:
        db.execute("UPDATE tasks SET claim_token='rotated' WHERE task_id='t1'")
    repeated = Uploader()
    # The durable upload-intent authority rejects the rotated fencing token
    # before another mock upload, even if an earlier receipt was sealed.
    with pytest.raises(ValueError, match="not ready for this fenced claim"):
        run(gate, uploader=repeated)
    assert repeated.seen == []
    assert gate.get("t1") is not None
