# Phase 48a: read-only app-server protocol contract (offline)

Parent: [Draft PR #47](https://github.com/MartinezS8/chatgpt-web2api/pull/47)
at exact SHA \`1ca44159d89a1dd2150a9a4f4c3355bb71920a9b\`.

## Scope delivered

\`app_server_contract.py\` is a **pure in-memory, no-I/O** fixture contract:
- initialization response + \`initialized\` notification;
- \`model/list\` matching the *exact* requested model and reasoning effort, no fallback;
- one \`thread/start\` and one \`turn/start\` using a read-only sandbox;
- explicit session, thread, turn, and request-ID correlation;
- terminal completion labeled \`transport_completed_unverified\`, not work evidence;
- malformed responses, mismatched IDs, server-initiated approval requests, failures,
  interruptions and replayed terminal events fail closed.

The module **does not** spawn \`codex\`, write JSONL to stdio, import a browser driver,
start a model turn, read private credentials, upload files, operate on GitHub, or
transition a real task state. It grants no remote send permission or production
finalization. Legacy \`Controller.dispatch\`, worker activation and the offline
MockSandbox are unchanged.

Protocol basis: official Codex App Server documentation:
https://learn.chatgpt.com/docs/app-server

Server versions may evolve. This is only a preliminary schema/sequence contract;
do not claim compatibility with the user's installed Codex binary without generating
and comparing that version's \`codex app-server generate-json-schema\` output.

## Follow-up gates

1. Phase 48b adds a bounded synthetic JSONL subprocess harness and adversarial
   transcripts; it still has no Codex process or provider connection.
2. Phase 48c must add durable \`worker_session\` / \`turn_id\` / \`request_id\` /
   idempotency and sent/unknown-delivery records in SQLite *before* any future
   authorized send. Do not reconstruct a send permit on restart. Unknown delivery
   means pause and explicit reconciliation, never blind resend.
3. Implement explicit sandbox, Windows worker account isolation, one allowed Git
   worktree and a process allowlist. A subprocess with the same user/token is not
   protected from controller secrets by path prechecks alone.
4. Use \`model/list\` and version-pinned generated schemas to confirm model/effort.
   App-server is not equivalent to ChatGPT web apps, plugin selection or uploads.
5. Keep the installed private workspace, mock/demo API and MCP observer's eight
   read-only tools intact. No live run without separate user authorization.
6. Windows 11 and Python 3.12 only; strict offline tests, Ruff, full-history
   Gitleaks, wheel/sdist and installed CLI/MCP-smokes on the final exact commit.
7. Review the contract carefully for SDK compatibility and breakage before expanding
   its scope. Do not mark model/effort/server availability verified: tests use fakes.

## Stop conditions

- Cross-thread/turn event, unsupported requested model/effort, unknown delivery,
  unexpected server approval request -> fail closed and operator review.
- No production task finalization or scope unlock from \`turn/completed\`.
- Windows hostile same-user TOCTOU remains FAIL, second-user ACL denial NOT TESTED.
- No automatic PR merge or code-approval authority.
