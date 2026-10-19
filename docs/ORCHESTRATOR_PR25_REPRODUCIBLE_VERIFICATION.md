# PR-25 — Reproducible local verification and honest evidence claims

Date: 2026-10-19. Stacked on Draft PR #26. This change improves validation discipline, **not** remote transport, task finalization, or provider authorization.

## Root-cause review

The earlier `scripts/verify_orchestrator.py` could return success without identifying the tested Git commit or asserting a clean working tree. Its summary set `network_actions: false` even though launching arbitrary Python tests does not establish network isolation. `--skip-lint` produced the same top-level success as a complete local check, while stdout/stderr tails could accidentally expose test fixture secrets.

The GitHub fork currently has zero workflow runs. Therefore successful provider CI, trusted reviewer approval, and a completed PR stack are **not** demonstrated.

## Implemented

- `--expected-sha <40-char>` pins verification to an explicitly supplied, independently recorded Git commit. A mismatch refuses to launch tests. Do **not** fill it via `git rev-parse HEAD` without comparing that SHA against the intended reviewed PR HEAD.
- `--strict` requires exact expected SHA, a clean Git working tree (including untracked files), and Ruff enabled. The script checks that `--repo` is the repository root.
- `--full` runs the complete non-E2E pytest suite. Strict + full + successful compileall/pytest/Ruff results in `local_gate_complete=true`; this is **not** a signed CI approval.
- Live account E2E is excluded with `-m "not e2e"` and `W2A_E2E_RUN=0` in the child process, even if enabled in the parent shell. This does not independently prove offline isolation.
- JSON includes Git HEAD, pin comparison, worktree state, Python/platform, check exit codes/durations, and SHA-256 summaries of captured stdout/stderr.
- Test output is **not** printed by default; `--diagnostics` explicitly opts into potentially sensitive output tails. `--skip-lint` remains a convenience for development and never yields `local_gate_complete=true`.
- Seven isolated pytest cases exercise pass/fail, commit mismatch, dirty tree, missing SHA, lint skip, redacted failures and wrong repository root.

## Local proof and exact blob equivalence

On Python 3.13/Linux in an isolated script-only fixture: `python -m pytest -q tests/test_verify_orchestrator.py` → **7 passed**. Tests were run again after the final style edits.

Source/test Git blobs were compared against the connector-written GitHub files:
- `scripts/verify_orchestrator.py`: `a4f7afd54f48fe7f154e49fa8285529d1e42837e`
- `tests/test_verify_orchestrator.py`: `42c6b5f282da670484a7b696ea5182b61d43fcca`

These prove exact tested file bytes for **this independent unit suite**, not the entire stacked repository, the final branch HEAD, Ruff or CI.

## Required Codex execution in reviewed checkout

Windows PowerShell after `git fetch` and checkout of the exact reviewed branch commit:

```powershell
# Use the commit SHA copied and independently checked from the intended PR HEAD:
$approvedHead = "<FULL_40_CHARACTER_REVIEWED_COMMIT_SHA>"
python scripts/verify_orchestrator.py --full --strict --expected-sha $approvedHead
```

Linux/macOS:

```bash
# Supply an independently recorded reviewed SHA (not auto-derived from HEAD)
python scripts/verify_orchestrator.py --full --strict --expected-sha "$APPROVED_HEAD_SHA"
```

Exit codes: `0` = requested local checks succeeded, `1` = check failure, `2` = rejected preflight. Record full JSON plus operating-system and environment provenance in an operator-controlled evidence location. CI/build matrix still needs separate execution.

## Remaining release blockers

- GitHub Actions run on exact reviewed branch, PR stacks #1–#27, Ruff and upstream tests on Python 3.11/3.12 and Windows/macOS/Linux.
- External action dependencies, workflow source, CI permissions and reviewer identity must be independent of agent-writable code.
- No authenticated remote ChatGPT worker/session or actual model/app/upload parity has been proven. Future production finalization demands fresh independent GitHub/CI/review reads, explicit human consent, provider actions and transactional authorization.
- Do not auto-merge or run account-mutating ChatGPT/UI actions based on this local verifier.
