# Orchestrator — GitHub-Review, Codex-Handoff und Release-Gates

**Repository:** `MartinezS8/chatgpt-web2api`.
**Aktueller Prüfzweig:** stacked Draft-Linie bis einschließlich PR #87,
plus enger Code-/Dokumentations-Follow-up auf dessen HEAD.
Keine Annahme, dass irgendeiner dieser Drafts bereits nach `master`
gemergt wurde.

**Ziel:** Ein hobbytauglicher lokaler Codex-Orchestrator mit bis zu fünf
Workern, aber bewusstem Übergang von Mock → echter Einzelturn →
zwei → fünf Worker. CI, reale Transportfähigkeit und fachliches Review
sind **getrennte** Beweise. Kein künstlicher Enterprise-Isolationsgate.

## Review-Gate 1 — GitHub-Stack und Regressionen

- [ ] Gestapelte PRs, Eltern-Refs, Heads und Merge-Base vollständig
      überprüfen; nicht nur die letzte PR als diff gegen `master`.
- [ ] Auf **exaktem HEAD**: Windows Python 3.12 Strict (pytest,
      Ruff, compileall), Gitleaks full-history, wheel/sdist/installed CLI,
      MCP-Smokes, CI-Grün dokumentieren.
- [ ] Review der kritischen Pfade: manuelle Einmal-Zustimmung, nur
      eine `turn/start`-Nachricht, ACK-/Terminal-Korrelation,
      Readonly-Policy, Audit-v2, absichtliche nicht-automatische Retry-Sperre.
- [ ] Abweichungen als konkreter Befund mit Pfad, Repro, Regressionstest,
      Fix-SHA und `OPEN/FIXED/LOCAL_ONLY` dokumentieren.

**Review-Finding R-01 (fix in diesem Follow-up):** Python
`True == 1` ließ ein `intent.json` mit
`"max_turn_starts": true` als numerisch korrekt erscheinen. Nur
**echte Integer 1** und der erwartete Intent-Status sind nun zulässig.
Synthetic regression added; no user/account input is read.

**Review-Finding R-02 (bereits erledigt in #87):** widersprüchliche
Top-Level- und verschachtelte Turn-Korrelation wird bereits vom
aktuellen Code abgewiesen. Kein älteres Pilotmodul aus #68 über #87
überschreiben.

## Review-Gate 2 — lokale echte Codex-Schemas und MCP-Grenzen

- [ ] Worktree auf den **neuesten verifizierten Draft-HEAD**, `git status`
      und SHA dokumentieren.
- [ ] Native lokale Codex.exe und Version/Manifest
      (jüngster lokal berichteter Stand: **0.164**), Binary-SHA pinnen;
      alte 0.157-/0.163-Samples nicht für aktuelle APIs ausgeben.
- [ ] Vier `v2/`-Schema-Dateien für `thread/start` und
      `turn/start` Requests/Results gegenüber aktuellen echten
      generierten JSON-Schemas manuell verifizieren.
- [ ] `scripts/preflight_codex_wire.py` offline mit den **genau
      vorgesehenen** Modell-/Effort-/CWD-Parametern PASS.
- [ ] Mit `prepare_codex_mcp_source_map.py` exakte lokale MCP-Quellen
      inventarisieren, Unbekanntes abweisen, v2 Snapshot/CWD binden;
      `probe_codex_start_matrix.py` und
      `audit_codex_mcp_config.py` lokal prüfen.

**Exit:** Schema-/Provenienzprüfung erfüllt. Keine
Behauptung eines echten Inferenz-Turns oder unabhängig geprüften
Sandbox-Prozesses.

## Review-Gate 3 — ein echter harmloser Codex-Turn

- [ ] Benutzer meldet sich selbst lokal an, **keine** Cookies/Tokens
      oder `auth.json` nach GitHub/ChatGPT.
- [ ] `--allow-account-discovery` mit gebundener MCP-Map,
      angebotene Modellkennung/Reasoning-Stufe prüfen.
- [ ] MXC/Read-only-Bedingungen und verbleibendes Risiko
      eingebauter Read-only-Tools akzeptieren (nicht als Scratch-only-
      Isolation darstellen).
- [ ] Genau ein `--allow-one-turn`; frisches Receipt-Verzeichnis,
      `intent.json` vor dem Send, **kein** Auto-Retry.
- [ ] Modellantwort exakt `ORCH_TEST_OK`, korrelierte
      Thread-/Turn-ACKs/Terminalevents, Audit-v2/Item-Lifecycle,
      kein unerwartetes Tool-Ereignis.
- [ ] `inspect_pilot_receipt.py`: Intent-Hash-Bindung,
      Ausgabe-Audit und Quarantäne-Status bewerten.
- [ ] Nichtvollständige, unbekannte oder widersprüchliche
      Delivery nicht wiederholen; lokale Ergebnisse ohne Secret-Leaks
      im Issue kommentieren.

**Exit:** erst nach realem positiven Ein-Turn-Evidenzbericht;
sonst konkreter, reproduzierbarer Blocker.

## Review-Gate 4 — echte Scheduler-/Outbox-Integration

- [ ] Ein-Turn-RPC-Pfad mit `DispatchOutbox` und
      `AppServerDeliveryLedger` in abstimmbarer, idempotenter
      Claim-/Delivery-Semantik verbinden; nicht direkt aus dem
      manuellen Pilot die Produktionsfreigabe ableiten.
- [ ] Ungewisse ACKs, Prozessabsturz, Restart, konkurrierende
      Claims und Stale-Recovery gegen doppelten Send testen.
- [ ] 2 → 5 synthetische Worker, getrennte Task-Pakete, klare
      Abschlussbelege; danach optional 2 → 5 **echte** Worker
      nach bewusster lokaler Freigabe.
- [ ] Operator-/Reviewer-Evidence und Merge-Gates bleiben von
      Transport-`completed` und erfolgreichen Modelltexten getrennt.

**Exit:** reproduzierbare Mock- und lokale Worker-Nachweise,
kein automatisch freigegebener unreviewter Provider-Output.

## Review-Gate 5 — Merge und Hobby-Release

- [ ] Drafts in nachvollziehbarer Stack-Reihenfolge reviewen,
      bei Änderungen CI auf dem integrierten SHA wiederholen.
- [ ] Passwort-/Accountdaten bleiben lokal, sensible Diagnosedateien
      werden nicht in Git übernommen.
- [ ] Bedienbare Windows-Anleitung, Recovery/Reset, eindeutige
      Fehlermeldungen für Hobby-Nutzer final prüfen.
- [ ] Merge ausschließlich nach ausdrücklicher Entscheidung,
      **kein** Auto-Merge für die vorbereitenden Drafts.

## Zuständigkeiten

**Hier in GitHub möglich:** Quelle/Diffs prüfen, Tests ergänzen,
CI-Fehler korrigieren, sichere Dokumentation, Draft-PRs,
Review-Issue/Checklisten, Mock-Scheduler-Tests.

**Nur lokal bei Codex/Windows:** korrekte native exe, echte lokale
0.164-Schemas, MCP-Quellnachweise, Codex-Login, account/model read,
erster echter Turn, reproduzierbare Backend-/Sandboxbeobachtung und
kontrollierter 2-/5-Worker-Livetest.

Das vollständige lokale Ablaufskript mit bereits vorhandenen MCP-
und MXC-Schutzschaltern steht in
`docs/ORCHESTRATOR_HOBBY_CODEX_RUNBOOK_DE.md`.
