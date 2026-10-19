# PR-04 (offline foundation): Correlated callbacks and independent GitHub evidence

Baseline: [PR #5](https://github.com/MartinezS8/chatgpt-web2api/pull/5) (`codex/orchestrator-v6-worker-scheduler`). This work remains **Draft**, with no production transport authorized.

## Motivation / architecture review

The existing V5 `DispatchOutbox` already owns acknowledged delivery and idempotent `turn.completed` events. Do not introduce another state machine that can mark tasks finished. MCP progress notifications and agent text are advisory, not provider-authenticated delivery or immutable Git/CI proof.

PR #5 previously could fail when assigning a recovered *pre-send* task: `orchestrator_worker_assignments.task_id` is primary key, while a previously released assignment row remained. PR #5 now conditionally reuses only released rows (`Scheduler.claim_next`) with a regression test, rather than overwriting active ownership. Independent review comment is on PR #5. Entire repo/Windows CI remains required.

## New modules

- `orchestrator/callback_policy.py`: mock-only callback envelope using exact `(attempt_id, conversation_id, delivery_id)`; durable, ordered, deduplicated progress events. Progress never advances task state or claims Git/CI proof. Completion delegates to existing `DispatchOutbox.complete`, preserving its accepted-turn correlation and existing durable `turn.completed` event. A second outbox read under SQLite `BEGIN IMMEDIATE` rejects progress racing with a terminal completion.
- `orchestrator/evidence.py`: immutable provider-evidence data contracts. Exact repository ID, PR number, 40-hex SHA, required green checks on the **current** SHA, independent latest-reviewer approval for that SHA; reject outstanding `CHANGES_REQUESTED`, draft/closed PRs and stale SHA.
- `orchestrator/review_policy.py`: requires a local task in `verified` state and an exact `github:{repo-id}:pr:{number}:sha:{head}` evidence reference. Re-reads provider evidence through a pluggable *read-only* adapter and records a review decision; does **not** call `Store.finalize_verified`, release locks, merge, upload, or perform external requests.

## Boundaries — not supported yet

- **No trusted live callback endpoint.** `CallbackPolicy.ingest` deliberately requires `source='mock'`; all other values fail. Future PR-07 must connect an authenticated permitted transport. A caller-provided `source` string MUST NOT be exposed as an authentication method.
- **No real GitHub evidence provider is bundled.** The `EvidenceReader` protocol needs a separately authenticated connector implementing read-only provider inspection and preserving the API's reviewer-order semantics. A mock evidence reader tests decision logic but cannot authorize real production approval.
- **Historical finalization bypass:** The prior `Store.finalize_verified(reviewer_ref, approved_by)` accepts unauthenticated strings. Never expose it to live Codex agents. Before unattended operation, enforce a provider-originated, single-use attestation in the canonical state transition and gate/deprecate the legacy direct call.
- **Stored verdicts are not permanently valid.** On head SHA / review / CI changes, a fresh `ReviewPolicy.assess` is mandatory; never approve from a cached row alone. External permissions, protected-branch policy, and CI authenticity must be checked by future provider adapter.
- **No automatic reviewer task DAG yet.** PR-04b/05 must orchestrate reviewed code vs. task dependencies so `review_of` becomes eligible only after implementation reaches `verified` (not just `queued` or `finished`), while keeping write locks until approval.
- **No genuine Plus-hosted apps, uploads or GPT-6 High model proof.** Offline callback tests do not establish any of these.

## Tests

Local Python 3.13 targeted tests:

```shell
PYTHONPATH=src pytest -q tests/test_orchestrator_review_gate.py tests/test_orchestrator_callback_policy.py
# 4 passed (each test exercises multiple negative cases)
python -m compileall -q src tests
```

The baseline PR tests, full Octo-Lex suite, Ruff and Windows CI must run on the exact final head SHA before any merge; they are not claimed as green here.

## Next gates

1. PR-04b: connect strict review approvals to the canonical `Store.finalize_verified` guard; make unauthorized direct completion impossible. Add review-task readiness to scheduler; stale review/CI invalidation.
2. PR-05: authenticated Codex CLI/MCP adapters, subscription cursor/replay and low-token structured events.
3. PR-06: authorization-checked attachment upload and app capability adapters, with real per-file confirmations.
4. PR-07: only an explicitly permitted live transport, strict model/effort gate, rate-limit handling without blind resend.

No auto-merge, no live requests, no account limitations bypassed.