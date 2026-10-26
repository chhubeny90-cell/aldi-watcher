# Kontrollierter Read-only-Login

`aldi_http_login_probe.py` verwendet den vorhandenen HTTP-Client für genau einen
Passwort-Login. Es gibt keinen Buchungsaufruf, SMS-Versand oder Passwort-Reset.
Ein Login-Erfolg verlangt die passende Rufnummer im Portal-Cookie und eine
geschützte, nichtleere Subscription-Antwort. **Tarif und Restvolumen sind damit
noch nicht nachgewiesen**; der Bericht führt diese Felder ausdrücklich als false.

## Einmal einrichten

1. Die Zielrufnummer der richtigen SIM als Repository-Secret `ALDI_PROFILE_1_USER`
   hinterlegen. `ALDI_USER` allein reicht für diesen Workflow nicht. Passwort
   über `ALDI_PASS` oder verschlüsselt über `ALDI_PASS_ENC` zusammen mit
   `CREDENTIAL_ENCRYPTION_KEY` hinterlegen.
   Keine Werte in Chat, Issues oder Logs veröffentlichen.
2. Vorhandener Journal-/Mailqueue-State muss lesbar, konsistent und ohne offene
   Vorgänge sein. Fehlender State wird nicht durch eine leere Historie ersetzt.
   Ein aktiver Auth-Backoff wird nicht gelöscht oder übergangen.

## Login starten und Ergebnis lesen

1. In GitHub unter **Actions → ALDI HTTP Login → Run workflow** den Branch
   `main` auswählen und den Workflow einmal starten. Es gibt kein zusätzliches
   Bestätigungsfeld und keinen vorgeschriebenen Browser-/App-Login davor.
2. Nach dem Lauf die deutsche Zusammenfassung auf der Workflow-Seite lesen.
   Sie zeigt Erfolg oder Abbruchgrund und den nächsten Schritt. Fehlende
   Einrichtung wird mit den benötigten Secret-Namen erklärt. Bei aktivem
   Warteabstand steht der früheste nächste Versuch in UTC dabei.

Ein manueller Start autorisiert genau einen lesenden Loginversuch. Bei einer
gemeldeten Kontosperre diese über den offiziellen ALDI-Weg klären; der Workflow
entsperrt kein Konto und wiederholt den Login nicht automatisch.

Vor jedem ALDI-Kontakt reserviert der Probe einen **24-Stunden-Backoff** im
bestehenden öffentlichen, nichtidentifizierenden Auth-State. Die Aktualisierung
verwendet den zuvor gelesenen Datei-SHA als Compare-and-swap und wird anschließend
zurückgelesen. Nur bei bestätigter Reservation beginnt der Login. Dafür benötigt
allein dieser manuelle Job `contents: write`; Checkout speichert keine Credentials.
Es werden keine neuen Zugangs- oder Zahlungsdaten gespeichert.

Konflikte, unklare Schreibantworten, geänderte Queue, aktive Sperre und Lesefehler
führen zum Abbruch ohne ALDI-Kontakt. `reservation_status=unconfirmed` bedeutet:
Die Reservation könnte bereits gespeichert sein; nachsehen, nicht erneut starten.
Die Reservation bleibt nach Fehler, Timeout und Erfolg erhalten. Keine automatische
Wiederholung, keine Backoff-Overrides und keine erneuten Jobversuche. Pushes und
Commit-Marker starten diesen Login nicht mehr.

Die Sperre schützt Pfade, die denselben Auth-State beachten. Andere historische
Diagnoseworkflows lesen ihn bisher nicht durchgängig; sie dürfen nicht parallel
als Ersatz für diesen kontrollierten Ablauf verwendet werden. Der Datei-CAS ist
keine atomare Transaktion über sämtliche unabhängigen Queue-Dateien.

## Nachweise und Grenzen

Der JSON-Bericht enthält feste Fehlercodes, Phasen, Commit/Run-Zuordnung,
strukturelle Ergebnisse und `booking_clicks=0`. Das optionale Feld `retry_after`
enthält bei aktivem Abstand oder begonnener Reservierung den zugehörigen
Zeitpunkt in UTC. Bei unbestätigter Reservierung ist dies kein Nachweis, dass
der Zustand gespeichert wurde oder ein weiterer Versuch bereits zulässig ist.
Cookies, Token, Rufnummer, Passwort, Tariftext und Kontoantworten bleiben im Speicher.

Ein abschließender Schritt mit `if: always()` schreibt die deutsche Anzeige
über `GITHUB_STEP_SUMMARY`; der JSON-Bericht bleibt als Artefakt erhalten.
Fehlt der Bericht nach Timeout oder Abbruch oder ist er unlesbar, lautet das
Ergebnis ausdrücklich **„Login nicht bestätigt“**. Den gespeicherten Zustand
zuerst prüfen, statt sofort erneut zu starten. Wird der gesamte Job hart beendet,
kann auch dieser abschließende Schritt ausfallen; eine fehlende Zusammenfassung
ist ebenfalls kein Erfolgsnachweis. Unbekannte Fehler werden allgemein erklärt;
die Zusammenfassung übernimmt keine freien Anbieter- oder Fehlermeldungen.

Der Voraussetzungenlauf vom 23.10.2026:
https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40007371792
bestätigte nur Konfigurationspräsenz und gespeicherten Zustand. Konto und Passwort
waren grundsätzlich konfiguriert; das dedizierte Zielkonto fehlte. Der gespeicherte
Backoff war abgelaufen. Das beweist weder aktuelle Zugangsdaten-Gültigkeit noch
eine aktuelle oder aufgehobene Kontosperre. Kein ALDI-Login wurde dabei versucht.

`docs/live-login-status-2026-10-16.md` dokumentiert einen historischen **lokalen**
Login. Das ist kein aktueller Cloud-Login; die historischen Cloud-Fehlerartefakte
sind nicht mehr verfügbar. Ein frischer Login und anschließend ein separat
abgesicherter Tarif-/Volumenabruf bleiben erforderlich. Buchungen und Tarifwechsel
bleiben außerhalb dieses Auftrags.

## Protokollreferenz

- https://github.com/JonasJoKuJonas/homeassistant-AldiTalk
- Revision `8d0b432e61094c4dc316b04c4180d276be577e41` (2026-09-02)
- `custom_components/aldi_talk/aldi_talk.py`, MIT-Hinweis:
  `third_party/homeassistant-alditalk-LICENSE.txt`

Der Client verarbeitet bekannte ForgeRock-Callbacks und die dokumentierte
Rechenaufgabe. Credential-POSTs folgen keinen Weiterleitungen; GET-Weiterleitungen
werden auf die bekannten HTTPS-ALDI-Hosts beschränkt. Unbekannte zusätzliche
Authentifizierungsanforderungen führen zum Abbruch.
