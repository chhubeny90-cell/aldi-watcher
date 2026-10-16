# Verifizierter Betriebsstand – 16. Oktober 2026

## Echte Beobachtungen

- Beim ursprünglichen Übernehmen der Zugangsdaten aus einem Screenshot wurden fremde Zeichen mit erkannt. Diese lokale Übernahme wurde korrigiert. Die vorherigen fehlgeschlagenen Versuche belegen keine Kontosperre bei korrekten Daten.
- Der korrigierte HTTP-Login lieferte einen Token und eine Erfolgsweiterleitung. Das Konto-Cookie lag vor, enthielt die Rufnummer jedoch im internationalen Ziffernformat ohne Pluszeichen. Die bisherige Prüfung lehnte dieses Format ab.
- Nach Normalisierung wurde am 16.10.2026 um 13:39 Uhr Europe/Berlin ein echter lokaler Login bestätigt: login_ok=true, account_match=true, eine geschützte Subscription geladen. Ein weiterer lesender Abruf bestätigte den Login ebenfalls.
- Keine automatisierte Nachbuchung und kein Buchungsklick wurden durchgeführt.
- Der reine HTML-Abruf der geschützten Übersicht lieferte weder auswertbares Restvolumen noch einen Nachbuchungsbutton. Fehlende HTML-Daten sind kein Nachweis für fehlendes Volumen oder einen deaktivierten Button.

## Manuelle Screenshots

Die vom Nutzer übermittelten Bilder zeigen einen manuellen Safari-Vorgang: 617 MB vor der Aktion, danach die Anbietermeldung „Bestellung erhalten“, rund 1,6 GB Restvolumen und einen ausgegrauten +1-GB-Button. Dies ist historischer Screenshot-Stand, kein aktueller automatisierter Status. Die vom Nutzer vermutete Freigabeschwelle unter 1 GB muss im tatsächlichen geladenen Zustand geprüft werden.

## Verbindlicher weiterer Ablauf

Frische geschützte Übersicht laden, vollständige Kontodaten abwarten, SIM und Tarif prüfen, Restvolumen und aktivierten Gratis-Nachbuchungsbutton erfassen. Ein deaktivierter Button auf einer alten Seite ist nicht maßgeblich. Keine DOM-Manipulation zum Freischalten. Nur eine eindeutig zugeordnete kostenlose Nachbuchung auslösen und danach Anbieterbestätigung und aktualisiertes Volumen prüfen. Unklare Resultate bleiben unbestätigt.

Eine Verbrauchsmail kann eine frische Prüfung auslösen. Eine 80-Prozent-Mail allein beweist keine Nachbuchungsberechtigung. Zehn-Minuten-Nachprüfungen sind ein diskutierter Entwurf, noch kein eingerichteter Betriebsplan.

## Offene Betriebsblocker

1. Gerenderte Kontoübersicht mit frischem Volumen und Buttonzustand prüfen.
2. Echte kostenlose Buchung samt Ergebnisnachweis durchführen, sobald verfügbar.
3. Zugangsdaten in einen dauerhaften Secret-Store des ausführenden Hosts übernehmen. GitHub-Secrets wurden in dieser Sitzung nicht angelegt; die lokale verschlüsselte Ablage ist kein eingerichteter GitHub-Betrieb.
4. Mail-Zugang separat konfigurieren; ALDI-Passwort ist kein Gmail-App-Passwort.
5. Unbeaufsichtigten Ausführungsplan und Fehlerbehandlung real testen.

## Validierung

Nach den Codekorrekturen lokal: 463 Tests bestanden, 1 übersprungen, 12 Untertests bestanden. Diese lokale Arbeitskopie enthielt auch die separaten Einmallink-Diagnose-Dateien aus PR 86; die Zahl ist nicht automatisch die CI-Testzahl von PR 87. GitHub-CI war zum Dokumentationszeitpunkt noch in Arbeit. Kein End-to-End-Betriebsnachweis und keine Zusage für den Start am Abend.

Keine Passwörter, Schlüssel, Cookies, Tokenwerte oder Screenshots werden in diesem Dokument gespeichert.
