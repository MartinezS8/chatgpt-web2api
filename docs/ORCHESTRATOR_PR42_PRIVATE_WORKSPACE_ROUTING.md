# PR-42 — Explicit private workspace routing, offline only

Parent PR #41 at `4c8dc7e1fdb641a7935e9f8d9b1d9ad380a0b64f`.

## Scope and authority

The final local Sol 6.1 report confirms recovery A PASS, Windows B PARTIAL,
and C an isolated CI-green draft candidate. Effective second-user ACL denial
and handle-relative immunity to hostile concurrent parent swaps remain untested.
This patch does NOT mark B PASS.

The new global CLI option `--private-workspace LABEL` opts into a **Windows-only,
already provisioned** private root at
`%LOCALAPPDATA%\\chatgpt-web2api\\LABEL`.
Provision first with `init-private-workspace --label LABEL`; never mutate
an existing legacy user's ACL or silently migrate their data.

Example (native Windows, omit any `--db` or `CHATGPT_ORCHESTRATOR_DB`):
```powershell
python -m chatgpt_web2api.orchestrator init-private-workspace --label offline-test
python -m chatgpt_web2api.orchestrator --private-workspace offline-test status --project p
python -m chatgpt_web2api.orchestrator --private-workspace offline-test create-task --id t --project p --role implement --prompt-file "$env:LOCALAPPDATA\\chatgpt-web2api\\offline-test\\prompt.txt"
python -m chatgpt_web2api.orchestrator --private-workspace offline-test staging-audit --root "$env:LOCALAPPDATA\\chatgpt-web2api\\offline-test\\blobs"
```

## Rules

- Verify existing root, current user SID, protected owner/DACL and existing
  database/blob child owner and non-broadening trustees before dispatch.
- At first provisioning, create the blob directory under the already protected
  root using ordinary DACL inheritance rather than calling Windows Python
  3.12.4+ `mkdir(mode=0o700)`, which may explicitly add Administrators and
  Owner Rights. Native CLI roundtrip tests verify this after reopen.
- The only database is `controller.sqlite3`; the only blob directory is
  `blobs`. Protected CLI operations derive these rather than trusting
  arbitrary `--db` or `--blob-root` inputs. Reject mixed `--db` and
  `--private-workspace` even when `--db` comes from the environment.
- Protected file inputs must be absolute regular files within the same private
  root. Explicit `--allowed-root` must resolve inside the root. When omitted,
  local seal attachments default to the protected root.
- Protected staging audit/cleanup accepts **only** the root or its blob
  directory, no arbitrary directories or path aliases.
- Worker claim's existing `--blob-root` parameter must match the verified
  private blob directory. Real transports and dispatch remain disabled.
- Existing `--db` operations and programmatic `Store`, `TaskPackages`,
  and backup APIs remain **legacy offline compatibility**, without any
  private-storage assurance. They must not be used with untrusted roots or
  presented as production ready.

## Still open / nonclaims

This is a **CLI routing gate**, not a cryptographic proof of root ownership and
not a handle-relative Windows filesystem implementation. ACL and pathname checks
are point-in-time. A sufficiently privileged process or other actor with write
access to a parent can still attempt concurrent swaps; the CLI is not a safe
sandbox for untrusted folder inputs. Native effective-denial testing under an
independently authorized restricted second user remains mandatory.

Direct library callers, non-CLI tools and externally initiated MCP/worker
integration do not automatically inherit the private-storage contract.
A separate design/review must assess each such entry point before any real
provider or account transport is allowed. Storage B and Production Ready stay
PARTIAL / NOT TESTED. No provider operations, merges or user-data rewrites.

## Acceptance

- New cross-platform path/CLI contract negative tests (native DACL loader
  stubbed on POSIX, **not** proof of actual Windows ACLs).
- GitHub diagnostic exact-commit matrix across Windows/macOS/Linux and
  Python 3.11/3.12, strict Ruff + full non-account-E2E suite, wheel build.
- On actual native Windows: create a disposable private root and verify
  positive protected CLI create/seal/audit/backup/restore and denial when
  owner/DACL/child permissions change; second-user test stays NOT TESTED until
  separately authorized.
