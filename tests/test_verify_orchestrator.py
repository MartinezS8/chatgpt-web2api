"""Isolated verification-gate tests: only temporary Git repositories, no provider calls."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_orchestrator.py"
MODULE_SPEC = importlib.util.spec_from_file_location("local_verification_gate", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
checker = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(checker)


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text("[build-system]\n", encoding="utf8")
    (repo / "tests" / "test_orchestrator_example.py").write_text("def test_example(): pass\n", encoding="utf8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "offline@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Offline Tester"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


def fake_checks(monkeypatch):
    original = checker.subprocess.run
    seen = []

    def replacement(args, **kw):
        if args[0] == "git":
            return original(args, **kw)
        seen.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout="pass\n", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", replacement)
    return seen


def output(capsys):
    return json.loads(capsys.readouterr().out)


def test_strict_full_clean_sha_reports_only_local_gate(checkout, monkeypatch, capsys):
    root, sha = checkout
    calls = fake_checks(monkeypatch)
    monkeypatch.setenv("W2A_E2E_RUN", "1")
    assert checker.main(["--repo", str(root), "--expected-sha", sha,
                         "--strict", "--full"]) == 0
    data = output(capsys)
    assert data["ok"] and data["local_gate_complete"]
    assert data["head_sha"] == sha and data["worktree_clean_at_start"]
    assert data["postflight_ok"] and data["head_sha_at_end"] == sha
    assert data["worktree_clean_at_end"]
    assert not data["network_isolation_verified"] and not data["live_provider_capabilities_verified"]
    assert len(calls) == 3 and all(c[1]["env"]["W2A_E2E_RUN"] == "0" for c in calls)
    assert all("stdout_tail" not in x for x in data["checks"])
    assert "-m" in calls[1][0] and "not e2e" in calls[1][0]


def test_wrong_sha_refuses_execution(checkout, monkeypatch, capsys):
    root, _ = checkout
    calls = fake_checks(monkeypatch)
    assert checker.main(["--repo", str(root), "--expected-sha", "a" * 40, "--strict"]) == 2
    data = output(capsys)
    assert not data["tests_started"] and not calls


def test_uncommitted_changes_refuse_strict_gate(checkout, monkeypatch, capsys):
    root, sha = checkout
    (root / "unexpected.txt").write_text("new file", encoding="utf8")
    calls = fake_checks(monkeypatch)
    assert checker.main(["--repo", str(root), "--expected-sha", sha, "--strict"]) == 2
    assert not output(capsys)["tests_started"] and not calls


def test_missing_pin_or_skipped_lint_cannot_pass_strict(checkout, monkeypatch, capsys):
    root, sha = checkout
    calls = fake_checks(monkeypatch)
    assert checker.main(["--repo", str(root), "--strict"]) == 2
    assert not output(capsys)["tests_started"]
    assert checker.main(["--repo", str(root), "--strict", "--expected-sha", sha,
                         "--skip-lint"]) == 2
    assert not output(capsys)["tests_started"]
    assert not calls


def test_skip_lint_is_only_a_smoke_test(checkout, monkeypatch, capsys):
    root, sha = checkout
    calls = fake_checks(monkeypatch)
    assert checker.main(["--repo", str(root), "--expected-sha", sha,
                         "--skip-lint"]) == 0
    data = output(capsys)
    assert data["ok"] and not data["local_gate_complete"]
    assert data["skipped_checks"] == ["ruff"] and len(calls) == 2


def test_failure_stays_red_and_hides_output_without_opt_in(checkout, monkeypatch, capsys):
    root, sha = checkout
    original = checker.subprocess.run

    def runner(args, **kw):
        if args[0] == "git":
            return original(args, **kw)
        if "pytest" in args:
            return subprocess.CompletedProcess(args, 1, stdout="SECRET_TEST_DATA", stderr="trace")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", runner)
    assert checker.main(["--repo", str(root), "--strict", "--full",
                         "--expected-sha", sha]) == 1
    raw = capsys.readouterr().out
    assert "SECRET_TEST_DATA" not in raw and "trace" not in raw
    parsed = json.loads(raw)
    assert not parsed["ok"] and not parsed["local_gate_complete"]
    assert len(parsed["checks"]) == 3


def test_invalid_git_metadata_refused(checkout, tmp_path, capsys):
    root, _ = checkout
    assert checker.main(["--repo", str(root / "src")]) == 2
    assert not output(capsys)["tests_started"]


def test_forged_success_after_tracked_file_mutation_is_rejected(
    checkout, monkeypatch, capsys,
):
    root, sha = checkout
    original = checker.subprocess.run
    edited = root / "tests" / "test_orchestrator_example.py"

    def runner(args, **kw):
        if args[0] == "git":
            return original(args, **kw)
        if "pytest" in args:
            edited.write_text("def test_example(): assert False\\n", encoding="utf8")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", runner)
    assert checker.main(["--repo", str(root), "--strict", "--full",
                         "--expected-sha", sha]) == 1
    result = output(capsys)
    assert all(x["exit_code"] == 0 for x in result["checks"])
    assert not result["postflight_ok"] and not result["local_gate_complete"]
    assert "dirty" in result["postflight_error"]
    assert not result["ok"]


def test_commit_moves_while_tests_run_is_rejected(checkout, monkeypatch, capsys):
    root, sha = checkout
    original = checker.subprocess.run

    def runner(args, **kw):
        if args[0] == "git":
            return original(args, **kw)
        if "pytest" in args:
            original(["git", "commit", "-qm", "unexpected", "--allow-empty"],
                     cwd=root, check=True)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", runner)
    assert checker.main(["--repo", str(root), "--strict", "--full",
                         "--expected-sha", sha]) == 1
    result = output(capsys)
    assert result["postflight_ok"] is False and not result["ok"]
    assert "differs from --expected-sha" in result["postflight_error"]


def test_inherited_pytest_selectors_and_external_pythonpath_removed(
    checkout, monkeypatch, capsys,
):
    root, sha = checkout
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests --maxfail=1")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_extra_test_plugin")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONPATH", "/tmp/untrusted")
    calls = fake_checks(monkeypatch)
    assert checker.main(["--repo", str(root), "--strict", "--full",
                         "--expected-sha", sha]) == 0
    result = output(capsys)
    assert result["postflight_ok"] and result["local_gate_complete"]
    assert calls
    for _, kwargs in calls:
        child = kwargs["env"]
        assert "PYTEST_ADDOPTS" not in child
        assert "PYTEST_PLUGINS" not in child
        assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in child
        assert child["PYTHONPATH"] == checker.os.pathsep.join((str(root / "src"),
                                                               str(root / "tests")))
    assert "-p" in calls[1][0] and "no:cacheprovider" in calls[1][0]


def test_unexpected_git_error_during_postflight_fails_closed(
    checkout, monkeypatch, capsys,
):
    root, sha = checkout
    calls = fake_checks(monkeypatch)
    original = checker._preflight
    seen = 0

    def preflight(*args, **kwargs):
        nonlocal seen
        seen += 1
        if seen == 2:
            raise ValueError("Git metadata unavailable; no tests were executed")
        return original(*args, **kwargs)

    monkeypatch.setattr(checker, "_preflight", preflight)
    assert checker.main(["--repo", str(root), "--strict", "--full",
                         "--expected-sha", sha]) == 1
    result = output(capsys)
    assert len(calls) == 3
    assert not result["postflight_ok"] and not result["local_gate_complete"]
    assert "postflight_error" in result and not result["ok"]


def test_injected_git_dir_and_worktree_do_not_redirect_identity(
    checkout, monkeypatch, capsys,
):
    root, sha = checkout
    monkeypatch.setenv("GIT_DIR", str(root / "does-not-exist.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(root / "src"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(root / "injected-index"))
    calls = fake_checks(monkeypatch)
    assert checker.main(["--repo", str(root), "--strict", "--full",
                         "--expected-sha", sha]) == 0
    result = output(capsys)
    assert result["head_sha_at_end"] == sha
    assert result["postflight_ok"] and result["local_gate_complete"]
    assert len(calls) == 3
