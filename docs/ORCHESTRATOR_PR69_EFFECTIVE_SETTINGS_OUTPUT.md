# PR #69 — Review findings F01/F02: output + effective thread settings

Stacked on Draft PR #68, exact parent `c250c348975d3d113a3da3a3fcff4c75ee5752dd`.

- Store only a **bounded** completed `agentMessage` text preview and SHA256,
  and separately compare to the *pilot-specific* target `ORCH_TEST_OK`. An
  empty or wrong answer never receives `assistant_output_matches_expected=True`.
  A terminal transport remains `transport_completed_unreviewed`: automatic
  task approval/finalization is **never** implied.
- Check effective top-level `thread/start` response `model`, `cwd`,
  `approvalPolicy` and `sandbox` in addition to JSON Schema. An actual
  differing value rejects the attempt BEFORE `turn/start`. Accepts the
  read-only sandbox's protocol enum representation in synthetic fixtures.
- Reject `model/rerouted` rather than silently logging the originally
  requested model as the model used.
- Existing fake transport remains separate. Negative tests exercise wrong
  content, absent agent message, sandbox/model/cwd/approval drift and rerouting.

A successful text comparison is a local receipt claim, NOT independent
provider evidence. Model IDs, effective model schemas and output-item
structure must be independently validated against the actual local Codex
`0.163.0-alpha.11` schema on Windows. No provider send, login, merge or
production change performed here. Exact-HEAD hosted Windows Strict + Gitleaks +
wheel/sdist installed smoke still required.
