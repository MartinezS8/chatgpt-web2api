# Lokaler Hobby-Orchestrator – Codex-Testanleitung (Windows 11)

**Stand:** Draft PR #63 auf der gestapelten Linie #59 → #60 → #61 → #62 → #63.
Die Python-3.12-Skripte sind implementiert, aber kein echter Account- oder
Codex-Turn wurde von ChatGPT ausgeführt. Dieser Leitfaden dient zur
**bewussten manuellen Ausführung auf deinem PC**, nicht als Startfreigabe.

## Kurzüberblick

| Schritt | Befehl/Skript | Codex-/Account-Aktion |
| --- | --- | --- |
| 1 | `inspect_codex_app_server.py` | nur `--version` und Schema generieren |
| 2 | `audit_codex_schema_fixture.py` | rein offline; Schema und Fixture vergleichen |
| 3 | `orchestrator_pilot_doctor.py` | SHA/Version lokal, kein Accountzugriff |
| 4 | `codex login` / `codex login status` | Benutzer meldet sich selbst an |
| 5 | `orchestrator_pilot_doctor.py --allow-account-discovery` | App Server, `account/read`, `model/list` |
| 6 | `pilot_one_codex_turn.py --allow-one-turn` | **ein echter** Thread/Turn (separat bewusst starten) |

Keine der ersten drei Prüfungen startet eine Inferenz. Die vierte ist ein
manueller offizieller Login. Die fünfte kann accountbezogene Daten lesen;
die sechste kann tatsächlich Modellnutzung verursachen.

## Einrichten und Offline-Checks

In PowerShell, in einem separaten Git-Worktree **der Draft-PR #63**:

```powershell
py -3.12 -m pip install -e '.[dev]'
# Expliziter Pfad zur vertrauenswürdigen NATIVEN Codex.exe, NICHT codex.cmd:
$CodexExe = 'C:\voller\pfad\zur\codex.exe'
$SchemaDir = Join-Path $env:LOCALAPPDATA 'w2a-schema-test-eindeutig'
$Scratch = Join-Path $env:LOCALAPPDATA 'w2a-leerer-testordner-eindeutig'

# SchemaDir darf NICHT existieren; Basis LOCALAPPDATA muss existieren.
py -3.12 scripts/inspect_codex_app_server.py --codex-exe "$CodexExe" --output-dir "$SchemaDir"
py -3.12 scripts/audit_codex_schema_fixture.py --schema-root "$SchemaDir" --list

# Explizit nur einen NEUEN, leeren Testordner anlegen:
New-Item -ItemType Directory -Path "$Scratch" -ErrorAction Stop

# Nur SHA/Version/Schema prüfen, KEIN account/read:
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch"
```

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
# Nach bewusster Zustimmung zum lokalen account/read / model/list:
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --allow-account-discovery
```

Aus dem Ergebnis den **exakten** Modell-Identifier und eine tatsächlich
unterstützte Reasoning-Stufe übernehmen. Danach erneut prüfen:

```powershell
py -3.12 scripts/orchestrator_pilot_doctor.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --allow-account-discovery --model '<EXAKTE_MODEL_ID>' --effort '<EXAKTE_EFFORT>'
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

py -3.12 scripts/pilot_one_codex_turn.py --codex-exe "$CodexExe" --schema-root "$SchemaDir" --cwd "$Scratch" --prompt-file "$PromptFile" --receipt-dir "$ReceiptDir" --model '<EXAKTE_MODEL_ID>' --effort '<EXAKTE_EFFORT>' --allow-one-turn
```

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
