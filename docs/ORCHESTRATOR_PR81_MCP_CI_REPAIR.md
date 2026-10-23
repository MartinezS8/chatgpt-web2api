# PR #81 — Strict CI Ruff repair + checked same-process startup args

Parent Draft #80, exact head `f494797b3cd5a1206815821fb2ff1ff7b2b47c48`.

PR #78 strict Windows/Python 3.12 run 39933923856 produced **1552 passed,
2 skipped, 20 subtests**, but its aggregate gate failed because Ruff I001
required separating two imports onto individual lines in
`tests/test_orchestrator_mcp_process_guard.py`. This cumulative descendant
fixes that import ordering and the similarly styled runtime-fence test import.
It does **not** claim parent #78's CI was fully green.

Two additional synthetic pilot tests prove:

1. The exact leaf override tuple returned by `verify_mcp_disabled` is passed
to both `discover_local_codex(startup_args=...)` and the actual app-server
`subprocess.Popen` command, with `app-server` as the last argument. No
unscoped second process is allowed by this wiring.
2. `--allow-one-turn` does not alone accept possible built-in read-only
tools: the separate acknowledgement is required before account access.

No real MCP process, login, app-server, HTTP connection or provider turn is
created by these tests. The owner must still identify the unknown server
source and check the actual native 0.163 protocol and effective MCP/app
catalog. Expected exact-head Windows Strict/Gitleaks/package-smoke is required
for this PR before labeling it PASS. `master` and persisted Codex settings
remain unchanged.
