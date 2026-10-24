# Projektübersicht und GitHub-Triage (21.10.2026)

> Dokumentation und Arbeitsorganisation; **kein** Nachweis für produktiven ALDI-Betrieb. Stand der verlinkten Diskussionen separat nachprüfen.

## Projekte klar trennen

- **ALDI-Watcher**: E-Mail-Sensor, sichere SIM-/Tarifzuordnung, Gratis-1-GB-Erkennung, Journal/Recovery, geschützter privater Runner. Einstieg: [Issue #125](../issues/125) und [Issue #116](../issues/116).
- **KI-Auftragsbox**: GitHub-basierte Aufgaben, Nachweise, Empfangsbestätigung und externe Integrationen. Einstieg: [Issue #126](../issues/126). Eine dokumentierte Anfrage ist **keine** bestätigte Zustellung an ein Fremdmodell.
- **Sicherheit/PRs**: Jeder Branch und Pull Request hat einen eigenen Scope und Commit. Keine stillen Merges, keine Übernahme historischer Testergebnisse auf neue SHAs.

## Aktive Arbeitsstränge (Stichprobe der GitHub-Suche vom 21.10.2026)

| Thema | Einstieg | Bedeutung |
| --- | --- | --- |
| Sichere ALDI-Betriebsbereitschaft | [#125](https://github.com/chhubeny90-cell/aldi-watcher/issues/125) | Vier P0-Pakete; noch kein authentifizierter End-to-End-Nachweis |
| Portal/Runner-Nachweis | [#116](https://github.com/chhubeny90-cell/aldi-watcher/issues/116) | Live-Gates und notwendige Betreiberschritte |
| KI-Übergaben | [#126](https://github.com/chhubeny90-cell/aldi-watcher/issues/126) | Tatsächliche Zustellung separat belegen |
| Vierfach-Simulation | [PR #130](https://github.com/chhubeny90-cell/aldi-watcher/pull/130) | Nur Offline-Regression, **keine vier Buchungen** |
| Gemini-Smoke-Test | [PR #129](https://github.com/chhubeny90-cell/aldi-watcher/pull/129) | Manuell, geschützt, noch kein echter Empfangsnachweis |
| KI-Security-Follow-up | [PR #128](https://github.com/chhubeny90-cell/aldi-watcher/pull/128) | Sicherheitsfixes gesondert abnehmen |

## Kommentarrichtlinie

1. Kommentare einzeln auf offenen, relevanten Diskussionsstand prüfen; Autor, Datum, Kontext, Commit und Belege festhalten.
2. **Aktionsfähig**: konkrete Rückfrage oder Finding mit technischer Antwort / Issue-Link / offenem nächsten Schritt beantworten.
3. **Bereits beantwortet**: nicht nochmals kommentieren. Bot-Statusmeldungen und Duplikate nicht künstlich mit Antworten überfluten.
4. Keine Reviews als erledigt markieren, bis sie auf dem exakten Commit nachweislich geprüft wurden.
5. Keine Zugangsdaten, Rufnummern, Cookies, Token, Recovery-Key oder personenbezogenen E-Mail-Inhalte veröffentlichen.

## Statusbegriffe

- **BLOCKED**: kritische Live-Bedingungen fehlen.
- **DRY_RUN_READY**: Simulation/Offline-Prüfung für konkreten Commit belegt; kein Providerbeleg.
- **LIVE_READY**: alle Freigabegates nachweislich erfüllt; heißt nicht gebucht.
- **LIVE_VERIFIED**: konkrete Anbieteraktion plus offizieller vorgangsbezogener Beleg vorhanden.

**Derzeitige verbindliche Auslegung: ALDI-Livebetrieb BLOCKED.** Weder erfolgreiche CI noch eine öffentliche Login-Seite oder ein KI-Kommentar lösen diese Sperre auf. Keine kostenpflichtige Option, keine absichtliche Doppelbuchung.

## Empfohlener Dokumentationsaufbau

- `README.md`: knappe Zielsetzung, echte Sicherheits-/Betriebsgrenzen, Einstieg in detaillierte Runbooks.
- `docs/`: Prüfberichte und Runbooks nach Datum; historische Berichte ausdrücklich als historisch kennzeichnen.
- `docs/project-triage-2026-10-21.md`: dieses Arbeitsregister.
- `tests/`: Simulation und Regression, strikt getrennt von Live-Aktionen.
- `.github/workflows/`: klar unterscheiden zwischen CI, read-only Monitoring, manuellen Integrations-Smoke-Tests und gesperrter Live-Nachbuchung.

## Nächste überprüfbare Schritte

- Kommentare und Review-Threads aller PRs separat einsammeln; Antwort nur auf tatsächlich offene fachliche Punkte.
- P0-Betriebsblocker am aktuellen Main erneut messen (insbesondere ursprünglicher Recovery-Key und privates persistentes Journal).
- README auf aktuelle belegte Statusinformationen kürzen, historische Betriebsaussagen in `docs/` belassen.
- Dokumentationsänderungen per PR abnehmen; keine Änderung am Produktivcode durch die Triage.
