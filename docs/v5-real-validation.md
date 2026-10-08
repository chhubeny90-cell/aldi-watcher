# V5: Prüfung mit echten ALDI-Mails — 08.10.2026

Zwei vollständige, unveränderte ALDI-Nachrichten wurden über den verbundenen,
authentifizierten Gmail-Connector gelesen: ein 80-%-Hinweis vom 02.10.2026,
23:21:41 UTC und die folgende Verbrauchsmeldung um 23:22:20 UTC.
`lite.mail.parse_gmail_message` akzeptierte beide anhand des tatsächlichen
Absenders, Betreffs, Gmail-Authentifizierungsheaders, DKIM-Signatur, MIME-Inhalts
und Empfangszeitpunkts. Ergebnis: `warning80` und `exhausted`.

Das verbundene Konto verwendet einen historischen Googlemail-Profilnamen;
die echten Gmail-Delivery-Header enthalten die entsprechende Gmail-Adresse.
Für die Prüfung wurde der tatsächlich empfangene, über denselben verbundenen
Account gelesene kanonische `Delivered-To`-Wert verwendet. Ein abweichender
Postfachwert wurde zunächst korrekt abgelehnt. Eine Zuordnung zu einem
produktiven ALDI-Tarif wurde daraus nicht abgeleitet.

Beide echten Mailereignisse liefen anschließend durch die reale LITE-Engine
mit `dry_run=True`, dem Alias `unmapped_mail_test` und dem tatsächlichen
`AldiPortal(PortalConfig())`. Es wurde kein Provider-Stub verwendet. Nur für
diese historische DRY_RUN-Prüfung wurden die ausgewählten Nachrichten
ausdrücklich akzeptiert und mit einer optionalen Altersgrenze von acht Tagen
verarbeitet. Der aktuelle LITE-Standard verwirft echte vergangene Ereignisse
nicht pauschal anhand ihres Alters; er prüft vor jeder Aktion den frischen
Providerzustand. Die Testgrenze war keine produktive Einstellung.

| Prüfung | Tatsächliches Ergebnis |
| --- | --- |
| Originale Mailklassifikation | 80-%-Hinweis und Verbrauchsmeldung korrekt erkannt |
| Reale Providerprüfung | Zweimal `FAILED / CHECK / account_flow_unconfigured` dauerhaft gespeichert |
| Browser-/Loginstart | 0; der fehlende verifizierte Account-Flow sperrt bereits vor dem Browserstart |
| Buchungsaufrufe / Buchungsreservierungen | 0 / 0 |
| Wiederholte Zustellung | Beide Ereignisse `DUPLICATE`; keine weitere Providerprüfung |
| Wiederholung in einem neuen Python-Prozess | Beide `DUPLICATE`; 0 Providerprüfungen, Logins und Buchungsaufrufe |
| SQLite | Privates DB-Verzeichnis; Datei mit Modus `0600`, vom Git-Repository ausgeschlossen |
| PRO auf diesen echten gespeicherten Ereignissen | 2 abgeschlossene Ereignisse, 2 Konfigurationsfehler, ein Mailzeitabstand von 39 Sekunden |

Die 39 Sekunden messen ausschließlich den Abstand der Empfangszeitpunkte
zwischen dem Warnhinweis und der Verbrauchsmeldung. Sie sind keine
Nachbuchungszeit, kein Nachweis einer Nachbuchung und kein Nachweis, dass beide
Mails dieselbe unveränderte Datenoption beschreiben. Die lokalen wenigen
Millisekunden bis zum Konfigurationsfehler messen ebenfalls keinen Login oder
Providerzugriff.

Diese Prüfung belegt den Weg **echte Mail → Parser → LITE-Ereignis → reale
Provider-Konfigurationsprüfung → persistierter Abschluss → Deduplizierung →
PRO-Auswertung**. Sie belegt keinen automatischen dauerhaften Mailempfang,
keinen erfolgreichen Accountlogin und kein erkanntes oder gebuchtes 0-€-1-GB-
Angebot. Dafür fehlen weiterhin die in
[v5-deployment-findings.md](v5-deployment-findings.md) beschriebenen Runtime-
Zugänge und verifizierten Account-/Tarifdaten.

Mailtexte, persönliche Anreden, Telefonnummern, vollständige Mail-IDs,
Passwörter und Tokens wurden nicht in diesen Bericht übernommen. Die private
SQLite-Datei wurde nicht committet. Kein Cloud-Dienst, bestehender Zeitplan oder
produktiver Providerzustand wurde durch diesen Test verändert.
