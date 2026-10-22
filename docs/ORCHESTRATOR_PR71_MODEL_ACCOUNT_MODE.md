# PR #71 — Accurate Codex catalog model and account mode

Parent #70 exact `80b24fc5e45cb85c1352f9fe0c4930a11339e14b`. Addresses review F07/F08, with explicit
distinction between `model/list` preset `id` and its actual `model`
slug. The manual pilot accepts a chosen picker ID, but sends the discovered
`model_slug` over `thread/start` and `turn/start`. The catalog report
includes supported input modalities, hidden flag and whether text input
is supported. Missing legacy `model` metadata defaults to `id`, explicitly
marked as unverified in `model_slug_declared`. Actual installed schemas and
requested model names must still be checked locally.

`account/read` is normalized into ChatGPT, API key, other or no-account
mode, without printing account email, cookies or tokens. The *manual hobby
pilot* requires an affirmative ChatGPT login mode; API-key accounts are
refused before intent, process or provider send to avoid unexpected billing.
Account discovery by itself may contact the service, but remains opt-in.
Visible model metadata returned by the official app-server is derived from
its catalog and may depend on the account's capabilities.

This is not an account entitlement audit nor a live-call authorization.
Tests use fake account/model fixtures; no real account calls, merges,
credential reads or worker launches happen in GitHub. Hosted exact-head
Windows Strict/Gitleaks/wheel+installed smoke required.
