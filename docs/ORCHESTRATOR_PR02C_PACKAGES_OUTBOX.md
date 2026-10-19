# PR-02C — Immutable local packages, send-intent outbox and event cursors

Stacked on PR-02B. This is **offline infrastructure** and intentionally has **no live browser, ChatGPT, Codex-app-server, GitHub or Supabase transport adapter**.

## Local task package

- `TaskPackages.seal(task_id, prompt, attachments, allowed_root=...)` verifies the registered prompt checksum, copies allowlisted file types into local content-addressed blobs and saves one immutable package record. File count and size are bounded; symlinks and out-of-root references are rejected. Attachment hashes are verified before preparing dispatch.
- Files are **not uploaded**. No remote attachment ID is created. A future authorized adapter must separately verify remote upload completion and MIME/size/plan quotas prior to any message send.
- Task prompt is stored **in plaintext in local SQLite** for durability. The DB and snapshot directory are sensitive; do not put credentials in prompts and protect/backup the files with OS permissions. Windows ACL hardening and encryption remain follow-up work.
- `python -m chatgpt_web2api.orchestrator --json seal-task --id ... --prompt-file ... [--attachment ... --allowed-root ...]`; `task-package` shows only the manifest, not the prompt.

## Durable send intent

- `DispatchOutbox.begin(task_id, fenced_claim_token)` atomically checks a sealed, verified package, the live `reserved` claim, and lease deadline, writes the unique attempt and `dispatch.intent`, and transitions the task to `dispatching`. Only the one synchronous *new* attempt return carries `new_send_permit=True`.
- A repeated begin or restarted process can *inspect* the same attempt, but never receives a second send permit. A crash **after** durable intent but **before** the actual external send cannot be distinguished from a crash after send without remote evidence; it becomes `unknown_delivery`, with no auto-resend.
- `accept` requires an existing intent, matching fenced claim, and confirmed remote conversation/message IDs. `complete` requires exact match with that delivery ID and immutable result reference. Duplicate matching receipts are idempotent; mismatches are rejected.
- An append-only `orchestrator_delivery_events` table provides stable event IDs and per-consumer sequential acknowledgment cursors that survive restarts. MCP progress notifications are **not** an authoritative completion signal.
- `reconcile_stale` marks aged unconfirmed intents unknown rather than retrying. No external delivery or 'exactly once' guarantees exist.

## Limits and outstanding integration

1. **Still not wired to V4 `Controller.dispatch` or Octo-Lex's web MCP.** A later transport PR must use `begin` rather than the legacy direct state transition. Do not combine two dispatch paths in production.
2. The outbox has only one attempt per task until an explicit, separately reviewed reconciliation protocol exists. Never automatically create a second attempt after `unknown_delivery`.
3. Provider-attested model/High, app selection, file uploads, consent, rate-limit handling and callback workers remain unimplemented.
4. Backup/restore migrations, schema versioning, secure Windows ACLs and consistency tests are still required prior to service deployment.
5. Test with `PYTHONPATH=src python -m pytest -q tests/test_orchestrator*.py`; run full upstream suite and CI independently before merge.