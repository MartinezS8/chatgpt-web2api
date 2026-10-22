# PR-51 – Offline operator reconciliation review (NO AUTHORITY)

## Baseline and scope

Stack on Draft PR #50 exactly at
`0b54a8c2bfdc3ed79463afe3d2f068a18c4a0576`.
Windows 11 / Python 3.12 only. This is an offline-only, read-only operator
triage feature, NOT the complete authenticated Phase-48c reconciliation gate.

### Implemented

- `OperatorReviewBoard` uses the existing `Observer` with fixed read-only
  queries. It lists attempts in quarantined or unverified states, exposing
  bounded status fields but no prompt, claim, session-key or credential.
- `preview(attempt_id, disposition)` calculates the review requirements for
  unresolved, independently delivered or independently not-delivered cases.
  The preview makes **no database modifications**.
- CLI `operator-review-queue --limit 20` and `operator-review-preview
  --attempt-id ID --disposition delivery_unresolved`, with `--db` or
  `--private-workspace LABEL`. These commands execute **before** any Store
  initialization or data writes.
- Old unauthenticated `record_operator_disposition` annotations remain
  non-authorizing even if they claim that independent evidence was reviewed.
- A preview never authorizes send, retry, credential access, evidence,
  finalization or quarantine release.

### Example (existing local database; no accounts)

```powershell
python -m chatgpt_web2api.orchestrator --db C:\\Temp\\synthetic.sqlite3 operator-review-queue
python -m chatgpt_web2api.orchestrator --db C:\\Temp\\synthetic.sqlite3 operator-review-preview --attempt-id ATTEMPT --disposition delivery_unresolved
```

For an existing, explicitly provisioned private Windows workspace, replace
`--db ...` with `--private-workspace LABEL`.

### Hard acceptance boundaries

The Windows operator identity is **NOT authenticated**. A CLI invocation by a
process under the same Windows SID cannot prove independent human approval;
hashing a user-supplied name is NOT identity verification. This PR cannot
resolve quarantine, issue a new attempt or enable the live Codex transport.

Next phase must design an actual trusted **Windows credential/token/authentication
boundary**, independently test second-user ACL denial and verify binding
of user action to an attempt, evidence digest, one-time nonce, expected state
version and atomically recorded decision. Any confirmation of non-delivery
must not automatically send a new turn.

Same-user Windows hostile TOCTOU is still FAIL, second-user effective ACL
denial NOT TESTED, real worker NOT TESTED, production NOT READY.

CI: exact SHA Windows/Python 3.12 strict non-account-E2E, Gitleaks full
history, wheel/sdist, fresh wheel offline/MCP/CLI smokes; no actual provider.
