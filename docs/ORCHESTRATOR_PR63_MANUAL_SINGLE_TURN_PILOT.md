# PR #63 — Manual single-turn local Codex pilot (experimental)

Parent Draft PR #62 at `e2050617a67a7116bb6d6a803fc21c96a4e6cdd9`. This is a real-process adapter
**prepared in GitHub only**; it has not launched a real provider process and
does not integrate with the canonical multi-worker scheduler.

The opt-in `scripts/pilot_one_codex_turn.py` starts with the PR #62 offline
binary/schema pin and PR #61 model discovery. The chosen model ID and effort
must be returned by the local account catalog. A text prompt is loaded from
an explicit small UTF-8 file. The receipt directory must be **NEW** and outside
the repository. A hashed send intent is fsynced before the real app-server is
launched. The script sends exactly one `thread/start` and at most one
`turn/start` with `approvalPolicy=never` and `sandboxPolicy=readOnly`,
then waits for the matching correlated `turn/completed` event. There are no
server-request approvals, retries, merges, file uploads or additional turns.
An unconfirmed send leaves `quarantine.json`, and the original receipt
directory cannot be reused. A completed transport is still **unreviewed**.

### User/Codex manual steps (NOT EXECUTED)

1. First obtain terminal CI on exact #63 HEAD; compare your local installed
   0.163.0-alpha.11 generated schema with the exact requests/responses. If
   `thread/start`, `sandbox`, `approvalsReviewer` or response layouts differ,
   FIX and test the adapter before any live call. Never assume old 0.157
   fixtures prove compatibility.
2. Pick a **new empty local scratch directory** with no personal files.
   For hobby-only testing this is a pragmatic first step, but a read-only
   Codex sandbox does not prove isolation from files elsewhere under the same
   Windows identity. Avoid secrets and privileged contexts.
3. Sign in yourself with the official Codex CLI/browser, with no token export.
   Run the PR #62 doctor with `--allow-account-discovery`, and choose the
   exact returned model ID and supported effort.
4. Create a text file outside the repository with a harmless prompt such as
   `Output exactly ORCH_TEST_OK. Do not use tools.`
5. Only after consciously choosing to issue ONE provider turn, run:

```powershell
py -3.12 scripts/pilot_one_codex_turn.py --codex-exe "C:\FULL\PATH\codex.exe" --schema-root "C:\LOCAL\schema-capture" --cwd "C:\LOCAL\empty-scratch" --prompt-file "C:\LOCAL\pilot-prompt.txt" --receipt-dir "C:\LOCAL\NEW-receipt" --model "<ACTUAL_MODEL_ID>" --effort "<ACTUAL_EFFORT>" --allow-one-turn
```

If delivery is ambiguous, do NOT rerun with a new directory without
reviewing the old receipts and independently checking the CLI session state.
This disposable pilot does not implement cross-process authenticated IPC,
protected controller DB, network sandbox attestation or durable model result
provenance. It is not production approval, nor an automatic five-worker
orchestrator. For higher-assurance operations, add the previously planned
Windows identity and controller boundaries first.

### Exact acceptance
Native Windows Python 3.12 + Ruff/compileall, Gitleaks, wheel/sdist,
installed offline CLI/MCP and synthetic subprocess tests on exact HEAD.
Codex must separately validate the live schema and run ONE authorized test;
hosted green CI alone is not evidence of account success.
