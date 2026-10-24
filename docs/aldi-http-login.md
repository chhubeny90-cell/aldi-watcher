# Kontrollierter Read-only-Login

`aldi_http_login_probe.py` verwendet den vorhandenen HTTP-Client für genau einen
Passwort-Login. Es gibt keinen Buchungsaufruf, SMS-Versand oder Passwort-Reset.
Ein Login-Erfolg verlangt die passende Rufnummer im Portal-Cookie und eine
geschützte, nichtleere Subscription-Antwort. **Tarif und Restvolumen sind damit
noch nicht nachgewiesen**; der Bericht führt diese Felder ausdrücklich als false.

## Voraussetzungen und genau ein Versuch

1. Der Eigentümer meldet sich einmal kontrolliert im offiziellen ALDI-Browser
   oder in der App an und prüft die richtige SIM. Bei Kontosperre diese zuerst
   über den offiziellen Weg auflösen. Keine automatischen Entsperrversuche.
2. Die Zielrufnummer ausschließlich als Repository-Secret `ALDI_PROFILE_1_USER`
   hinterlegen. `ALDI_USER` allein reicht für diesen Workflow nicht. Passwort
   über `ALDI_PASS` oder den vorhandenen verschlüsselten Passwortpfad hinterlegen.
   Keine Werte in Chat, Issues oder Logs veröffentlichen.
3. Vorhandener Journal-/Mailqueue-State muss lesbar, konsistent und ohne offene
   Vorgänge sein. Fehlender State wird nicht durch eine leere Historie ersetzt.
   Ein aktiver Auth-Backoff wird nicht gelöscht oder übergangen.
4. Workflow **ALDI HTTP Login** auf `main` einmal manuell starten und
   `manual_login_verified=true` nur nach Schritt 1 setzen. Diese Angabe ist die
   Erklärung des Eigentümers, kein unabhängig bestätigter Entsperrnachweis.

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
strukturelle Ergebnisse und `booking_clicks=0`. Cookies, Token, Rufnummer,
Passwort, Tariftext und Kontoantworten bleiben im Speicher.

Der Voraussetzungenlauf vom 23.10.2026:
https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40007371792
bestätigt nur Konfigurationspräsenz und gespeicherten Zustand. Konto und Passwort
sind grundsätzlich konfiguriert; das dedizierte Zielkonto fehlt. Der gespeicherte
Backoff ist abgelaufen. Das beweist weder aktuelle Zugangsdaten-Gültigkeit noch
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
