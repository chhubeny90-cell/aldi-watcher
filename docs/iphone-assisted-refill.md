# iPhone-Assisted Refill: providerfreier Benachrichtigungsweg

## Was dieser Branch nach der Übernahme kann

1. Der stündliche Mailmonitor liest neue ALDI-TALK-Verbrauchsmails über IMAP.
2. Nur eine **neue, bereits klassifizierte Verbrauchsmail** erzeugt einen
   HMAC-geschützten Outbox-Eintrag auf dem vorhandenen GitHub-State-Branch.
   80-%-Warnungen erzeugen **keine** Refill-Benachrichtigung.
3. Der separate SMTP-Schritt versucht bis zu fünf offene Erinnerungen je Lauf.
4. Mit der Mail auf dem iPhone öffnet der Nutzer per Home-Screen-Kurzbefehl die
   offizielle ALDI-TALK-App, prüft Konto, Tarif, genau 1 GB und 0,00 €, und
   drückt **selbst** bei eindeutiger Berechtigung einmal den Refill-Button.

**Kein** Browser-Bot, SMS-Versand, API-Nachbuchung, automatischer Refill,
Portal-Zugang, ALDI-Login oder Anbieterbeleg ist Teil dieses Wegs.
SMTP_ACCEPTED bedeutet Annahme durch den Mailserver, nicht Empfang auf
dem iPhone oder erfolgte Nachbuchung.

## Administrator-Konfiguration (auf main nach geprüfter Übernahme)

In GitHub > Settings > Secrets and variables > Actions:

- Repository variable **`ALDI_IPHONE_NOTIFY_ENABLED=true`** erst setzen, nachdem
  Mailmonitor und SMTP-Konfiguration nachgewiesen sind. Ohne diese Variable
  bleibt der Sender deaktiviert und der bestehende Mailmonitor unverändert.
- IMAP: `MAILBOX_1_USER`, `MAILBOX_1_PASS` und bei Bedarf `MAILBOX_1_HOST`
  (analog `MAILBOX_2_*`), sowie unveränderter `ALDI_RECOVERY_KEY` oder
  korrekt konfigurierter `ALDI_STATE_ENCRYPTION_KEY` für die Erkennung.
- SMTP: `ALDI_NOTIFY_SMTP_HOST`, `ALDI_NOTIFY_SMTP_USER`,
  `ALDI_NOTIFY_SMTP_PASS`, `ALDI_NOTIFY_FROM`,
  `ALDI_REFILL_RECIPIENTS` als GitHub Actions Secrets; optional
  `ALDI_NOTIFY_SMTP_PORT` (Standard 465, SSL).
- Das standardmäßig genutzte `GITHUB_TOKEN` benötigt die bereits vorhandene
  `contents: write`-Berechtigung zur atomaren Outbox-Speicherung.

Die Zugangsdaten müssen nicht in Chat, Issue oder Logs kopiert werden.
Ein grüner CI-Lauf beweist **keine** erfolgreiche Mailzustellung.

**Vor dem Einschalten:** Prüfen, ob alte Verbrauchsmails bereits über den
Legacy-Trigger oder die Mail-Handoff-Queue historisiert wurden. Der neue
Notifier respektiert diese Historie. Eine Mail wird niemals allein anhand
eines Postfachindex einer SIM zugeordnet.

## iPhone einrichten

1. App **Kurzbefehle** öffnen, neuen Kurzbefehl `ALDI 1 GB` erstellen.
2. Aktion **App öffnen** hinzufügen, als App ALDI TALK wählen.
3. Kurzbefehl zum Home-Bildschirm hinzufügen.
4. Mail-Benachrichtigungen für den vorgesehenen Empfänger aktivieren.
5. Bei einer Verbrauchsmeldung den Kurzbefehl öffnen. Im **offiziellen**
   Konto SIM, Tarif und eindeutig kostenlosen 1-GB-Refill prüfen; nur
   anschließend **selbst einmal** auslösen.

Kein koordinatenbasierter Autoklick und kein unbekannter URL-Scheme-Deep-Link.

## Zustandsmodell und Fehler

Die Datei `<ALDI_STATE_PATH>.iphone-notifications.json` auf dem
State-Branch enthält ausschließlich HMAC-Fingerprints und
`READY → SENDING → SMTP_ACCEPTED` beziehungsweise `UNKNOWN`.

- Doppelte Mailidentitäten erzeugen nicht erneut einen Eintrag.
- Ein Fehler vor SMTP-Versandkonfiguration lässt `READY` unangetastet.
- SMTP-Fehler nach Beginn von `SENDING` führen zu `UNKNOWN` statt zu
  einem automatischen zweiten Versuch.
- Ein Runner-Absturz während `SENDING` bleibt ebenfalls blockiert;
  erfordert manuelle Prüfung der Mailzustellung.
- Ist die Queue mit 512 Einträgen voll oder der State-Branch nicht
  beschreibbar, wird der Monitorfehler sichtbar; es wird nichts gebucht.
- Keine vollständigen Telefonnummern, E-Mail-Adressen, Mailtexte,
  Login-Daten oder Session-Token werden auf dem State-Branch gespeichert.

## Offline-Test

```sh
python -m pytest -q tests/test_iphone_notification_outbox.py tests/test_iphone_refill_reminder.py tests/test_mail_monitor_queue_integration.py tests/test_mail_notification_templates.py
```

Die alte `scripts/iphone_refill_reminder.py` bleibt nur als
**nicht angeschlossener** privater SQLite-Sender erhalten. Der produktive
GitHub-Workflow verwendet ausschließlich die State-Branch-Outbox und
`scripts/send_iphone_notifications.py`.

**Freigabestand:** Nach Merge und Einrichtung des SMTP-/IMAP-Zugangs darf
höchstens die Erinnerung aktiviert werden. Ein einziger tatsächlicher
Mail-Empfang auf dem iPhone muss separat nachgewiesen werden. Die
Buchung bleibt vom Kontoinhaber manuell bestätigt.
