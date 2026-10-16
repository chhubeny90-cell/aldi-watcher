# Betriebsprüfung 17.10.2026 (Europe/Berlin)

Geprüfter main-Commit: `481b0a91f705de0915866d1a130df3a403c8c63d`.
Diese Prüfung ersetzt ältere Betriebsannahmen, belegt aber keinen neuen Login
und keine echte Buchung. Der öffentliche Portaltest ist kein Kontotest.

## Sechs Prüfschritte

| Schritt | Tatsächlicher Nachweis | Ergebnis / notwendiger nächster Schritt |
| --- | --- | --- |
| 1. Verbrauchsmail | Lauf `38966370793`, 16.10.2026 23:01 Uhr: `configured_mailboxes=0`, `dedup_key_configured=false`, `no_mailboxes_configured`. | Blockiert. Mindestens ein IMAP-Postfach und `ALDI_RECOVERY_KEY` sicher konfigurieren und den Monitor erneut prüfen. |
| 2. Login / Kontodaten | Passwort-Diagnose `38946795242`, 16.10.2026 20:22 Uhr: `frontend_credentials_submitted_no_token`. Älterer HTTP-Lauf `38583852700`, 14.10.2026: `account_locked`. | Kein erfolgreicher Login belegt. Die alte Sperrmeldung ist kein Nachweis einer aktuellen Sperre. Eine neue, erfolgreiche Sitzung und geladene Kontodaten fehlen. |
| 3. Anschlusszuordnung | Prüfcode für Rufnummer und Tarif vorhanden; kein neuer authentifizierter Kontodatensatz in dieser Prüfung verfügbar. | Offen. Zielrufnummer und aktiven Unlimited-Tarif im angemeldeten Konto prüfen; Postfachindex reicht nicht. |
| 4. Gratisoption | Preis-/Tarifprüfungen und Tests vorhanden. Kein aktuelles Angebot aus einem erfolgreich geladenen Kundenkonto verfügbar. | Offen. Genau eine berechtigte kostenlose 1-GB-Option am zugeordneten Anschluss nachweisen. |
| 5. Bestellung | `run.yml` setzt `AUTO_BOOK_ENABLED=false`; `mail-trigger.yml` führt nur `usage_mail_notify.py` aus. Der Mail-Monitor startet keine Buchung. | Kein aktiver vollständiger Mail-zu-Buchung-Ablauf. Vor einer Aktivierung Konto, Angebot, dauerhaften Buchungszustand und Abschlussdetektor prüfen. |
| 6. Abschluss | `aldi_live_refill.py` setzt neue Buchungen nach dem Klick ausdrücklich auf `UNKNOWN`; `check_recharge_status` gibt immer `UNKNOWN` zurück. | Abschlussdetektor fehlt. Offizielle, der konkreten Bestellung zugeordnete Abschlussantwort beobachten und deren Prüfung implementieren. Volumenzuwachs oder „Bestellung erhalten“ reichen nicht. |

## Verfügbare Zugänge und Ausführungsgrenzen

- GitHub-Repository, Workflow-Metadaten und Job-Logs waren lesbar.
- Im Ausführungsprozess waren weder ALDI-Zugangsdaten noch IMAP-Zugangsdaten,
  Account-Konfiguration oder Recovery-Key als Umgebungsvariablen verfügbar.
  Daraus folgt keine Aussage über alle im GitHub-Secret-Store gespeicherten Werte.
- Die verbundenen GitHub-Werkzeuge bieten hier keinen Secret-Schreibzugriff und
  keinen Start eines neuen Workflows mit frei wählbaren Eingaben an.
- Der neueste öffentliche Watcher-Lauf `38965992508` führte nur `public_probe`
  aus; der Test-Job wurde in diesem geplanten Lauf übersprungen.
- Der SMS-Diagnosejob von 16.10. protokollierte einen Klick zur Code-Anforderung,
  aber weder Code-Eingabe noch bestätigte Code-Zustellung oder abgeschlossenen
  Login. Daraus darf keine funktionierende SMS-Anmeldung abgeleitet werden.

## Unabhängig behobener Fehler

`usage_mail_notify.py` ließ bei unvollständiger Postfachkonfiguration oder einem
nicht numerischen Port eine Exception durchlaufen, während der Bericht keine
`configuration_error` enthielt. Der Monitor schreibt jetzt einen eindeutigen,
bereinigten Konfigurationsfehler und beendet sich vor jedem Postfachzugriff mit
Exit 2. Beliebiger Exception-Text wird nicht in den Bericht übernommen.

## Sichere Konfiguration

Unter Repository → Settings → Secrets and variables → Actions für ein Postfach:

- `MAILBOX_1_USER`: vollständige zugehörige Mailadresse.
- `MAILBOX_1_PASS`: IMAP-Zugang, bei Gmail ein dafür erstelltes App-Passwort.
- `MAILBOX_1_HOST`: bei Gmail optional; Workflow verwendet bei gesetztem User
  `imap.gmail.com`. Für andere Anbieter explizit setzen.
- `MAILBOX_1_PORT`: optional, Standard 993.
- `ALDI_RECOVERY_KEY`: stabiler zufälliger Schlüssel für die HMAC-Deduplizierung;
  einen bereits produktiv verwendeten Schlüssel nicht ungeprüft ersetzen.

Diese Werte gehören nicht in Chat, Quellcode oder öffentliche Workflow-Logs.
Eine ChatGPT-Gmail-Verbindung überträgt sie nicht in GitHub Actions.
Die vollständige Mailkonfiguration allein behebt Schritte 2 bis 6 nicht.

## Quellen

- Mail: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38966370793
- Öffentliche Probe: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38965992508
- Letzte manuelle Diagnose: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38946795242
- Älterer HTTP-Login: https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38583852700

Keine Zugangsdaten geändert, kein neuer ALDI-Login ausgelöst, keine Bestellung
abgesendet und kein wiederkehrender Buchungsbetrieb aktiviert.
