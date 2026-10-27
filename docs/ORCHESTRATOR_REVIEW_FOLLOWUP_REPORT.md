# Review follow-up — strict receipt intent and current head handoff

Parent = exact PR #87 HEAD `be7ea93726b018a3fc6803e242dd2816c7a9c1d4`.

**R-01 (fixed):** In the read-only receipt inspector,
`intent.get("max_turn_starts") != 1` accepted JSON boolean `true`
because `True == 1` in Python. The inspector now requires
`type(value) is int`, exactly `1`, and the known durable
`possible_send_not_yet_verified` intent status. Negative tests
cover `true`, a numeric string, zero, wrong status and missing cap.
This does not add any new send, retry, login or filesystem writes.

**R-02 (already upstream):** PR #87 already rejects inconsistent
optional top-level `turnId` at terminal handling; the earlier
temporary review PR based on #68 was therefore explicitly closed,
not stacked or merged.

**R-03 (docs):** Preserved the existing current PR #87 MCP config
provenance, MXC sandbox opt-in, audited reply checks and local
Codex 0.164 caveats. Updated the operator guide with a
BOM-free Windows PowerShell test prompt, a copied-parameters
offline `preflight_codex_wire.py` step, links to the new
GitHub/Codex five-gate review plan and unambiguous Draft HEAD
selection.

All native login/MCP/turn results are left for the authorized
Codex instance on Windows. GitHub CI can only prove offline
behavior and packaging; it does not simulate the local provider.

### Zusätzlicher historischer Readiness-Befund (27. Oktober)

Die lokale Reportdatei `docs/ORCHESTRATOR_MCP_REFRESH_READINESS_REPORT.md`
erfasst einen Codex-0.164-Binary-Hashwechsel trotz identischer
Versionsangabe; die früher generierten 320 Schemas sind auf das
alte Binary gepinnt. Der aktuelle Hash muss vor jedem Pilot neu
erfasst und mit einem **neuen** Bundle verbunden werden.
Außerdem war der alte MXC-AppData-CWD-Test negativ; nur Temp
war zuvor positiv. Beide sind im Gate-2-Review als OPEN erfasst.
Das ist eine dokumentierte lokale Beobachtung, **kein** durch
diesen GitHub-PR ausgeführter Test.
