from __future__ import annotations

import tempfile
from pathlib import Path
from dataclasses import replace

import pytest

from chatgpt_web2api.orchestrator.evidence import (
    CheckEvidence, PullRequestEvidence, ReviewEvidence, github_result_ref, verify_github_review,
)
from chatgpt_web2api.orchestrator.review_policy import ReviewPolicy, ReviewRequest
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState

SHA = "1" * 40
OLD = "2" * 40


def snapshot():
    return PullRequestEvidence(
        repository_id=123, pull_number=17, head_sha=SHA, author_user_id=7,
        state="open", is_draft=False,
        checks=(CheckEvidence("tests/linux", SHA, "success"),
                CheckEvidence("tests/windows", SHA, "success")),
        reviews=(ReviewEvidence(9, "APPROVED", SHA),),
    )


class FakeReader:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def get_pull_request(self, repository_id, pull_number):
        self.calls += 1
        return self.data


def verdict(data=None, **kwargs):
    return verify_github_review(data or snapshot(), repository_id=123, pull_number=17,
                                expected_sha=SHA,
                                required_checks=("tests/linux", "tests/windows"), **kwargs)


def test_exact_head_checks_and_independent_current_review():
    assert verdict().approved
    assert verdict(allowed_reviewers=frozenset({9})).approved
    assert not verdict(allowed_reviewers=frozenset({99})).approved
    assert verdict(replace(snapshot(), head_sha=OLD)).reason == "stale_head_sha"
    assert not verdict(replace(snapshot(), checks=(CheckEvidence("tests/linux", OLD, "success"),))).approved
    assert not verdict(replace(snapshot(), reviews=(ReviewEvidence(7, "APPROVED", SHA),))).approved
    assert not verdict(replace(snapshot(), reviews=(ReviewEvidence(9, "APPROVED", OLD),))).approved
    assert not verdict(replace(snapshot(), reviews=(ReviewEvidence(9, "APPROVED", SHA),
                                                     ReviewEvidence(9, "CHANGES_REQUESTED", SHA)))).approved
    assert verdict(replace(snapshot(), reviews=(ReviewEvidence(9, "APPROVED", SHA),
                                                     ReviewEvidence(10, "CHANGES_REQUESTED", SHA)))).reason == "outstanding_changes_requested"
    assert not verdict(replace(snapshot(), is_draft=True)).approved
    assert not verdict(replace(snapshot(), state="closed")).approved
    assert not verify_github_review(snapshot(), repository_id=123, pull_number=17,
                                    expected_sha=SHA, required_checks=()).approved


def test_evidence_ref_validation():
    assert github_result_ref(123, 17, SHA) == f"github:123:pr:17:sha:{SHA}"
    with pytest.raises(ValueError):
        github_result_ref(123, 17, "invalid")


def test_db_gate_requires_verified_task_and_records_without_finalizing():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "controller.sqlite")
        store.create(TaskSpec("t", "p", "implement", "task"))
        policy = ReviewPolicy(store)
        request = ReviewRequest("t", 123, 17, SHA, ("tests/linux", "tests/windows"))
        reader = FakeReader(snapshot())
        assert policy.assess(request, reader).reason == "task_not_verified"
        assert reader.calls == 0
        reserved = store.claim("p")
        token = reserved["claim_token"]
        assert store.transition("t", TaskState.RESERVED, TaskState.DISPATCHING, claim_token=token)
        assert store.transition("t", TaskState.DISPATCHING, TaskState.IN_PROGRESS, claim_token=token)
        assert store.transition("t", TaskState.IN_PROGRESS, TaskState.RESULT_RECEIVED,
                                claim_token=token, evidence_ref=github_result_ref(123, 17, SHA))
        assert store.transition("t", TaskState.RESULT_RECEIVED, TaskState.VERIFIED, claim_token=token)
        assert policy.assess(request, reader).approved
        assert store.get("t")["state"] == "verified"
        assert len(policy.recorded("t")) == 1
        assert policy.assess(request, reader).approved
        assert len(policy.recorded("t")) == 1
        mismatched = replace(request, expected_head_sha=OLD)
        assert policy.assess(mismatched, reader).reason == "task_evidence_ref_mismatch"
        assert len(policy.recorded("t")) == 1