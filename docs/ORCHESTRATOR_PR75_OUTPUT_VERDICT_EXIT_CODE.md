# PR #75 — Exit 0 only for the expected completed output

Parent Draft #74 SHA `09d2490b874007a12764200906f7793f20e2bbe1`. Follow-up finding F01:
`turn/completed` alone was still capable of making
`scripts/pilot_one_codex_turn.py` return CLI exit **0** despite no completed
agent message or the wrong text.

The manual pilot CLI now exits 0 only if the turn is terminal completed **and**
the bounded final answer matches the deliberately pinned hobby test target
`ORCH_TEST_OK`. Otherwise it exits 2 and keeps the no-retry receipt.

The inspector distinguishes:
- `TERMINAL_OUTPUT_MATCHED_UNREVIEWED` (exit 0, not independent proof)
- `TERMINAL_OUTPUT_MISMATCH_OR_MISSING` (exit 2)
- `LEGACY_TERMINAL_OUTPUT_UNCHECKED` (exit 2 for old receipts)
- `TERMINAL_FAILED_OR_INTERRUPTED` and quarantine/incomplete states (exit 2).

Offline synthetic regressions are added, no real provider is contacted.
The real local Codex version/schema acceptance is still outstanding.
