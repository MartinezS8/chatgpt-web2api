# Lokaler Hobby-Orchestrator – Codex-Testanleitung (Windows 11)

**Stand der Dokumentation:** 27. Oktober 2026, Review auf Basis des
gestapelten Draft-HEAD von PR #87 (einschließlich #84).
Der vorhandene lokale Bericht dokumentiert Codex 0.164,
MCP-/Apps-Fence und Account-/Modell-Discovery; diese Nachweise stammen
aus dem lokalen Diagnoselauf, **nicht** von diesem GitHub-Review.
Ein echter Codex-Turn ist weiterhin nicht nachgewiesen. Siehe
[aktuelle Diagnose und Grenzen](ORCHESTRATOR_MCP_REFRESH_READINESS_REPORT.md).
Dieser Leitfaden dient zur
**bewussten manuellen Ausführung auf deinem PC**, nicht als Startfreigabe.
**Pflichtstopp vor dem ersten echten Turn (Befund vom 27.10.2026):**
Der lokale MCP-Refresh-Bericht hält fest, dass die jetzt sichtbare
`codex.exe` weiterhin Version 0.164 meldet, aber einen **anderen
SHA-256-Fingerprint** hat als die frühere Schema-Erfassung
(`1103e9e0…` statt `c6144bc1…`). Die bisherige alte
`offline-readiness.json` darf somit NICHT verwendet werden.
Zuerst aktuelle EXE und **frisches Schema-Bundle** neu erfassen und
die Bindung verifizieren. Danach MCP-v2-Quelle, CWD- und MXC-Probe
erneut prüfen. Der vorherige MXC-Test mit AppData-CWD schlug wegen
falschem effektivem CWD fehl, während der Temp-CWD-Test damals PASS
war. Auch der frühere Temp-PASS überträgt sich nicht automatisch
auf das neue Binary. Siehe
[lokaler Befund](ORCHESTRATOR_MCP_REFRESH_READINESS_REPORT.md).


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

Unbedingt den **aktuellen PR-HEAD** aus GitHub prüfen und nicht versehentlich
eine ältere Draft-Stufe (#63, #68) oder ungemergtes `master` verwenden.
Die Checkliste für den gesamten Review steht in
[Review- und Codex-Abnahmeplan](ORCHESTRATOR_REVIEW_GATES_AND_CODEX_HANDOFF.md).

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
# BOM-freies UTF-8, auch in Windows PowerShell 5.1
[System.IO.File]::WriteAllText($PromptFile,
    'Output exactly ORCH_TEST_OK. Do not use tools.',
    (New-Object System.Text.UTF8Encoding($false)))

# Rein offline: dieselben aus dem lokalen v2-Manifest überprüften
# Request-Shapes wie beim Live-Pilot, kein Login und kein Provider-Turn.
& $Python scripts/preflight_codex_wire.py --schema-root "$SchemaDir" --cwd "$Scratch" --prompt-file "$PromptFile" --model '<EXAKTE_MODEL_ID>' --effort '<EXAKTE_EFFORT>' --thread-params-schema v2/ThreadStartParams.json --thread-result-schema v2/ThreadStartResponse.json --turn-params-schema v2/TurnStartParams.json --turn-result-schema v2/TurnStartResponse.json
# Falls dieser Preflight nicht PASS ist: hier abbrechen und lokal prüfen.
# Auch PASS beweist noch keine echten Server-Responses oder MCP-Isolation.

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

Das Tool-Ereignis-Audit v1 zählt ausschließlich feste Typnamen; unbekannte
Typen erscheinen als `unknown`. Tool- oder Approval-Ereignisse, unbekannte
Ereignisse und widersprüchliche Statuswerte verhindern einen sauberen
Pilotstatus. Der Pilot liefert Exitcode 0 nur bei korrekter Antwort und
`clean_tool_free_pilot=true`. Der Receipt-Inspector verlangt zusätzlich eine
konsistente, vollständige Audit-Aufzeichnung und die Bindung an `intent.json`;
ältere Receipts ohne Audit gelten dafür als ungeprüft.

```powershell
& $Python scripts/inspect_pilot_receipt.py --receipt-dir "$ReceiptDir"
```

Das Audit wertet beobachtete App-Server-Ereignisse aus und kann bereits
erfolgte Aktionen erst nachträglich erkennen. Es verhindert keine Tool-Aktion
und beweist weder vollständige Ereignismeldung noch wirksame Windows-Isolation.
Tool-Payloads und unerwartete Modellantworten werden nicht ins Receipt kopiert.

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


### PR #87 – Audit v2

Der Offline-Audit verlangt künftig zusammenpassende Item-Start-/Abschlussereignisse
und einen konsistenten Terminal-Snapshot. Auch verspätete Safe-Notifications
markieren den Pilot als nicht sauber. Die Redaktionsregeln bleiben erhalten.
Ein grüner Fake-Test belegt **keine** echte Codex-0.164-Transportkompatibilität
oder vollständige OS-Isolation. Version-1-Receipts sind kein Audit-v2-PASS.


## Ergänzung Review — Status und Abnahme

Die komplette PR-Linie reicht inzwischen mindestens bis #87 und enthält
mehrere neuere MCP-, Ausgabe- und Sandbox-Prüfungen. Beim lokalen Pilot
den HEAD des **neuesten geplanten Integrations-PRs** prüfen und ein früheres
Snippet niemals blind auf einen anderen Codex-Versionsstand übertragen.
Der Offline-Preflight überprüft Request-Payloads, nicht die reale Antwort
des Servers. Eine erfolgreiche lokale `result.json` ist kein
unabhängiger Modell-/Datei-Review und keine Freigabe für automatische
fünf echte Worker. Vor dem Merge Gate 1–5 aus der obigen Review-Datei
abarbeiten.
