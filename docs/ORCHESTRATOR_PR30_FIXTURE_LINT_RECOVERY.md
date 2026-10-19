# PR-30 — Restore Pytest fixture registration and remove remaining Ruff findings

Date: 2026-10-20. Stacked on Draft PR #31; `master` unchanged.

## Review: a "safe" Ruff fix was unsafe for Pytest
At exact stacked branch SHA `e28c368375409d3ff4a955fa59bb8c1d1cc8dbef`, [GitHub Actions run 39332816766](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39332816766) failed on all 6 Linux/macOS/Windows + Python 3.11/3.12 cells: **988 tests passed, 64 setup errors, 20 subtests passed**. Ruff reported **53 remaining errors**, down from the earlier 115, but tests regressed.

The root cause: Ruff's default `F401` unused-import fix removed `store` imported from `test_orchestrator_provider_evidence` in three consumer test modules. Those imports register an external pytest fixture in the module namespace, **despite not being referenced as an ordinary Python symbol**. A lint tool cannot safely infer this registration; the rewrite broke fixture discovery. The affected consumer modules are `test_orchestrator_implementer_provenance.py`, `test_orchestrator_task_review_evidence.py`, and `test_orchestrator_workflow_pin_ledger.py`.

## Changes
- Re-export `store` explicitly with `from test_orchestrator_provider_evidence import ... store as store` in all three consumer modules. The intentional same-name alias informs Ruff that the symbol is an intentional public fixture re-export.
- Introduce `tests/test_orchestrator_fixture_reexports.py`, checking that the three imported `store` objects are precisely the provider's fixture. Prevent future "safe" F401 cleanup from removing registration silently.
- Fix all 45 reported E701 one-line colon statements and 5 E702 semicolon statements by preserving their exact expressions and making their control-body indentation explicit.
- Resolve F841 unused locals: keep the `nextpart(item, uid)` call's side effect while removing unused assignment; remove genuinely unused `poll_count` initialization.
- Use Python 3.11+ `StrEnum` for UP042, but explicitly delegate `__str__` to `Enum.__str__` to **preserve the previous public text representation** (e.g. `TaskState.RESERVED`). Add tests for both string equality and unchanged JSON serialization. An independent reviewer should still check downstream compatibility.

## Verification status and limits
The changes are committed based on exact GitHub source and CI evidence. **No new passing test or clean Ruff claim applies until CI reruns on the exact new commit.** The prior 1,052-passing receipt belongs to an older commit; it cannot attest to this patch.

The self-editable branch Actions workflow remains **untrusted diagnostics only** and must not authorize production changes. No live ChatGPT worker, model/app control, real upload, merge or finalizer is enabled.

## Next checks
1. Verify all six OS/Python cells against exact pushed SHA, zero Ruff errors, and postflight clean source.
2. Confirm dependent wheel/sdist build and CLI smoke steps actually complete on that same SHA.
3. Perform independent review of StrEnum compatibility, fixture export conventions and lint tool configuration. Pin dependency versions and introduce owner-protected CI separately.
