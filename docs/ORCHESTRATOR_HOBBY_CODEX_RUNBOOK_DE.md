# Lokaler Codex-Orchestrator – aktueller Review- und Testleitfaden (Windows 11)

**Anwendungsfall:** privates Hobbyprojekt mit lokalen Codex-Workern. Dies ist
kein freigegebenes Produktivsystem. Die Änderungen sind **gestapelte
Draft-PRs**; die Basiskette ab #49 und die Pilot-PRs #59–#69 sind nicht
automatisch in `master` integriert.

**Geprüft über GitHub Actions:** #63–#68 mit Windows/Python 3.12,
Offline-Tests, Secret-Scan und installierten Paket-Smokes (Stand bei
Erstellung dieser Anleitung). **Nicht geprüft:** native Codex-Authentifizierung,
echte JSON-RPC-Kompatibilität von Codex 0.163+, Provider-Turn,
Betrieb mehrerer echter Worker.

## Grundregel

Codex lokal **auf dem neuesten vereinbarten PR-HEAD** starten, nicht auf
`master` oder dem historischen #63-Stand. Vor Ausführung den SHA
mit dem aktuellen PR in GitHub abgleichen. Keine Secrets, Tokens,
`auth.json`, Cookies oder Browser-Profile hochladen. Ein Scratch-Ordner
ohne private Daten genügt für den ersten Hobby-Pilot.

## A. Offline-Vorbereitung (kein Login, keine Provider-Inferenz)

