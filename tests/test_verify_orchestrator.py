"""Isolated verification-gate tests: only temporary Git repositories, no provider calls."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
