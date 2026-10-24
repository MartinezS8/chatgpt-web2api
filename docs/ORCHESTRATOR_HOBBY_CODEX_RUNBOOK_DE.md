# Lokaler Hobby-Orchestrator – Codex-Testanleitung (Windows 11)

**Stand:** 24. Oktober 2026, Erweiterung auf Basis von Draft PR #84.
Native Codex 0.164, MCP-/Apps-Fence und Account-/Modell-Discovery wurden lokal
geprüft. Ein echter Codex-Turn wurde weiterhin nicht ausgeführt. Siehe
[aktuelle Diagnose und Grenzen](ORCHESTRATOR_MCP_REFRESH_READINESS_REPORT.md).
Dieser Leitfaden dient zur
**bewussten manuellen Ausführung auf deinem PC**, nicht als Startfreigabe.

## Kurzüberblick

| Schritt | Befehl/Skript | Codex-/Account-Aktion |
| --- | --- | --- |
| 1 | `inspect_codex_app_server.py` | nur `--version` und Schema generieren |
| 2 | `audit_codex_schema_fixture.py` | rein offline; Schema und Fixture vergleichen |
| 3 | `orchestrator_pilot_doctor.py` | SHA/Version lokal, kein Accountzugriff |
| 4 | `codex login` / `codex login status` | Benutzer meldet sich selbst an |
| 5 | `orchestrator_pilot_doctor.py --allow-account-discovery --mcp-source-map ...` | App-Server, `account/read`, `model/list`; nur nach Prüfung aller MCP-Herkünfte |
| 6 | `pilot_one_codex_turn.py --allow-one-turn` | **ein echter** Thread/Turn (separat bewusst starten) |

Keine der ersten drei Prüfungen startet eine Inferenz. Die vierte ist ein
manueller offizieller Login. Die fünfte kann accountbezogene Daten lesen;
die sechste kann tatsächlich Modellnutzung verursachen.

## Einrichten und Offline-Checks

In PowerShell, im geprüften Entwicklungs-Worktree und mit einer externen
Python-3.12-Umgebung. `$Python` bezeichnet deren absoluten `python.exe`-Pfad.

```powershell
& $Python -m pip install -e '.[dev]'
# Expliziter Pfad zur vertrauenswürdigen NATIVEN Codex.exe, NICHT codex.cmd:
$CodexExe = 'C:\voller\pfad\zur\codex.exe'
$SchemaDir = Join-Path $env:LOCALAPPDATA 'w2a-schema-test-eindeutig'
$Scratch = Join-Path $env:TEMP 'w2a-leerer-testordner-eindeutig'

# SchemaDir darf NICHT existieren; Basis LOCALAPPDATA muss existieren.
py -3.12 scripts/inspect_codex_app_server.py --codex-exe "$CodexExe" --output-dir "$SchemaDir"
py -3.12 scripts/audit_codex_schema_fixture.py --schema-root "$SchemaDir" --list

# Explizit nur einen NEUEN, leeren Testordner anlegen:
New-Item -ItemType Directory -Path "$Scratch" -ErrorAction Stop
$McpMap = Join-Path $env:LOCALAPPDATA 'w2a-mcp-source-map-eindeutig.json'

# Nur SHA/Version/Schema prüfen, KEIN account/read:
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch"

# Nur Konfigurationsmetadaten inventarisieren; startet keinen MCP-Server.
& $Python scripts/prepare_codex_mcp_source_map.py --codex-exe "$CodexExe" --cwd "$Scratch" --output-map "$McpMap" --plugin-cache (Join-Path $env:USERPROFILE '.codex\plugins\cache') --bind-snapshot
```

Wenn die Inventarisierung mit Exitcode 2 endet oder `unknown`-Einträge
enthält, **hier stoppen**. Prüfe lokal die tatsächliche Quelle jedes Eintrags
(zum Beispiel Benutzer-/Projektkonfiguration, CLI-Override oder Plugin) und
ergänze nur belegte Zuordnungen; Plugin-Einträge benötigen die exakte
`plugin_id`. Keine unbekannte Quelle erraten. Die Karte enthält lokale
Servernamen und gehört weder in Git noch in einen Bericht.

Die optionale Plugin-Inventur akzeptiert nur eindeutige aktivierte Plugin-IDs,
passende Cache-Verzeichnisse und explizite Manifest-Verweise. Mehrdeutige
Versionen bleiben `unknown`; umgeleitete Kandidaten werden nicht als Beleg
verwendet. Der v2-Snapshot bindet Binary, Version, CWD, effektive
Inventarmetadaten und die gelesenen lokalen Quelldateien. Er ist keine
signierte Herkunftsbescheinigung und erfasst nicht jede Managed-/Remote-Schicht.

