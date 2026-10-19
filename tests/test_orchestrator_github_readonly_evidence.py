from __future__ import annotations

from dataclasses import asdict

import pytest

from chatgpt_web2api.orchestrator.github_readonly_evidence import (
    GitHubReadOnlyEvidence,
    GitHubReadOnlyHTTP,
    _NeverRedirect,
)

SHA = "1" * 40


class FakeGitHubReader:
    def __init__(self, **overrides):
        self.paths = []
        self.pr_views = 0
        self.overrides = overrides

    def __call__(self, path):
        self.paths.append(path)
        repo = {"id": 137, "full_name": "Acme/repo"}
        pr = {"number": 7, "state": "open", "merged": False,
              "base": {"repo": {"id": 137}},
              "head": {"sha": SHA, "ref": "codex/fix", "repo": {"id": 137}}}
        run = {"id": 99, "repository": {"id": 137}, "workflow_id": 51,
               "head_sha": SHA, "status": "completed", "conclusion": "success",
               "run_attempt": 1, "event": "push", "head_branch": "codex/fix",
               "head_repository": {"id": 137}}
        jobs = {"total_count": 2, "jobs": [
            {"name": n, "run_id": 99, "head_sha": SHA,
             "status": "completed", "conclusion": "success"}
            for n in ("lint", "unit")]}
        if path == "/repos/Acme/repo":
            payload = repo
        elif path == "/repos/Acme/repo/pulls/7":
            self.pr_views += 1
            payload = pr
        elif path == "/repos/Acme/repo/actions/runs/99":
            payload = run
        elif path == "/repos/Acme/repo/actions/runs/99/jobs?filter=latest&per_page=100":
            payload = jobs
        else:
            raise AssertionError(f"unexpected path: {path}")
        changes = self.overrides.get("pr_after" if path.endswith("/pulls/7")
                                     and self.pr_views == 2 else
                                     "repo" if path == "/repos/Acme/repo" else
                                     "pr" if path.endswith("/pulls/7") else
                                     "jobs" if "/jobs?" in path else "run", {})
        if changes:
            payload = {**payload, **changes}
        return payload


def inspect(reader=None, *, workflow_ids=frozenset({51}), sha=SHA):
    reader = reader or FakeGitHubReader()
    gate = GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
                                  trusted_workflow_ids=workflow_ids, reader=reader,
                                  required_job_names=frozenset({"lint", "unit"}),
                                  now=lambda: 1729300000.0)
    return gate.inspect(pr_number=7, expected_head_sha=sha, run_id=99)


def test_exact_repository_pr_head_and_allowlisted_green_run():
    reader = FakeGitHubReader()
    rec = asdict(inspect(reader))
    assert rec["repository_id"] == 137 and rec["run_id"] == 99
    assert rec["workflow_id"] == 51 and rec["verified_at"] == 1729300000.0
    assert rec["assurance"] == "provider_read_only_unreviewed"
    assert rec["event"] == "push" and rec["head_branch"] == "codex/fix"
    assert rec["successful_jobs"] == ("lint", "unit")
    assert not rec["production_finalization_permitted"]
    assert not rec["live_send_permitted"]
    assert reader.paths == ["/repos/Acme/repo", "/repos/Acme/repo/pulls/7",
                            "/repos/Acme/repo/actions/runs/99",
                            "/repos/Acme/repo/actions/runs/99/jobs?filter=latest&per_page=100",
                            "/repos/Acme/repo/pulls/7"]


@pytest.mark.parametrize("section,changes,match", [
    ("repo", {"id": 138}, "repository identity"),
    ("repo", {"full_name": "Attacker/repo"}, "repository identity"),
    ("pr", {"state": "closed"}, "PR head"),
    ("pr", {"merged": True}, "PR head"),
    ("pr", {"head": {"sha": "2" * 40}}, "PR head"),
    ("pr", {"base": {"repo": {"id": 138}}}, "PR head"),
    ("run", {"repository": {"id": 138}}, "workflow evidence"),
    ("run", {"workflow_id": 52}, "workflow evidence"),
    ("run", {"status": "in_progress"}, "workflow evidence"),
    ("run", {"conclusion": "failure"}, "workflow evidence"),
    ("run", {"head_sha": "2" * 40}, "workflow evidence"),
    ("run", {"run_attempt": 0}, "workflow evidence"),
    ("run", {"event": "workflow_dispatch"}, "workflow evidence"),
    ("run", {"event": "pull_request"}, "workflow evidence"),
    ("run", {"head_branch": "other"}, "workflow evidence"),
    ("run", {"head_repository": {"id": 138}}, "workflow evidence"),
    ("jobs", {"total_count": 3}, "job list"),
    ("jobs", {"jobs": []}, "job list"),
    ("jobs", {"jobs": [{"name": "lint", "run_id": 99, "head_sha": SHA,
                         "status": "completed", "conclusion": "success"}] ,
              "total_count": 1}, "required"),
    ("jobs", {"jobs": [{"name": "lint", "run_id": 99, "head_sha": SHA,
                         "status": "completed", "conclusion": "success"},
                        {"name": "unit", "run_id": 99, "head_sha": SHA,
                         "status": "completed", "conclusion": "failure"}]}, "CI job"),
    ("pr_after", {"head": {"sha": "3" * 40}}, "PR head"),
])
def test_rejects_untrusted_or_stale_provider_snapshots(section, changes, match):
    with pytest.raises(ValueError, match=match):
        inspect(FakeGitHubReader(**{section: changes}))


