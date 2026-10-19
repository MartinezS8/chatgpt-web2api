"""Task-scoped GitHub reviewer observation regression tests (mock provider only)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from test_orchestrator_github_readonly_reviews import Provider, review
from test_orchestrator_provider_evidence import (
    SHA,
    STAMP,
    FakeReader,
    gate,
    inspect,
)

from chatgpt_web2api.orchestrator.github_readonly_reviews import (
    GitHubReadOnlyReviews,
)
from chatgpt_web2api.orchestrator.provider_evidence import ProviderEvidenceLedger
from chatgpt_web2api.orchestrator.task_review_evidence import TaskReviewEvidenceLedger


class Reviewer(Provider):
    def __init__(self, *args, mutation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pr["head"]["sha"] = SHA
        self.reviews = [dict(review(), commit_id=SHA)]
        self.mutation = mutation

    def __call__(self, path):
        if self.move_head and path == '/repos/Acme/repo/pulls/7' and self.pr_reads == 1:
            self.calls.append(path)
            self.pr_reads += 1
            return {**self.pr, 'head': {'sha': 'b' * 40}}
        if self.mutation and path.endswith('/reviews?per_page=100&page=1'):
            mutate = self.mutation
            self.mutation = None
            mutate()
        return super().__call__(path)


def create(store, *, reader=None, now=STAMP, implementer=55):
    reader = reader or Reviewer()
    ci = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    review_gate = GitHubReadOnlyReviews(
        owner='Acme', repo='repo', repository_id=137,
        trusted_reviewer_ids=frozenset({44, 45}),
        reader=reader, now=lambda: now)
    ledger = TaskReviewEvidenceLedger(
        store, ci, review_gate, trusted_implementer_user_id=implementer,
        now=lambda: now)
    return ledger, ci, reader


def seed(store):
    ledger, ci, reader = create(store)
    inspect(ci)
    return ledger, ci, reader


def record(ledger, task='impl', attempt='attempt-1'):
    return ledger.inspect_and_record(task_id=task, attempt_id=attempt)


def test_success_is_immutable_and_does_not_finalize_or_unlock(store):
    ledger, ci, reader = seed(store)
    result = record(ledger)
    assert result['new'] and result['reviewer_ids'] == [44]
    assert result['assurance'] == 'provider_read_only_review_unfinalized'
    assert not result['production_finalization_permitted']
    assert result['ci_digest'] == ci.get('impl')['digest']
    assert ledger.get('impl')['package_sha256'] == ci.get('impl')['package_sha256']
    assert store.get('impl')['state'] == 'result_received'
    assert store.get('impl')['slot'] == 1
    assert [x['kind'] for x in store.events('impl')].count('review.provider_observed') == 1
    assert not ledger.production_finalization_permitted('impl')
    again = record(ledger)
    assert not again['new'] and again['digest'] == result['digest']
    assert [x['kind'] for x in store.events('impl')].count('review.provider_observed') == 1
    assert len(reader.calls) >= 5
    reopened = create(store)[0]
    assert reopened.get('impl')['digest'] == result['digest']


def test_missing_ci_fails_before_review_api_is_called(store):
    ledger, _, reader = create(store)
    with pytest.raises(ValueError, match='CI observation required'):
        record(ledger)
    assert not reader.calls and ledger.get('impl') is None


@pytest.mark.parametrize('bad', [
    ('attempt', 'wrong'), ('task', 'other'), ('task', ''), ('attempt', ''),
])
def test_wrong_task_or_attempt_denied(store, bad):
    ledger, _, reader = seed(store)
    args = {'task':'impl', 'attempt':'attempt-1'}
    args[bad[0]] = bad[1]
    with pytest.raises(ValueError):
        record(ledger, **args)
    assert reader.calls == []


@pytest.mark.parametrize('field,command', [
    ('claim', "UPDATE tasks SET claim_token='rotated' WHERE task_id='impl'"),
    ('version', "UPDATE tasks SET claim_version=claim_version+1 WHERE task_id='impl'"),
    ('state', "UPDATE tasks SET state='needs_human' WHERE task_id='impl'"),
    ('scope', "UPDATE tasks SET write_scopes='[\"github:repo/138\"]' WHERE task_id='impl'"),
    ('package', "UPDATE orchestrator_task_packages SET package_sha256='fake' WHERE task_id='impl'"),
    ('dispatch', "UPDATE orchestrator_dispatch_attempts SET status='unknown' WHERE task_id='impl'"),
    ('result', "UPDATE orchestrator_dispatch_attempts SET result_ref='wrong' WHERE task_id='impl'"),
    ('ci_head', "UPDATE orchestrator_provider_observations SET head_sha='bbbb' WHERE task_id='impl'"),
    ('ci_digest', "UPDATE orchestrator_provider_observations SET digest='tampered' WHERE task_id='impl'"),
])
def test_mutated_binding_or_ci_rejected_before_review_get(store, field, command):
    ledger, _, reader = seed(store)
    with store._connect() as db:
        db.execute(command)
    with pytest.raises(ValueError):
        record(ledger)
    assert reader.calls == [] and ledger.get('impl') is None


def test_task_changes_during_external_review_rejected(store):
    ledger, ci, _ = seed(store)
    def mutate():
        with store._connect() as db:
            db.execute("UPDATE tasks SET claim_version=claim_version+1 WHERE task_id='impl'")
    other = create(store, reader=Reviewer(mutation=mutate))[0]
    with pytest.raises(ValueError, match='changed during review|does not match'):
        record(other)
    assert ledger.get('impl') is None


def test_ci_changes_during_review_rejected(store):
    ledger, _, _ = seed(store)
    def mutate():
        with store._connect() as db:
            db.execute("UPDATE orchestrator_provider_observations SET run_id=500 WHERE task_id='impl'")
    other = create(store, reader=Reviewer(mutation=mutate))[0]
    with pytest.raises(ValueError, match='digest invalid'):
        record(other)
    assert ledger.get('impl') is None


def test_review_provider_does_not_authorize_on_changed_head(store):
    seed(store)
    reader = Reviewer(move_head=True)
    ledger = create(store, reader=reader)[0]
    with pytest.raises(ValueError, match='PR head'):
        record(ledger)
    assert ledger.get('impl') is None


def test_reviewer_not_permitted_or_self_review_rejected(store):
    seed(store)
    reader = Reviewer(perm={'permission':'read','user':{'id':44}})
    ledger = create(store, reader=reader)[0]
    with pytest.raises(ValueError, match='not independently authorized'):
        record(ledger)
    assert ledger.get('impl') is None
    ledger2 = create(store, implementer=44)[0]
    with pytest.raises(ValueError, match='insufficient'):
        record(ledger2)


def test_controller_policy_and_repo_binding_must_be_trusted(store):
    ci = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    gate_other_repo = GitHubReadOnlyReviews(owner='Acme',repo='repo',repository_id=138,
        trusted_reviewer_ids=frozenset({44}),reader=Reviewer())
    with pytest.raises(ValueError, match='same trusted repository'):
        TaskReviewEvidenceLedger(store, ci, gate_other_repo, trusted_implementer_user_id=55)
    real_gate = GitHubReadOnlyReviews(owner='Acme',repo='repo',repository_id=137,
        trusted_reviewer_ids=frozenset({44}),reader=Reviewer())
    with pytest.raises(ValueError, match='trusted implementation'):
        TaskReviewEvidenceLedger(store, ci, real_gate, trusted_implementer_user_id=0)


def test_stale_ci_snapshot_denied_before_read(store):
    ledger, _, reader = seed(store)
    with store._connect() as db:
        db.execute("UPDATE orchestrator_provider_observations SET observed_at=?",(STAMP-130,))
    with pytest.raises(ValueError, match='stale'):
        record(ledger)
    assert reader.calls == []


def test_old_review_snapshot_time_denied(store):
    seed(store)
    ledger = create(store)[0]
    # Override the network adapter with a controlled stale observation.
    actual = ledger.reviewer.inspect
    ledger.reviewer.inspect = lambda **kwargs: replace(actual(**kwargs), observed_at=STAMP-121)
    with pytest.raises(ValueError, match='cannot authorize'):
        record(ledger)
    assert ledger.get('impl') is None


def test_attempt_cannot_be_replaced_after_observation(store):
    ledger, ci, _ = seed(store)
    before = record(ledger)
    with store._connect() as db:
        db.execute("UPDATE orchestrator_provider_review_observations SET digest='corrupt' WHERE task_id='impl'")
    with pytest.raises(ValueError, match='already sealed'):
        record(ledger)
    assert before['digest'] != ledger.get('impl')['digest']


def test_16_concurrent_observations_create_one_event(store):
    ledger, _, _ = seed(store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _: record(ledger), range(16)))
    assert sum(row['new'] for row in receipts) == 1
    assert len(set(r['digest'] for r in receipts)) == 1
    assert [e['kind'] for e in store.events('impl')].count('review.provider_observed') == 1