```powershell
# Kein Account, Thread oder Turn. Optional fester PowerShell-CWD-Test unter MXC.
& $Python scripts/probe_codex_start_matrix.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --case "$Scratch" "$McpMap" --probe-mxc-command
```

Für jeden weiteren CWD muss eine eigene v2-Karte erzeugt werden. Ein
App-Server-Handshake prüft keinen Sandbox-Kindprozess. Der MXC-Test verwendet
ein neues prozesslokales Read-only-Berechtigungsprofil mit ausgeschaltetem
Netzwerk; Legacy-Sandbox-Setup mit möglichen Windows-Kontoänderungen wird
nicht ausgeführt. Ein Exitcode 0 bei abweichendem CWD zählt als Fehler.

**Wichtig:** Der Schema-Fingerprint aus einer alten Codex-Version darf nicht
für eine neue Codex.exe wiederverwendet werden. Bei Änderungen Version und
Schema erneut generieren, nie still automatisch fallbacken. Der schon
beobachtete lokale Stand `0.163.0-alpha.11` ist nicht gleichbedeutend mit
einem erfolgreich getesteten App-Server-Adapter.

## Nach manuellem Login: Modelldiscovery

Melde dich auf deinem Laptop über den offiziellen Codex-CLI-/Browserdialog
selbst an. Niemals `auth.json`, Tokens, Gerätecodes oder Cookies in ChatGPT
oder GitHub teilen.

```powershell
codex login status
# Nach abgeschlossenem Herkunftsreview und bewusster Zustimmung zu account/read / model/list:
py -3.12 scripts/audit_codex_mcp_config.py --codex-exe "$CodexExe" --cwd "$Scratch" --mcp-source-map "$McpMap"
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --allow-account-discovery --mcp-source-map "$McpMap"
```

Aus dem Ergebnis den **exakten** Modell-Identifier und eine tatsächlich
unterstützte Reasoning-Stufe übernehmen. Danach erneut prüfen:

```powershell
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --allow-account-discovery --mcp-source-map "$McpMap" --model '<EXAKTE_MODEL_ID>' --effort '<EXAKTE_EFFORT>'
```

Mit `model_verified: true` ist **nur** die Auswahl bestätigt – keine
Provider-Inferenz, kein Schreibrecht, keine Prüfung der echten Isolation.

## Der erste echte Ein-Turn-Test – nicht automatisch

**Zuerst Codex auf dem Laptop prüfen lassen:** Stimmen
`thread/start`-/`turn/start`-Requests und Responses mit den lokal generierten
Schemas überein? Die ältere synthetische Version 0.157 hatte bereits bekannte
Unterschiede zur 0.163-Bundle (unter anderem `approvalsReviewer`,
`sandbox` und `thread.source`). Vor einem echten Turn eventuelle Fehler im
Adapter korrigieren und Tests wiederholen.

Nur falls bewusst ein echter einzelner Provider-Turn gewünscht ist, und
nach Prüfung des leeren Testverzeichnisses:

```powershell
$PromptFile = Join-Path $env:LOCALAPPDATA 'w2a-pilot-prompt-eindeutig.txt'
$ReceiptDir = Join-Path $env:LOCALAPPDATA 'w2a-pilot-receipt-eindeutig'
'Output exactly ORCH_TEST_OK. Do not use tools.' | Set-Content -Path "$PromptFile" -Encoding UTF8 -NoNewline

& $Python scripts/pilot_one_codex_turn.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --prompt-file "$PromptFile" --receipt-dir "$ReceiptDir" --model '<EXAKTE_MODEL_ID>' --effort '<EXAKTE_EFFORT>' --windows-sandbox mxc --mcp-source-map "$McpMap" --thread-params-schema v2/ThreadStartParams.json --thread-result-schema v2/ThreadStartResponse.json --turn-params-schema v2/TurnStartParams.json --turn-result-schema v2/TurnStartResponse.json --allow-readonly-builtin-tools --allow-one-turn
```

