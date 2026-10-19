"""Static contract for development-branch CI, not a provider trust certificate."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchestrator-branch-validation.yml"
STANDARD_CI = ROOT / ".github" / "workflows" / "ci.yml"

CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"


def test_only_feature_branch_pushes_trigger_diagnostics():
    content = WORKFLOW.read_text(encoding="utf8")
    assert re.search(
        r"(?m)^on:\s*\n\s*push:\s*\n\s*branches:\s*\n"
        r"\s*- ['\"]codex/orchestrator-\*['\"]", content,
    )
    for forbidden in ("pull_request_target:", "workflow_run:", "repository_dispatch:",
                      "workflow_dispatch:", "schedule:"):
        assert forbidden not in content


def test_action_refs_are_full_immutable_commit_ids():
    content = WORKFLOW.read_text(encoding="utf8")
    actions = re.findall(r"(?m)^\s*-?\s*uses: ([^\s#]+)", content)
    assert len(actions) == 4
    assert actions.count(f"actions/checkout@{CHECKOUT_SHA}") == 2
    assert actions.count(f"actions/setup-python@{SETUP_SHA}") == 2
    assert all(re.fullmatch(r"actions/(checkout|setup-python)@[a-f0-9]{40}", a)
               for a in actions)


def test_diagnostics_use_read_only_github_token_and_no_secrets():
    content = WORKFLOW.read_text(encoding="utf8")
    assert re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", content)
    assert "persist-credentials: false" in content
    assert "secrets." not in content
    assert "id-token: write" not in content
    assert "contents: write" not in content
    assert "pull-requests: write" not in content


def test_all_os_python_combinations_run_full_exact_head_gate():
    content = WORKFLOW.read_text(encoding="utf8")
    assert "ubuntu-latest, windows-latest, macos-latest" in content
    assert "python: ['3.11', '3.12']" in content
    assert "fail-fast: false" in content
    assert "REVIEWED_HEAD_SHA: ${{ github.sha }}" in content
    # Explicit diagnostics can be placed between the strict flag and SHA;
    # only exact-SHA, full-suite and strict requirements are authoritative.
    assert "verify_orchestrator.py --full --strict " in content
    assert '--expected-sha "$REVIEWED_HEAD_SHA"' in content
    assert "W2A_E2E_RUN: '0'" in content
    assert "needs: offline-suite" in content


def test_authoritative_standard_ci_is_not_expanded_or_replaced():
    content = STANDARD_CI.read_text(encoding="utf8")
    assert re.search(r"(?m)^  push:\s*\n    branches: \[master\]", content)
    assert re.search(r"(?m)^  pull_request:\s*\n    branches: \[master\]", content)
    assert "codex/orchestrator-" not in content
