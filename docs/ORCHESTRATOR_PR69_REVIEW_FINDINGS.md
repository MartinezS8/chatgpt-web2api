# PR #69 — Review fixes and handoff

Parent Draft PR #68 exact `c250c348975d3d113a3da3a3fcff4c75ee5752dd`.

## Concrete review findings

**F-01 (receipt wrong integer type):** The prior receipt inspector tested
`intent.get("max_turn_starts") != 1`. In Python, `True == 1`,
so a JSON boolean passed the supposedly strict one-send counter.
Now `type(...) is int` and the intent's start status must match the
documented durable-intent contract. Added parametrized regressions.

**F-02 (conflicting terminal correlation):** The one-turn pilot correctly
compared the nested `turn.id` on `turn/completed`, but ignored an
optional top-level `turnId` that contradicted it. Now rejects such
contradictions; synthetic fake server proves it quarantines without replay.

**F-03 (stale operator runbook):** The old German runbook led with PR #63
and omitted the four required schema-selector flags from the illustrated
live command. It now provides exact flags, an offline preflight step,
read-only receipt review and explicit local-Codex-only gates, targeting
the stacked review branch rather than old `master`.

## Outcome / non-goals

All improvements are offline and backwards-compatible with the recorded
single-turn receipt shapes. No actual Codex model/account tests were
run via GitHub. A new detailed Gate-1 through Gate-5 review matrix lives at
`docs/ORCHESTRATOR_REVIEW_GATES_AND_CODEX_HANDOFF.md`.

The prior stack remains Draft. No merge, login, provider call or real
worker dispatch occurs as part of this PR.
