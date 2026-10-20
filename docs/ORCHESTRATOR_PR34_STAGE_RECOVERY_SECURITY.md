# PR-34 — Cooperative V2 staging crash recovery, offline only

Base: PR #35 HEAD `757df4a48d148d85bb280013e020c59672127766`.
Implementation and tests are intended for a separate stacked Draft PR. No `master` merge, live provider actions, authenticated browser or automatic finalizer.

## Problem and trust model

Previous SQLite and attachment stages were cleaned only on normal Python control flow. A process death via `os._exit` leaves an unknown stage on disk. A stage's age by itself does not prove abandonment, because another active process may still own it. Historic legacy stage names were written without cross-process lifetime coordination; they cannot safely be auto-deleted.

The new V2 protocol assumes a trusted, account-private staging directory. An attacker that can rewrite the parent directory or rename a junction during OS file operations is **not** in the safe threat model. Simple `lstat`/reparse checks and `fstat` equality do not provide universal Win32 handle-based guarantees.

## V2 stage lifecycle

- Both `TaskPackages._store_blob` and `snapshot_sqlite_same_directory` acquire the same `stage_guard(directory)` before allocating a stage. It is held until publication or removal, including during writes.
- POSIX uses `flock`; Windows uses `msvcrt.locking` on a permanent per-directory `.orchestrator-stage.lock` file. A hard process death releases the OS lock without requiring a callback. This serializes cooperating writers and recovery.
- Managed names are `.staged-v2-<32-hex>` or `.sqlite-snapshot-v2-<32-hex>`, created with `O_CREAT|O_EXCL`. The lock file is intentionally never automatically removed.
- `cleanup_managed_stages` first takes the exclusive lock, then rechecks each candidate's regular-file identity. Only known V2 names meeting an age threshold can be unlinked. Legacy `.staged-*` and `.sqlite-snapshot-*` stay untouched indefinitely for manual reconciliation. Default is `dry_run=True`.
- CLI: `python -m chatgpt_web2api.orchestrator staging-audit --root <EXPLICIT-LOCAL-DIR>` lists candidates. To opt into V2-only cleanup, add `--delete-managed-v2 --older-than-hours 24`; deletion requires at least one hour and the cooperative lock. **Never** run on untrusted or multi-user writable storage.

## macOS canonical POSIX paths

Initial exact-SHA [CI run 39435309531](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39435309531) exposed legitimate macOS temp aliases such as `/var -> /private/var` being rejected by the inherited reparse component validation. The fix canonicalizes the path **only on POSIX** before ancestor checks and retains strict reparse/junction checking on Windows. Attachment sources are still checked against the resolved `allowed_root`, and direct source symlinks remain rejected. The new POSIX alias regression covers an explicitly controlled directory, not malicious racing writes.

## Attachment identity check

`TaskPackages.seal` retains the source file's initial `os.stat_result`. At fd open, the code compares `fstat` device/inode, size, and nanosecond modification time. The code compares the fd again after the read. A source swap between preflight and open fails rather than silently snapshotting another inode. The existing allow-root and reparse checks remain.

**Limit:** Python-level stat/fstat cannot promise immunity against every malicious simultaneous Windows junction/path replacement. Do not grant write access to arbitrary other principals on `allowed_root` or storage roots. A true arbitrary-path Windows trust boundary needs native handle-relative operations and final path identity checks.

## Verification

Focused local stdlib staging protocol regression tests: hard-process-exit leftover, active writer not deleted, strict V2 naming, legacy untouched, negative age. Expanded repository tests include source replacement and CLI dry-run/explicit deletion protection. The full GitHub branch-validation workflow runs Python 3.11/3.12 on Linux/macOS/Windows with `W2A_E2E_RUN=0`, strict SHA and Ruff; only results returned for the *new exact commit* may be cited.

Separate acceptance remains **NOT TESTED** for: second-user effective Windows ACL denial, unprivileged malicious junction replacement during a trusted operation, real NTFS long paths on systems where long-path support is disabled, and abrupt power loss with NTFS durability. A Windows diagnostic may pass or skip a disposable >260-character path; skip is not an accepted compatibility proof.

Live ChatGPT sessions, uploads, hosted app selection, authenticated remote callbacks, external writes and productive finalization remain unavailable.
