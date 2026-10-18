---
name: orchestrator-control
description: Use for safe local creation, inspection, reservation and recovery of multi-agent software-project tasks in this repository. Do not treat it as a ChatGPT browser or connector integration.
---

# Codex local orchestrator control (preview)

Use `python -m chatgpt_web2api.orchestrator --json <command>` with an explicit `--db PATH` or `CHATGPT_ORCHESTRATOR_DB` environment variable. This skill explains the project's own CLI. It does not install CLI-Anything, connect external accounts or grant permission to automate ChatGPT.

Read [the implementation and limitations](../../docs/ORCHESTRATOR_V3_CLI_ANYTHING.md) before first use.

## Safe sequence

1. `--json capabilities`: inspect boundaries; live chat dispatch is **false**.
2. `--json status --project PROJECT`: inspect active slots and task states.
3. Prepare a UTF-8 prompt file in the approved local project area. Never put credentials in the prompt file.
4. `--json create-task --id TASK --project PROJECT --role implement --prompt-file ABSOLUTE_PATH --write-scope repo:src/owned-folder`: register an immutable task hash.
5. `--json list-tasks --project PROJECT`: check recorded hashes, dependencies and scopes.
6. `--json claim --project PROJECT`: reserve an eligible local slot; **does not send a message**.
7. After a crash, `--json recover --project PROJECT` marks uncertain sends for human reconciliation. Never blindly resubmit an uncertain delivery.
8. `--json events --id TASK`: inspect the immutable event trail.

### Rules

- `review` workers have no write scopes; do not represent their text as evidence of successful changes.
- Keep the Git SHA/PR evidence and target ownership check outside the browser response.
- Never claim GPT-6/High is active unless positively verified through an authorized interface.
- Do not assume five reserved slots equal five simultaneously allowed account requests.
- No live UI automation, authentication, Supabase writes or GitHub merges are performed by this CLI.
- A human or separate evidence-aware workflow must approve merges, external mutation and any uncertain delivery.