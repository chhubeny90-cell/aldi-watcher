# V5 — verifizierter Stand vom 08.10.2026

LITE ist implementiert, aber **NOT READY für Livebetrieb**. Es wurde keine
Nachbuchung ausgeführt oder als erfolgreich behauptet. Bestehende GitHub-
Zeitpläne bleiben aktiv; der neue Zweig verändert den laufenden Hauptzweig nicht.

## Tatsächlich geprüft

* Vollständige lokale Testsuite: **329 bestanden**. Darunter alle sieben
  geforderten LITE-Kernfälle, Prozess-/SQLite-Neustart, gleichzeitige Ereignisse,
  kostenpflichtige Angebote, Mailauthentifizierung und Cursor-Redelivery.
* Zwei originale ALDI-Mails: Klassifikation, reale Konfigurationsprüfung,
  persistierter Abschluss und Deduplizierung auch in einem neuen Prozess.
  Kein Provider-Stub, kein Browserstart, keine Buchungsreservierung.
* Docker-Image gebaut; echter Chromium-/Chromedriver-Start als Benutzer 10001,
  Shadow-DOM-Feld gefunden. SQLite-Ereignis nach Start eines zweiten Containers
  mit demselben Volume wiedererkannt. Keine ALDI-Anfrage in diesen Pakettests.
* Echter HTTP-Empfänger im Container: Healthcheck, Ablehnung unsignierter Push-
  Nachrichten und sauberer SIGTERM-Abschluss bestätigt. Synthetischer privater
  Testcursor, keine Gmail-API-Anfrage und kein produktiver Mailtrigger.
  WATCHDOG meldet die zwei real gespeicherten Konfigurationsfehler korrekt.
* Öffentlicher offizieller Login: Weiterleitung zum CIAM-Login und sichtbare
  Shadow-DOM-Eingabefelder auf dem lokalen Host bestätigt. Keine Anmeldung
  mit dem Benutzerkonto auf diesem Host, da Laufzeit-Zugangsdaten fehlen.
* [Read-only Accountprobe auf GitHub](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/37753926870):
  `login_not_confirmed`, Phase `username_field`. Abbruch vor Eingabe der
  Zugangsdaten; damit sind weder Passwortfehler noch MFA nachgewiesen.

## Komponenten

| Komponente | Stand | Grenze des Nachweises |
| --- | --- | --- |
| LITE | NOT READY live | Gmail-Transport und Transaktionen getestet; Accountlogin, aktuelles 0-€-1-GB-Angebot und echte Erfolgsbestätigung fehlen. |
| WATCHDOG | NOT READY live | Crash-/Lock-/Doppelbuchungsschutz sowie einmalige Restart-Anforderung getestet; kein dauerhafter Supervisor deployed. Provider-Reconciliation noch nicht verifiziert. |
| PRO | READY als lokales Analysewerkzeug | Zwei echte abgeschlossene Ereignisse ausgewertet; 39 Sekunden Mailabstand und zwei Konfigurationsfehler. Kein produktiver Analysejob deployed. |

Die 39 Sekunden sind ein Mailabstand, keine Nachbuchungsdauer. PRO liest
ausschließlich; Verbesserungen werden auf einem separaten Zweig getestet.
Im getesteten LITE wurden ein pauschaler 30-Minuten-Buchungsschutz und ein
pauschaler Ein-Stunden-Mailverfall entfernt: Beide könnten einen berechtigten
neuen Verbrauchstrigger verlieren. Stattdessen entscheidet immer der frisch
verifizierte Providerzustand; offene PENDING/UNKNOWN bleiben gesperrt.

## Tatsächlich verbleibende Blocker

1. Regulärer erfolgreicher ALDI-Accountlogin und beobachtete Account-, Tarif-,
   Preis-, Angebots- und Erfolgsmerkmale. Der rekonstruierende Abgleich benötigt
   außerdem echte Provider-Historie oder eine eindeutige Buchungs-ID;
   `reconcile()` lässt unbekannte Ergebnisse derzeit bewusst UNKNOWN.
2. Sicher bereitgestellte Laufzeit-Zugänge: ALDI und Gmail OAuth. Der lesbare
   ChatGPT-Gmail-Connector stellt keinen OAuth-Refresh-Token für den Bot bereit.
   Das verwendete Postfach muss dem tatsächlich angemeldeten Account eindeutig
   zugeordnet werden.
3. Dauerhafter autorisierter Host mit persistentem DB-Volume; für Gmail Push
   zusätzlich ein autorisiertes Google-Cloud-Projekt und HTTPS-Endpunkt.
   Hier sind weder Cloud-Zugangsdaten noch ein dauerhafter Zielhost konfiguriert.

Es gibt kein als funktionsfähig markiertes Release, solange die echte Kette
Mail → Login → kostenloses Angebot → Buchung → Erfolgsbestätigung nicht läuft.
Der Branch und seine Commits sichern den überprüfbaren Entwicklungsstand.

## Weiterarbeit am 08.10.2026: überwachte Mail-Laufzeit

Der bestehende Stand wurde erneut mit 329 erfolgreichen lokalen Tests geprüft.
Die Ergänzung bringt 14 weitere Tests einschließlich eines echten lokalen
HTTP-Servers mit: `/health` zeigt nur Erreichbarkeit, `/ready` prüft den
Mailtransport. Vor dem ersten erfolgreichen Abgleich, bei Fehlern und bei
überfälligem Abgleich wird keine Bereitschaft behauptet. Die Prüfung sagt
ausdrücklich nichts über Live-Buchungsbereitschaft aus.

`serve` erneuert den Gmail-Watch täglich und gleicht Gmail History alle fünf
Minuten ab. Dadurch werden verlorene Push-Benachrichtigungen nachgeholt. Cursor,
Account-Sperren und Ereignisdeduplizierung gelten auch für diesen Weg. Fehler
werden frühestens nach 60 Sekunden erneut versucht. Im mailfreien Leerlauf
gibt es weiterhin keinen Portalzugriff. Die Docker-Bereitschaftsprüfung nutzt
`/ready`; ein unabhängiger Alarmempfänger ist weiterhin nicht eingerichtet.

Aktuelle Warn- und Verbrauchsmails wurden erneut in zwei verbundenen Postfächern
gefunden. Die SIM-Zuordnung und zuverlässige Zustellung nach jedem Zusatzpaket
sind dadurch weiterhin nicht bewiesen. Ein fehlendes ALDI-Mailereignis wird durch
den Gmail-Abgleich nicht ersetzt. Eine unabhängige Portal-Kontrolle ist offen.

In der aktuellen Entwicklungsruntime sind weder ALDI-Zugangsdaten noch Gmail-
OAuth-Laufzeitzugänge oder Docker vorhanden. Es wurde kein Dienst deployed,
kein vollständiger Liveflow getestet und keine Buchung ausgeführt. Der lokale
HTTP-Test ist kein externer Verfügbarkeits- oder Benachrichtigungsnachweis.

Startbefehle und sichere Konfiguration: [Runbook](v5-runbook.md).
Mailnachweis: [Echte Validierung](v5-real-validation.md).
Referenzen und verworfene Ansätze: [GitHub-Recherche](v5-reference-research.md).
