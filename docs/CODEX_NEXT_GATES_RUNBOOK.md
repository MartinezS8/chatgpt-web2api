# Codex next gates — unmerged orchestrator PR stack

**Repository:** `MartinezS8/chatgpt-web2api`  
**Current base at the end of this phase:** `codex/orchestrator-v9-upload-app-preflight`  
**Date:** 2026-10-19

## Confirmed development artifacts

1. PR #1 — V3 task/store/CLI foundation; target `master`.
2. PR #2 — fenced pre-send state transitions and global write-scope quarantine; target PR #1 branch.
3. PR #3 — operator-asserted canonical resource aliases; target PR #2 branch.
4. PR #4 — immutable prompt/package snapshots, dispatch intent/outbox, event cursor; target PR #3 branch.
5. PR #5 — mock-only logical worker registry, scheduler and supervisor; target PR #4 branch.
6. PR #6 — offline callback inbox, simulated SHA-bound GitHub evidence, independent mock reviewer checks and bounded fix proposals; target PR #5 branch.
7. PR #7 — observer-only Codex CLI and stdio MCP control surface (read-only); target PR #6 branch.
8. PR #8 — mock-only attachment receipt / per-message app and exact model/effort preflight; target PR #7 branch.

**All PRs are Draft and unmerged.** Do not interpret this as working web automation. Pull-request head SHAs must be re-read before integration because they can change.

## Immediate Codex actions (offline, Windows)

Use the user's own local development environment and permissions. **No unattended network/API/account test by default**.

```powershell
git clone https://github.com/MartinezS8/chatgpt-web2api.git
cd chatgpt-web2api
git fetch origin
git switch codex/orchestrator-v9-upload-app-preflight
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python scripts/verify_orchestrator.py
python scripts/verify_orchestrator.py --full
```

The validator runs syntax compile, pytest (non-E2E) and Ruff; it reports machine-readable JSON and returns exit code 1 on failure. It never starts a browser, submits a ChatGPT request, invokes GitHub writes or uses connected apps. For a constrained local environment, `--skip-lint` skips only Ruff and must not count as a green release gate. **Do not override test failures.**

`chatgpt-orchestrator-observer-mcp` is a separate stdio-only, read-only tool server. Verify its real MCP 1.26 handshake on Windows and ensure advertised tools contain no mutation methods. Its read-only SQLite DB access must use a Windows user-restricted database path, not a globally readable shared directory.

## Merge/readiness gates (hard blockers)

- [ ] Ruff success, full upstream non-E2E tests, Windows + supported Python versions, independent code review; inspect each PR's cumulative merge-base and exact HEAD SHA.
- [ ] Schema evolution and Windows file ACL audit (task prompts/attachment snapshots are sensitive). Safe WAL backup/restore and on-disk migration tests.
- [ ] Verify no implicit auto-retry in every external send path. Legacy `Controller.dispatch` and Octo-Lex `retry_on_rate_limit` must be gated by one durable, fenced outbox; external exactly-once cannot be presumed.
- [ ] Confirm central authority for `Store.finalize_verified`: the older method accepts asserted reviewer/operator strings. The new mock review ledger does **not** itself stop a privileged caller from using the legacy method. Before making any write tool available to an agent, require provider-verified exact SHA + successful CI + independent review + genuine human approval when needed.
- [ ] Canonical resource aliases are operator assertions, not external GitHub/Supabase permissions; integrate authenticated provider ACL checks before any write.
- [ ] One Codex MCP stdio connection is **not** five independently identified ChatGPT sessions; bind each worker to proven transport/session/target identities.
- [ ] Protect callback adapter and state-changing MCP tools with authentication, origin binding, per-attempt identity, deduplication and callback acknowledgment. MCP progress is advisory; completion must have provider-authoritative turn ID or remain unknown.

## PR-06B — real attachments/apps, if authorized

- Verify transport access to actual file-upload operation; upload sealed blob bytes, not original files. Record provider file ID, exact size/type/hash *and confirmed attachment status* before send.
- Handle partial uploads, quota windows, file type rejection, expired sessions, retries, and clean cancellation. Never send with an incomplete attachment set; never silently resend an uncertain chat message.
- Discover permitted app/plugin list for this specific worker account/plan/message. Selecting a connected app in one ChatGPT message does not prove it was selected in the next. Ask a real user to complete required approvals; never auto-confirm consent.
- Test an allowed three-file upload + one explicitly selected permitted app, and negative cases, using an authorized test account. Record executable proof: versions, IDs, screenshots/structured provider events and SHA.

## PR-07 — authorized transport and model/High gate

- Decide explicitly between officially supported Codex app-server and any separately permitted ChatGPT UI experiment. These are **not equivalent**: hosted ChatGPT connectors and ChatGPT Plus web-chat UI controls cannot be assumed to work in the app-server preview.
- Define `submit`, `observe`, `resume`, `reconcile`, `cancel` contract. Validate model *and* reasoning effort from trustworthy provider state; if `GPT-6 High` cannot be proven, **zero sends**, no fallback.
- One-worker opt-in E2E before attempts at multiple sessions. Measure account-bound throttling, long-thought completions, interruption recovery, callback duplication and unknown send status. Enforce Plan limits; no CAPTCHA or anti-bot circumvention.

## PR-08 — Windows reliability / security

- Per-user startup and Windows service/Task Scheduler lifecycle, safe stop/resume, local credential storage, ACL checks, audit redaction and SQLite WAL checkpointed backup/restore.
- Test 1/2/5 *logical mock* workers under subprocess crash, stalled callback, symlinked attachment, concurrent scheduler, token expiry, permission revoke and interrupted disk writes.
- An optional operator dashboard may read safe observer data; do not show secrets, browser profile tokens or attachment bytes.

## Expected evidence to attach to the PR before release

- Exact `git rev-parse HEAD`, `python --version`, supported OS, dependency lock/snapshot.
- JSON output from `python scripts/verify_orchestrator.py --full`, Ruff output and CI/run IDs if available.
- Separate signed-off real-transport capability/authorization decision with clear feature gaps.
- Each implemented gate has positive, negative and crash/replay tests; approval and mutation gates remain denied by default until independently verified.

**No GitHub Issues required.** This Markdown runbook and `ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md` are the single in-repository work queue. GitHub Actions may be configured and exercised by Codex later, as requested.