@pytest.mark.parametrize("owner,repo,rid,workflows", [
    ("ac/me", "repo", 137, frozenset({51})),
    ("Acme", "../foo", 137, frozenset({51})),
    ("Acme", "repo", 0, frozenset({51})),
    ("Acme", "repo", True, frozenset({51})),
    ("Acme", "repo", 137, frozenset()),
    ("Acme", "repo", 137, frozenset({True})),
])
def test_rejects_unsafe_authority_configuration(owner, repo, rid, workflows):
    with pytest.raises(ValueError):
        GitHubReadOnlyEvidence(owner=owner, repo=repo, repository_id=rid,
                               trusted_workflow_ids=workflows, reader=FakeGitHubReader(),
                                  required_job_names=frozenset({"lint", "unit"}))


@pytest.mark.parametrize("pr,run,sha", [(0, 99, SHA), (7, False, SHA),
                                       (7, 99, "a" * 39), (7, 99, "G" * 40)])
def test_rejects_malformed_requested_identifiers(pr, run, sha):
    gate = GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
                                  trusted_workflow_ids=frozenset({51}), reader=FakeGitHubReader(),
                                  required_job_names=frozenset({"lint", "unit"}))
    with pytest.raises(ValueError, match="invalid GitHub evidence request"):
        gate.inspect(pr_number=pr, expected_head_sha=sha, run_id=run)


def test_http_reader_disallows_redirects_and_non_pr_paths():
    client = GitHubReadOnlyHTTP()
    for path in ("https://evil.example", "/orgs/a", "/repos/a/b/actions/runs/1/steps",
                 "/repos/a/b/contents/secret", "/repos/a/b/../../../evil"):
        with pytest.raises(ValueError, match="not an allowed read-only endpoint"):
            client(path)
    with pytest.raises(ValueError, match="HTTP redirect"):
        _NeverRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil")


@pytest.mark.parametrize("required,events", [
    (frozenset(), frozenset({"push"})),
    (frozenset({"bad\nname"}), frozenset({"push"})),
    (frozenset({"unit"}), frozenset({"workflow_dispatch"})),
    (frozenset({"unit"}), frozenset({"pull_request"})),
    (frozenset({"unit"}), frozenset()),
])
def test_job_and_event_policy_must_be_explicit_and_safe(required,events):
    with pytest.raises(ValueError):
        GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
            trusted_workflow_ids=frozenset({51}), reader=FakeGitHubReader(),
            required_job_names=required, trusted_events=events)


def test_jobs_reject_duplicate_names_and_wrong_run_identity():
    jobs=[{"name": name, "run_id": 99, "head_sha": SHA, "status": "completed",
           "conclusion": "success"} for name in ("lint", "lint")]
    with pytest.raises(ValueError,match="duplicate"):
        inspect(FakeGitHubReader(jobs={"jobs": jobs}))
    jobs[1]["name"]="unit"
    jobs[1]["run_id"]=98
    with pytest.raises(ValueError,match="CI job"):
        inspect(FakeGitHubReader(jobs={"jobs": jobs}))


def test_http_reader_jobs_query_is_exactly_allowlisted():
    client=GitHubReadOnlyHTTP()
    for path in ("/repos/a/b/actions/runs/99/jobs",
                 "/repos/a/b/actions/runs/99/jobs?filter=all&per_page=100",
                 "/repos/a/b/actions/runs/99/jobs?filter=latest&per_page=2",
                 "/repos/a/b/actions/runs/99/jobs?filter=latest&per_page=100&foo=bar"):
        with pytest.raises(ValueError,match="not an allowed"):
            client(path)
