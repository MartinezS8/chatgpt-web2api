# Orchestrator: Review- und Codex-Abnahmeplan

## Scope / verifizierter Ausgangspunkt

Repo: `MartinezS8/chatgpt-web2api`; ein lokaler Hobby-Orchestrator
mit maximal fünf getrennten Codex-Workern als Ziel.

Die Pilot-Erweiterungen sind aufeinander gestapelt:
`#59 -> #60 -> #61 -> #62 -> #63 -> #64 -> #65 -> #66 -> #67 -> #68 -> #69`.
Frühere PRs #49–#58 bilden weitere Grundlagen.
**Ein erfolgreicher CI-Job ist keine Authentifizierung, keine echte
Provider-Inferenz und kein Merge.**

Die folgenden Gates sind sequenziell. Für die Hobby-Variante ist
keine Enterprise-VM oder Compliance-Zertifizierung zwingend,
wohl aber die minimale Integrität des Testordners und
das Vermeiden ungewollter doppelter Sends.

### Gate 1 — Github-Code und CI (ChatGPT/GitHub möglich)

- [ ] Stacked PR-Parents, HEADs, geänderte Dateien und Merge-Base
      auf Konsistenz prüfen; `master` nur nach separater Entscheidung.
- [ ] Auf **dem exakt vorgesehenen PR-HEAD**: Windows/Python 3.12
      Strict offline inklusive pytest, Ruff und compileall.
- [ ] Vollständige Gitleaks-Prüfung und externe Build-Smokes
      für wheel/sdist, installierte CLI/MCP.
- [ ] Pflichten im Review prüfen: keine API-Keys in Dateien,
      kein versteckter Retry, keine stillen Fallbacks zu Fake-0.157.
- [ ] Gefundene Defekte durch neue Regressionstests und PR-Fixes beheben.
- **Exit:** alle Checks terminal PASS, offene Review-Kommentare
  geklärt, noch **keine** Aussage über echte Codex-Wire-Kompatibilität.

### Gate 2 — Lokaler Codex-Schema-Abgleich (Codex/Windows)

- [ ] Neuen Worktree anlegen, SHA verifizieren, Scratch/SchemaDir anlegen.
- [ ] Native vertrauenswürdige Codex.exe `--version` + 0.163+-Manifest
      mit Hash erfassen; nie ein altes Manifest still übernehmen.
- [ ] Genau vier reale generierte Schema-Dateien an RPC-Methoden mappen
      und `preflight_codex_wire.py` ausführen.
- [ ] Fehler bei `sandbox`, `approvalPolicy`, `serviceName`,
      `thread.source`, `effort` oder Result-Shape korrigieren,
      ausschließlich anhand der wirklichen lokalen Schemas.
- **Exit:** Offline-Request-Validierung PASS, echte
  Response-Validierung weiterhin als **offen** dokumentiert.

### Gate 3 — Lokale manuelle Provider-Verbindung (Codex/Windows)

- [ ] Benutzer meldet sich lokal selbst an; kein Teilen von Secrets.
- [ ] Nur mit `--allow-account-discovery` Account/Modelle abfragen.
- [ ] Exakte Modellkennung und Reasoning-Stufe überprüfen.
- [ ] Genau einen `--allow-one-turn` mit harmloser Aufgabe auslösen.
- [ ] Response/Benachrichtigungen, `intent.json`, `result.json` oder
      `quarantine.json` via `inspect_pilot_receipt.py` auswerten.
- [ ] Bei unklarer Zustellung nicht wiederholen; Fehlerszenario
      und Abhilfekorrektur dokumentieren.
- **Exit:** ein echter Einzelturn mit passenden Thread/Turn-IDs
  oder ausdrücklich dokumentierter Blocker; kein automatisches
  'fertig' nur aufgrund eines terminalen Transportevents.

### Gate 4 — Outbox- und Multiworker-Integration (danach)

- [ ] Einzelturn-Adapter kontrolliert mit bestehendem
      `DispatchOutbox`/`AppServerDeliveryLedger` verbinden.
- [ ] Restart/unknown delivery, idempotente Claim-/Dispatch-Sperre,
      Stale-Recovery und isolierte Tasks ohne doppelte Sends testen.
- [ ] Erst Offline-Tests mit 2 und danach 5 Mock-Workern.
- [ ] Erst nach lokaler Pilotfreigabe 2 reale Worker testen,
      danach bewusst auf bis zu 5 erweitern.
- [ ] Reviewer/Freigabe, Evidence, Finalisierung und Merge
      getrennt von Transport-Ack prüfen.
- **Exit:** kein verlustiger/duplizierter Task bei Recovery,
  Resultate nachvollziehbar, Reviewer-Prozess funktioniert.

### Gate 5 — Zusammenführung und Hobby-Release

- [ ] Draft-PRs in Stack-Reihenfolge prüfen; bei Konflikten
      explizit Base/HEAD neu überprüfen.
- [ ] CI auf dem jeweils tatsächlich integrierten Commit erneut grün.
- [ ] Dokumentation, lokale Betriebsanleitung, Reset und
      Fehlermeldungen für Hobby-Setup verifizieren.
- [ ] Benutzer entscheidet über Merge; keine automatische Integration.

## Review-Entscheidungsprotokoll

Jeder Befund enthält: `PR/SHA`, Pfad, Reproduktionsschritte,
Erwartung/Ist, Auswirkung, Testnachweis, Fix-Commit und
`OPEN/FIXED/LOCAL_ONLY`. Kritische Befunde verhindern eine
Behauptung von Live-Readiness; Feature-Wünsche können als Backlog
markiert werden. GitHub-Actions-Checks sind automatisierte
Tests, **kein** unabhängiges Human-Code-Review.

## Aufgabenverteilung

**ChatGPT via GitHub:** Source-/Diff-Review, Tests, Dokufixes,
Draft-PRs, CI-Logs, Review-Befunde, Backlog-/Review-Issue.
**Codex auf Windows:** lokale Codex.exe, reales 0.163+-Schema-Mapping,
Authentifizierung, Account-/Modellprüfung, ein harmloser Live-Turn,
lokale Receipt-/OS-Prüfung, anschließend evidenzbasierter
Multiworker-Versuch. Kein automatischer Token-Upload nach GitHub.

**Keine voreilige Aussage:** #69 kann offline grün sein,
während der echte lokale App Server weiterhin unbekannt ist.
