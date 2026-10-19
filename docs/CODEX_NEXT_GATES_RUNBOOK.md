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