Ein neues Git-Worktree für die aktuellste Draft-PR (hier #69) verwenden:

```powershell
git fetch origin
git worktree add ..\w2a-local-pilot origin/codex/orchestrator-v66-review-gates-and-wire-receipt-fixes
Set-Location ..\w2a-local-pilot
git rev-parse HEAD
git status --short
py -3.12 -m pip install -e '.[dev]'

$CodexExe = 'C:\voller\pfad\zur\nativen\codex.exe'
$SchemaDir = Join-Path $env:LOCALAPPDATA 'w2a-schema-neu-eindeutig'
$Scratch   = Join-Path $env:LOCALAPPDATA 'w2a-scratch-neu-eindeutig'
$PromptFile = Join-Path $env:LOCALAPPDATA 'w2a-prompt-neu-eindeutig.txt'
$ReceiptDir = Join-Path $env:LOCALAPPDATA 'w2a-receipt-neu-eindeutig'

New-Item -ItemType Directory -Path "$Scratch" -ErrorAction Stop
[System.IO.File]::WriteAllText(
    $PromptFile,
    'Output exactly ORCH_TEST_OK. Do not use tools.',
    (New-Object System.Text.UTF8Encoding($false))
)

py -3.12 scripts/inspect_codex_app_server.py --codex-exe "$CodexExe" --output-dir "$SchemaDir"
py -3.12 scripts/audit_codex_schema_fixture.py --schema-root "$SchemaDir" --list
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch"
```

`$SchemaDir` muss neu sein, `$Scratch` muss leer sein; Codex.exe ist
ein **expliziter nativer EXE-Pfad**, nicht `codex.cmd`. Der Python-Doctor
prüft Binary-SHA/Version und Schema-Manifest, startet für diesen Aufruf
**keinen** Turn. Nach einem Versionswechsel Schema-Erfassung
in einem anderen neuen Ordner wiederholen.

## B. Vier echte Schema-Dateien auswählen und offline prüfen

Aus `--list` die **exakten relativen JSON-Dateipfade** zu
`thread/start` Params/Result und `turn/start` Params/Result anhand
ihrer **tatsächlichen Definitionen** ermitteln. Nicht blind die alten
synthetischen 0.157-Beispielnamen übernehmen.

```powershell
$ThreadParams = '<ECHTER_RELATIVER_SCHEMA_PFAD>'
$ThreadResult = '<ECHTER_RELATIVER_SCHEMA_PFAD>'
$TurnParams   = '<ECHTER_RELATIVER_SCHEMA_PFAD>'
$TurnResult   = '<ECHTER_RELATIVER_SCHEMA_PFAD>'
$ModelId      = '<SPÄTER_EXAKT_ENTDECKTE_MODELLKENNUNG>'
$Effort       = '<EXAKT_UNTERSTÜTZTE_REASONING_STUFE>'
```

Die Auswahl ist ein menschlicher Review-Schritt: SHA-Fingerprints und
negative Schema-Proben verhindern manche falsch positiven PASS-Ergebnisse,
beweisen aber **nicht** von selbst das richtige Mapping. Nach Auswahl
und mit einer expliziten Modellkennung:

```powershell
py -3.12 scripts/preflight_codex_wire.py --schema-root "$SchemaDir" --cwd "$Scratch" --prompt-file "$PromptFile" --model "$ModelId" --effort "$Effort" --thread-params-schema "$ThreadParams" --thread-result-schema "$ThreadResult" --turn-params-schema "$TurnParams" --turn-result-schema "$TurnResult"
```

Erwartete Flags: `thread_params_schema_pass: true`,
`turn_params_schema_pass: true`; die Result-Schemas sind nur geladen,
**keine echten Antworten geprüft**. `app_server_process_started: false`,
`account_read_performed: false`, `real_turn_started: false`.

## C. Optionaler Account-Check und EIN bewusst ausgelöster Turn

**Erst jetzt**, bei eigener Zustimmung lokal über `codex login`
anmelden (keine Geheimnisse weitergeben). Die Account-Prüfung ist
separat vom Live-Turn:

```powershell
codex login status
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --allow-account-discovery
```

`$ModelId` und `$Effort` aus dem tatsächlich angebotenen Katalog
auswählen, danach den **Offline-Preflight aus B erneut** ausführen
und die Katalogauswahl ebenfalls prüfen:

```powershell
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --allow-account-discovery --model "$ModelId" --effort "$Effort"
```

**Nur wenn** diese lokalen Schritte passen und ein einziger harmloser
Provider-Aufruf ausdrücklich gewünscht ist:

```powershell
py -3.12 scripts/pilot_one_codex_turn.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --prompt-file "$PromptFile" --receipt-dir "$ReceiptDir" --model "$ModelId" --effort "$Effort" --thread-params-schema "$ThreadParams" --thread-result-schema "$ThreadResult" --turn-params-schema "$TurnParams" --turn-result-schema "$TurnResult" --allow-one-turn
```

Dies ist **nur ein** `thread/start` + **höchstens ein**
`turn/start` pro Versuch. Das Programm schreibt `intent.json`
vor dem Sendversuch und entweder `result.json` oder
`quarantine.json` (bei abruptem Abbruch ggf. gar keines davon).

**Nicht automatisch wiederholen, nicht denselben Receipt-Pfad erneut
verwenden**. Nach dem Aufruf kann ohne weitere Provider-Kommunikation
geprüft werden:

```powershell
py -3.12 scripts/inspect_pilot_receipt.py --receipt-dir "$ReceiptDir"
```

`TERMINAL_UNREVIEWED` bedeutet nur Transport abgeschlossen;
`UNKNOWN_DELIVERY` ist **keine** Erlaubnis zum Retry;
`PRE_TURN_FAILURE` bedeutet in diesem Pilot-Code keinen
versuchten `turn/start`-Send; `INCOMPLETE_OR_INTERRUPTED`
bedeutet unklare Unterbrechung. Ohne Sichtprüfung der Antwort
keine unabhängige Modell-/Fachabnahme.

## D. Was Codex im lokalen Ergebnisbericht nachweisen muss

- Worktree-Branch, exakter HEAD-SHA und aktueller CI-Status
- Codex-Version, Binary-Hash, 4 reale Schemapfade, Manifest/Hashes
- Offline-Wire-Preflight mit allen Ergebnisflags
- Katalog-/Account-Status **ohne** persönliche Accountdaten
- Beim ausdrücklich erlaubten Test: Anzahl Sendversuche,
  Response-/Notification-Korrelation, Receipt-Klassifikation,
  eventuelle Fehler ohne Prompt-/Token-Leaks
- Abweichungen von realen Schemas und **nur dann** notwendige
  kleine Adapterfixes samt Regressionstests; danach CI erneut
- Freigabeempfehlung für **2 echte Worker** erst nach nachgewiesenem
  Einzelturn und Outbox-/Recovery-Test; 5 Worker anschließend

Die gesamthafte Review-Abfolge und Merge-Voraussetzungen stehen in
`docs/ORCHESTRATOR_REVIEW_GATES_AND_CODEX_HANDOFF.md`.
