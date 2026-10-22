# PR #62: Local Codex pilot doctor and short Codex handoff

Stacked on PR #61 exact parent `fe64f765d6bc643648c3baeaf27c7f15754da5d5`. This is a CLI preflight,
NOT a real-worker implementation.

The new `scripts/orchestrator_pilot_doctor.py` consolidates the exact native
Codex binary SHA/version pin, captured schema manifest verification and (only
if explicitly opted in) local read-only account/model discovery from PR #61.
It verifies a deliberately chosen model ID and reasoning effort against actual
catalog entries. It never chooses model defaults silently and never sends a
thread, a turn, a plugin call or any code change.

On Windows 11, Python 3.12, after regenerating the offline schema receipt if
Codex.exe has been updated:

```powershell
# Strictly offline except running codex.exe --version
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "C:\FULL\PATH\codex.exe" --schema-root "C:\LOCAL\schema-capture" --cwd "C:\LOCAL\empty-workspace"

# OPTIONAL later: deliberately ask the logged-in account about its models
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "C:\FULL\PATH\codex.exe" --schema-root "C:\LOCAL\schema-capture" --cwd "C:\LOCAL\empty-workspace" --allow-account-discovery

# Choose actual returned model and effort, not a hard-coded example
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "C:\FULL\PATH\codex.exe" --schema-root "C:\LOCAL\schema-capture" --cwd "C:\LOCAL\empty-workspace" --allow-account-discovery --model "<RETURNED_MODEL_ID>" --effort "<RETURNED_EFFORT>"
```

**Next task for Codex:** Validate the local `0.163.0-alpha.11` schema fixtures
from PR #60, verify the #61 real **read-only discovery command** after user
login/consent, preserve the JSON receipt outside the repository and report
exactly which models/efforts are available without copying tokens or user
account data. If process handshake fails, diagnose before adding any turn.
Then build and review the *separate* one-turn, idempotent dispatch adapter
using the existing delivery ledger and approved test directory. The latter
is NOT already implemented by this doctor and needs a separate explicit
consent for any first real inference.

The project is for local hobby use: VM/service-account hardening and enterprise
review process may be treated as optional for experimentation **only after**
the user understands the Windows same-user access risk; no developer action
in this PR changes the currently disabled live-send gate.
