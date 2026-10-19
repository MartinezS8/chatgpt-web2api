# PR-27 — Read-only feature-branch CI diagnostics

Date: 2026-10-19. Stacked on Draft PR #28. All changes confined to developer diagnostics; `master` and existing `.github/workflows/ci.yml` remain untouched.

## Review and rationale

The authoritative `.github/workflows/ci.yml` only runs for `push(master)` or pull requests targeting `master`. GitHub Actions had **zero runs** on the fork, despite 26+ stacked development PRs. GitHub's documented `push` event discovers workflows present on non-default feature branches, so a separate file can run without changing the owner-authorized workflow source.

This separate workflow is **UNTRUSTED DIAGNOSTIC EVIDENCE**, because the same development branch can modify its YAML. Green diagnostics may never be promoted into production CI approval, worker identity proof, reviewer attestation, merge permission or task completion.

## Implemented

- New `.github/workflows/orchestrator-branch-validation.yml`, triggered only on pushes matching `codex/orchestrator-*`, with `permissions: contents: read`, `persist-credentials: false`, no repository/environment secrets and per-branch cancellation of superseded runs.
- Pin third-party action entrypoints to exact verified Git commits: `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` (v4.2.2) and `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (v5.6.0), independently looked up from GitHub tag refs.
- Run `python scripts/verify_orchestrator.py --full --strict --expected-sha "$REVIEWED_HEAD_SHA"` under Linux, macOS and Windows with Python 3.11 and 3.12 (six matrix entries). Also force non-E2E mode; local SHA pre/postflight and clean worktree checks remain mandatory.
- A wheel and sdist build (with CLI help smoke checks) depends on the **entire** matrix succeeding.
- The diagnostic job requests `--diagnostics` explicitly to include up to 3k/1.5k characters of test/lint stdout/stderr tail in its public GitHub log. This is **allowed here only because these ephemeral read-only runners have no live ChatGPT account/session or provider secrets**; avoid echoing personal data and revoke this opt-in before introducing sensitive test fixtures.
- Five static tests assert allowed triggers, GitHub read-only privileges, all entrypoints SHA-pinned, six combinations, enforced SHA check and unchanged owner workflow.

## First real evidence: not green

GitHub automatically created runs as soon as the feature-branch workflow was pushed. For the first complete diagnostic run, [Actions run 39327764123](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39327764123), the Linux Python 3.11 check reported:
- `compileall`: exit 0.
- `pytest`: exit 2 with **four collection failures** because neighboring test-helper modules were not on `PYTHONPATH`.
- `ruff`: exit 1 with **115 errors** in `src/` and `tests/`.
- Git SHA preflight and postflight both passed, so these were genuine source/test/lint problems, not a checkout mismatch.

We amended `verify_orchestrator.py` to set child `PYTHONPATH` to the pinned checkout's `src` **and** `tests`, restoring intended top-level imports of `test_orchestrator_provider_evidence` and similar helpers. A later matrix run is needed to know whether the collection fix reveals other test failures. The lint gate remains intentionally red until fixed. Initial runs can be cancelled by subsequent pushes; report only completed runs for a specific, exact HEAD.

## Gaps and release blockers

- This developer-workflow YAML is **branch-writable**. It is not `WorkflowSourcePin` policy; that older operator-trusted gate requires an independently approved source digest and protected branch rules. Do not permit the new workflow's status to satisfy the finalizer.
- Python packages from PyPI, setup/build tool chains, operating-system runner images, dependency transitive graph and browser-independent test internals are **not immutable** despite full action SHA pins. No supply-chain attestation or network isolation is claimed.
- The previous `ci.yml` still downloads gitleaks from an external release URL and uses floating action versions. It must be hardened independently under protected owner policy.
- No authenticated live web agent, model/app attestation, real remote uploads, ChatGPT Plus usage rights, approved merge, or human-authorized finalization is implemented.
- Treat `local_gate_complete` as local source-test reporting only; no trusted CI release stamp from this PR.

## Next concrete work

1. Inspect the latest workflow matrix logs and fix actual pytest failures; preserve fail-closed gates.
2. Triage all Ruff findings into additive new defects and historical source debt; fix as scoped reviews rather than applying unsafe automatic refactors.
3. Compare exact source commit, OS/Python, job outcomes and successful package build before marking validation complete. Trusted CI requires separate policy controls and reviewer checks.

References: [GitHub push event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) and [GitHub secure action usage](https://docs.github.com/en/actions/reference/security/secure-use).
