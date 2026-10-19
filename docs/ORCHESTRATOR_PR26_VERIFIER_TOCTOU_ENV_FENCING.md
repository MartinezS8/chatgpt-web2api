# PR-26 — Prevent false local verification after checkout or environment mutation

Date: 2026-10-19. Stacked on draft PR #27, **not** on `master`.

## Review findings

The V25 local verification gate checked an exact Git HEAD and a clean worktree **before** invoking subprocesses. A test process or concurrent editor could then alter a tracked file or move the HEAD, while all subprocesses returned zero and the verifier reported `ok=true` and `local_gate_complete=true`. This is a real time-of-check/time-of-use defect in the local evidence boundary.

Additionally, inherited `PYTEST_ADDOPTS` can silently ignore tests with `--ignore` or `-k`, `PYTEST_PLUGINS` and inherited `PYTHONPATH` can change collected tests, and inherited `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` can redirect Git queries outside the checkout. Existing `W2A_E2E_RUN=0` and `-m 'not e2e'` remain in place.

## Changes

- Recheck the requested Git identity, root, tracked/untracked clean state and expected SHA **after** compileall, pytest and Ruff finish. A postflight mismatch now forces `ok=false`, `postflight_ok=false` and `local_gate_complete=false`, with a nonzero exit code, *even if subprocesses all returned zero*.
- Include final `head_sha_at_end` and `worktree_clean_at_end` when a final observation succeeded. Failure reports carry a concise `postflight_error` without raw test output.
- Sanitize `GIT_*` for all Git subprocesses so they cannot read an injected Git worktree, index or config identity.
- Sanitize inherited `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD` from child test subprocesses. Set `PYTHONPATH` to checked-out `src` only.
- Pass `-p no:cacheprovider` to pytest, avoiding the common new untracked `.pytest_cache` directory during strict postflight.
- Add five negative and environment-hardening test cases; total isolated verifier suite: **12 test functions**.

## Limitations

The new postflight check reduces a serious TOCTOU window but is not a hermetic snapshot or cryptographic attestation against a privileged adversary. Code can still change and revert while a test runs without being observable at the end. Tests and dependencies can access the network; this script only forces E2E opt-in off and excludes the e2e marker. It does not authenticate runner provenance, hosted ChatGPT sessions, operator consent or CI job integrity.

**Execution status:** All changes committed through GitHub; exact full stacked checkout, Ruff, supported OS/Python matrix, CI and even these new 12 isolated tests are **not executed in this tool session**. No claims of passed tests or approved workflow are made. Treat this PR as a code candidate awaiting independent verification.

## Required local verification

From an independently reviewed SHA after the *entire* PR stack has been checked out:

```bash
python -m pytest -q tests/test_verify_orchestrator.py
python scripts/verify_orchestrator.py --full --strict --expected-sha "$REVIEWED_HEAD_SHA"
```

Check the returned `head_sha`, `head_sha_at_end`, `ok`, `postflight_ok` and `local_gate_complete` together. For diagnostics only, opt in with `--diagnostics`; treat full raw tails as potentially sensitive. Perform CI on Windows/macOS/Linux Python 3.11/3.12 independently, including provenance-pinned workflows, required job identities and trusted reviewers.

## Next gate

The GitHub repo still has zero completed Actions workflow runs observed, because its existing `.github/workflows/ci.yml` push trigger covers only `master` and PR trigger targets only `master`; stacked feature-to-feature PRs do not necessarily trigger this CI. The next work must solve branch CI eligibility and immutable trusted workflow dependencies without converting agent-controlled green workflows into authority. Do not enable automatic merges, remote sends, plugin selection, uploads or finalization as a result of this change.
