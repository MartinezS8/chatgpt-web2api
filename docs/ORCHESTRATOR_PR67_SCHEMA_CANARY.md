# PR #67 — Prevent false-green permissive wire schema selections

Parent Draft PR #66 exact `fff672a89e577d5bbf5a9e3078c1470f4cac86b0`. Although schema files were SHA-pinned
and four explicit selectors were mandatory, a user could point one selector at
a method-agnostic schema such as `{"type":"object"}`; the validator would then
report PASS for malformed method-specific input or output. This is especially
dangerous while migrating 0.157 mock fixtures to the installed 0.163 alpha.

This PR introduces four fixed **negative canary instances**, one per RPC
params/result selection. A selected schema that validates its obviously
broken canary is rejected at construction, before account discovery or
`thread/start`. Existing synthetic fixtures are made slightly more specific
to represent real object contracts and cover the new behavior. All other
schema hashes, local-only resource resolution and explicit selection rules
remain unchanged.

The canary is a necessary diagnostic for grossly wrong selectors, **not**
independent proof of correct method/file mapping, protocol compatibility,
an authenticated account, sandbox enforcement or delivery. The exact
generated Codex schemas still require local validation and human review.
No real worker is started here; leave Draft until exact-HEAD CI terminal green.
