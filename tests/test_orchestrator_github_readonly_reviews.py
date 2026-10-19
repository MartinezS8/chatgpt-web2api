"""Offline negative and success tests for real GitHub review read contracts."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from chatgpt_web2api.orchestrator.github_readonly_reviews import (
    GitHubReadOnlyReviews, GitHubReviewsHTTP, _NoRedirect,
)

SHA = 'b' * 40


def review(review_id=1, uid=44, login='reviewer', state='APPROVED', sha=SHA,
           when='2026-10-19T12:00:00Z'):
    return {'id': review_id, 'user': {'id': uid, 'login': login}, 'state': state,
            'commit_id': sha, 'submitted_at': when}


class Provider:
    def __init__(self, *, repo=None, pr=None, reviews=None, perm=None, move_head=False):
        self.calls = []
        self.pr_reads = 0
        self.repo = {'id': 137, 'full_name': 'Acme/repo'} if repo is None else repo
        self.pr = ({'number': 7, 'state': 'open', 'merged': False, 'draft': False,
                    'base': {'repo': {'id': 137}}, 'head': {'sha': SHA},
                    'user': {'id': 13}} if pr is None else pr)
        self.reviews = [review()] if reviews is None else reviews
        self.perm = {'permission': 'write', 'user': {'id': 44}} if perm is None else perm
        self.move_head = move_head

    def __call__(self, path):
        self.calls.append(path)
        if path == '/repos/Acme/repo':
            return self.repo
        if path == '/repos/Acme/repo/pulls/7':
            self.pr_reads += 1
            if self.move_head and self.pr_reads == 2:
                return {**self.pr, 'head': {'sha': 'a' * 40}}
            return self.pr
        if path == '/repos/Acme/repo/pulls/7/reviews?per_page=100&page=1':
            return self.reviews
        if path.startswith('/repos/Acme/repo/collaborators/') and path.endswith('/permission'):
            return self.perm
        raise AssertionError(f'Unexpected GET: {path}')


def inspect(provider=None, **kwargs):
    provider = provider or Provider()
    gate = GitHubReadOnlyReviews(owner='Acme', repo='repo', repository_id=137,
        trusted_reviewer_ids=frozenset({44, 45}), reader=provider,
        now=lambda: 100.0, **kwargs)
    return gate.inspect(pr_number=7, expected_head_sha=SHA,
                        implementer_user_id=55)


def test_success_read_only_and_recheck_order():
    provider = Provider()
    data = asdict(inspect(provider))
    assert data['head_sha'] == SHA
    assert data['reviewer_ids'] == (44,)
    assert data['review_ids'] == (1,)
    assert data['observed_at'] == 100.0
    assert data['assurance'] == 'provider_read_only_review_unfinalized'
    assert data['production_finalization_permitted'] is False
    assert data['live_send_permitted'] is False
    assert provider.calls == ['/repos/Acme/repo', '/repos/Acme/repo/pulls/7',
         '/repos/Acme/repo/pulls/7/reviews?per_page=100&page=1',
         '/repos/Acme/repo/collaborators/reviewer/permission',
         '/repos/Acme/repo/pulls/7']


@pytest.mark.parametrize('replacement', [
    {'id': 138, 'full_name': 'Acme/repo'},
    {'id': 137, 'full_name': 'Other/repo'},
    {'id': '137', 'full_name': 'Acme/repo'},
])
def test_repository_identity_fails_closed(replacement):
    with pytest.raises(ValueError, match='repository identity'):
        inspect(Provider(repo=replacement))


@pytest.mark.parametrize('field,value', [
    ('state','closed'), ('merged',True), ('draft',True),
    ('base', {'repo':{'id':138}}), ('head',{'sha':'c'*40}),
    ('user',{'id':0}),
])
def test_bad_pr_state_author_sha_or_repository(field,value):
    base=Provider().pr
    with pytest.raises(ValueError, match='PR head, author or state'):
        inspect(Provider(pr={**base,field:value}))


@pytest.mark.parametrize('reviews,error', [
    ([], 'insufficient'),
    ([review(state='PENDING')], 'insufficient'),
    ([review(state='COMMENTED')], 'insufficient'),
    ([review(uid=13)], 'insufficient'),  # PR creator cannot approve
    ([review(uid=55)], 'insufficient'),  # implementer cannot approve
    ([review(uid=99)], 'insufficient'),  # not trusted reviewer
    ([review(sha='c'*40)], 'insufficient'),  # stale commit approval
    ([review(state='DISMISSED')], 'insufficient'),
    ([review(state='CHANGES_REQUESTED')], 'unresolved'),
    ([review(state='UNKNOWN')], 'unknown review state'),
    ([review(review_id=0)], 'invalid review identity'),
    ([review(when='yesterday')], 'malformed review submission time'),
    ([review(when='2026-10-19T12:00:00')], 'missing timezone'),
    ([review(), review(review_id=1)], 'invalid review identity'),
    ([review(), review(review_id=2, state='DISMISSED')], 'insufficient'),
    ([review(), review(review_id=2,state='CHANGES_REQUESTED')], 'unresolved'),
    ([review(), review(review_id=2,state='COMMENTED')], None),
])
def test_review_state_and_commit_fencing(reviews,error):
    if error is None:
        assert inspect(Provider(reviews=reviews)).review_ids == (1,)
    else:
        with pytest.raises(ValueError, match=error):
            inspect(Provider(reviews=reviews))


def test_second_reviewer_can_block_earlier_approval():
    seq=[review(),review(review_id=2,uid=45,login='second',state='CHANGES_REQUESTED')]
    with pytest.raises(ValueError,match='unresolved'):
        inspect(Provider(reviews=seq))


def test_latest_reviewer_clears_own_change_request():
    seq=[review(state='CHANGES_REQUESTED'),review(review_id=2,state='APPROVED')]
    assert inspect(Provider(reviews=seq)).review_ids==(2,)


@pytest.mark.parametrize('permission', [
    {'permission':'read','user':{'id':44}},
    {'permission':'none','user':{'id':44}},
    {'permission':'write','user':{'id':45}},
    {'permission':'admin','user':{'id':'44'}},
    {},
])
def test_permission_must_be_authoritative(permission):
    with pytest.raises(ValueError,match='not independently authorized'):
        inspect(Provider(perm=permission))


def test_admin_permission_accepted():
    assert inspect(Provider(perm={'permission':'admin','user':{'id':44}})).reviewer_ids==(44,)


def test_pr_head_moving_between_reviews_and_second_read_rejected():
    with pytest.raises(ValueError,match='PR head'):
        inspect(Provider(move_head=True))


def test_incomplete_history_always_rejected():
    with pytest.raises(ValueError,match='history incomplete'):
        inspect(Provider(reviews=[review(review_id=x+1) for x in range(100)]))


def test_review_list_type_rejected():
    with pytest.raises(ValueError,match='history incomplete'):
        inspect(Provider(reviews={'items':[review()]}))


def test_required_two_distinct_reviewers():
    seq=[review(),review(2,45,'second')]
    # Provider provides permission mapping based on login; both need independent proof.
    class TwoProvider(Provider):
        def __call__(self,path):
            if path.endswith('/collaborators/second/permission'):
                self.calls.append(path)
                return {'permission':'write','user':{'id':45}}
            return super().__call__(path)
    assert inspect(TwoProvider(reviews=seq),required_approvals=2).reviewer_ids==(44,45)
    with pytest.raises(ValueError,match='insufficient'):
        inspect(Provider(reviews=[review()]),required_approvals=2)


def test_review_history_out_of_order_denied():
    seq=[review(when='2026-10-19T13:00:00Z'), review(2,44,'reviewer',when='2026-10-19T11:00:00Z')]
    with pytest.raises(ValueError,match='order changed'):
        inspect(Provider(reviews=seq))


@pytest.mark.parametrize('name,repo_id,trusted,needed',[
    ('../attacker',137,frozenset({44}),1),
    ('Acme',0,frozenset({44}),1),
    ('Acme',True,frozenset({44}),1),
    ('Acme',137,frozenset(),1),
    ('Acme',137,frozenset({True}),1),
    ('Acme',137,frozenset({44}),2),
    ('Acme',137,frozenset({44}),False),
])
def test_bad_config_denied(name,repo_id,trusted,needed):
    with pytest.raises(ValueError):
        GitHubReadOnlyReviews(owner=name,repo='repo',repository_id=repo_id,
                              trusted_reviewer_ids=trusted,reader=Provider(),required_approvals=needed)


@pytest.mark.parametrize('pr,sha,implementer',[
    (False,SHA,55), (0,SHA,55), (7,'x'*40,55), (7,SHA,True), (7,SHA,0),
])
def test_bad_request_denied(pr,sha,implementer):
    gate=GitHubReadOnlyReviews(owner='Acme',repo='repo',repository_id=137,
                    trusted_reviewer_ids=frozenset({44}),reader=Provider())
    with pytest.raises(ValueError,match='invalid review request'):
        gate.inspect(pr_number=pr,expected_head_sha=sha,implementer_user_id=implementer)


def test_http_read_only_exact_endpoints_no_credential_leak():
    client=GitHubReviewsHTTP(token='test-secret')
    for path in ['https://evil.net', '/repos/Acme/repo/pulls/7/reviews?per_page=200&page=1',
                 '/repos/Acme/repo/pulls/7/reviews?per_page=100&page=2',
                 '/repos/Acme/repo/pulls/7/comments',
                 '/repos/Acme/repo/collaborators/../permission',
                 '/repos/Acme/repo/issues/1',
                 '/repos/Acme/repo/../../../evil',
                 '/repos/Acme/repo/actions/runs/99']:
        with pytest.raises(ValueError,match='not permitted'):
            client(path)
    with pytest.raises(ValueError,match='redirect'):
        _NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil')