Die letzten beiden Flags benötigen eine konkrete Freigabe: ein einzelner
Turn sowie das verbleibende Risiko eingebauter Read-only-Werkzeuge. Derselbe
Windows-Benutzer und `readOnly` belegen keine Scratch-only-Leseisolation.
Der Pilot fordert MXC ausdrücklich an und schaltet den automatischen
Backend-Fallback aus. Der tatsächliche Sandbox-Backend-Prozess eines
Modell-Toolaufrufs ist damit noch nicht unabhängig bestätigt.

Das Skript erstellt `intent.json` **vor** dem Live-Send. Eine bestätigte
Transportbeendigung schreibt `result.json` mit Status
`transport_completed_unreviewed`; eine unsichere Zustellung hinterlässt
`quarantine.json`. Ein vorhandenes Receipt-Verzeichnis wird nicht
überschrieben. **Nicht erneut starten**, bevor die erste Zustellung manuell
untersucht wurde. Ein Terminal-Event bedeutet nicht automatisch, dass alle
Aufgabenergebnisse validiert sind.

## Konsequenzen für Hobbybetrieb

Es ist möglich, für einen reinen Hobbyversuch zunächst ohne Enterprise-VM
oder separaten Windows-Service zu arbeiten. Dann hat die lokale Codex.exe
aber grundsätzlich die Rechte ihrer Windows-Identität; eine deklarierte
`readOnly`-Sandbox ist keine umfassende Zugriffssperre auf andere Benutzerdateien.
Deshalb: keine privaten Dateien/Schlüssel im Testordner, keinerlei produktive
Zugangsdaten mitgeben und nur mit einem harmlosen Prompt beginnen.

**Nicht fertig:** echte fünf parallele Codex-Worker, globale Dispatch-
Quarantäne im Controller, unabhängige GitHub-Review-/Merge-Finalisierung,
ChatGPT-Web-UI-Pluginparität, und Windows-Release. PR #63 ist ein bewusst
separater Minimal-Pilot, nicht das abschließende Orchestrator-System.

## Was Codex im Abschlussbericht festhalten soll

- Exakter Branch/HEAD/Worktree-Status und CI-SHA; keine ungeprüften Merges
- Native Codex-Version und Schema-Fingerprint, Anzahl Schema-Dateien
- Negativer oder positiver Vergleich der eigenen `thread/start`-Fixtures
- Exakte verwendete Modellkennung/Reasoning-Stufe, ohne Accountdaten
- Beim ersten Live-Test: eine oder null `turn/start`-Requests, Ergebnisstatus,
  Thread-/Turn-Korrelation, `intent.json`, `result.json`/`quarantine.json`
- Beobachtete Probleme und folgende Implementierungsaufgaben für 2/5 Worker


## Ergänzung: PR #64 — Schema-Fence vor dem Live-Test

Der Pilot hat jetzt vier **Pflichtargumente** für exakt ausgewählte und zur
lokalen Codex-Version passende Schema-Dateien:

```powershell
--thread-params-schema "<THREAD_PARAMS_SCHEMA.json>" `
--thread-result-schema "<THREAD_RESULT_SCHEMA.json>" `
--turn-params-schema "<TURN_PARAMS_SCHEMA.json>" `
--turn-result-schema "<TURN_RESULT_SCHEMA.json>"
```

Codex muss diese vier relativen Dateinamen **aus dem realen Schema-Manifest**
ermitteln, die jeweils erwartete Struktur überprüfen und an den obigen
`pilot_one_codex_turn.py`-Aufruf anhängen. Test-Filenames sind NICHT die
wirklichen Pfade der installierten Codex-Version. Ungeprüfte oder fehlende
Pfade brechen vor dem Live-Send ab. Unpassende `thread/start`-Antworten
verhindern den anschließenden `turn/start`. Der Test bleibt ausdrücklich
ein einzelner bewusst gestarteter Hobby-Pilot.


## PR #66 — Diagnose klar zwischen vor und nach Turn-Send unterscheiden

Ein fehlgeschlagener lokaler Pilot schreibt weiterhin `quarantine.json`.
Neu ist `turn_start_may_have_been_sent`: Bei `false` wurde innerhalb
dieses Prozesses **kein** `turn/start`-Send versucht, bei `true` ist die
Zustellung unsicher und darf nicht ohne manuelle Untersuchung wiederholt
werden. In beiden Fällen bleibt `retry_permitted: false` und derselbe
Receipt-Pfad kann nicht erneut verwendet werden. Verfrühte
`turn/`-Benachrichtigungen sowie widersprüchliche verschachtelte
Turn-IDs werden jetzt vor einer falschen Terminalbewertung abgefangen.
