# PR-33 — Versioned SQLite initialization and explicit Windows storage hardening

Date: 2026-10-20. Parent is Draft PR #34 at `96005a30102c1015ab41fcb0673da170714a5ae6`. Branch: `codex/local-v33-storage-hardening-no-ci`.

**User instruction:** do not run GitHub CI. This branch intentionally does not match the push-only `codex/orchestrator-*` diagnostic trigger. No workflow file was changed, no CI run or production deployment was requested.

## Why

The original `Store._initialize` performed `executescript` schema initialization separately from legacy-column additions and quarantine logic. Python sqlite3 `executescript` can commit pending transactions and is not an adequate atomic migration fence. Existing Windows local-data folders also relied on manual ACL settings, and a WAL-correct backup interface was missing.

## Changes

1. **Store migration v2:** transaction-wrap table/index creation, existing V3 column additions, legacy active-state quarantine and `orchestrator_schema_versions` registration. Use `BEGIN IMMEDIATE`, reject unknown future versions and missing mandatory ownership columns. Previously unversioned databases are recognized conservatively.
2. **Integrity checks:** SQLite `quick_check` and `foreign_key_check` before schema writes, plus FK checks after migration. Existing orphans block migration rather than being silently repaired/dropped.
3. **Opt-in Windows secure workspace:** `python -m chatgpt_web2api.orchestrator init-private-workspace --label my-test`. Creates *only a new workspace* under `%LOCALAPPDATA%\\chatgpt-web2api\\my-test`. Uses the native current-user SID and shell-free `icacls` to drop inherited permissions, explicitly grant the user and SYSTEM full control, then request verification. No attempt to rewrite the ACL of a pre-existing workspace. Only the resulting private paths should be used for protected controller DB and blobs.
4. **SQLite online backup:** `python -m chatgpt_web2api.orchestrator --db <absolute-existing-db-path> backup-local-db --filename before-upgrade.sqlite3`. Uses SQLite's online backup API (committed WAL included), validates integrity and FK constraints on the snapshot, syncs to disk, then publishes a hard-link under the source DB's same directory. It refuses to overwrite an existing name, symlink source or traversal. A filesystem without hard-link support fails closed. The caller must ensure the parent directory is private; an existing public directory is not automatically secured.
5. **Tests added, not executed:** unversioned V3→v2 upgrade; injected migration failure with DDL rollback; future-schema rejection; orphan-FK fail closed; subprocess crash with uncommitted schema/data writes; WAL-correct backup and no-clobber; interrupted attachment staged-file cleanup; SID parsing and shell-free ACL argument construction; CLI availability.

## Constraints and residual risks

- Legacy DBs/directories are **not automatically secured**. Existing production data must be explicitly migrated into a new restricted workspace by an operator after backup and independent permission review. This PR does not implement that migration.
- Windows ACL provisioning is opt in and requires native Windows tools. It is not yet a full effective-ACL audit, owner SID attestation, junction traversal proof or hardened security descriptor review. Windows manual verification remains mandatory.
- SQLite online backup is *backup creation*, not a tested full restore plan; no automatic rollback of user databases is performed.
- Test process abort covers atomic SQLite rollback. Abrupt OS power loss, NTFS durability, ACL inheritance, backup restoration and Windows filesystem edge conditions remain to be tested locally.
- No real worker sends, plugin/app controls, authenticated remote callbacks, automatic approval, release, or merge are implemented.

## Local validation request (NOT GitHub CI)

After checking out the new exact branch and verifying the Git worktree is clean, run in a disposable Python virtual environment outside the repo:

```powershell
python -m pytest -q -p no:cacheprovider -m "not e2e" tests/test_orchestrator_storage_hardening.py
python -m ruff check src/ tests/
python scripts/verify_orchestrator.py --full --strict --expected-sha (git rev-parse HEAD).Trim()
```

On Windows, separately create a disposable private workspace and inspect its effective access rights and inherited permissions with `icacls`. Do not run tests with live ChatGPT credentials or `W2A_E2E_RUN=1`.

**Approval:** The development implementation is unverified until a local code reviewer and Windows runner confirm correctness. An existing GitHub-Actions success on the parent SHA does not attest to the new code.
