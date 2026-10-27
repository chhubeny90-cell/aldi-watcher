# ALDI-Login: aktueller Status und historischer Nachweis

## Aktueller Ablauf

Der Workflow **ALDI HTTP Login (disabled)** in
`.github/workflows/http-login.yml` ist auf `main` ausdrücklich deaktiviert.
Er enthält nur einen Sperrhinweis und endet mit Exit-Code 2. Er lädt keine
Zugangsdaten und führt weder Anmeldung noch authentifizierte Statusabfrage aus.
Ein manueller Dispatch wäre deshalb kein neuer Login-Test.

Die aktuelle Projektregel sieht ohne nachgewiesene ausdrückliche Anbieterfreigabe
keinen skriptgesteuerten Zugriff auf das geschützte ALDI-Kundenkonto vor. Der
verbliebene Probe-Code ist historische Implementierung, keine Ausführungsfreigabe.
Nicht durch direkte Python-Aufrufe, alte Commit-Stände, andere Diagnoseworkflows
oder das Löschen eines Backoffs ausweichen.

Für eine aktuelle Kontoprüfung verwendet der Kontoinhaber selbst die offizielle
ALDI-TALK-App oder das Portal. Der Abschnitt zur Read-only-Prüfung in
[der manuellen Prüfanleitung](aldi-safe-manual-live-check.md) beschreibt den
Abgleich von Ziel-SIM, Tarif, Restvolumen und Angebot. Der aktuelle Arbeitsauftrag
umfasst keine Buchung; die dort separat beschriebene manuelle Buchung ist keine
Freigabe dafür.

Für eine Rückmeldung genügen Zeitpunkt mit Zeitzone, die Aussage „richtige SIM
geprüft“, der angezeigte Tarif, Restvolumen mit Einheit sowie Angebots- und
Kostenhinweise. Keine Rufnummern, Passwörter, SMS-Codes, Cookies oder Token teilen.
Eine solche Rückmeldung ist eine Betreiberangabe, kein automatisierter Nachweis.

## Historischer Cloud-Login vom 25.10.2026

[Run 40241870678](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40241870678)
wurde auf Commit `be50fb8e0ba24966d162731d017116f393843dd6` erfolgreich beendet.
Das in [Issue #116](https://github.com/chhubeny90-cell/aldi-watcher/issues/116)
festgehaltene damalige bereinigte Protokoll dokumentiert:

- `outcome=login_verified`, `login_ok=true`, `account_match=true`;
- eine geschützte Subscription und einen Credential-Submit;
- `booking_clicks=0`, `read_only=true`, bestätigte Auth-Reservation;
- `tariff_loaded=false`, `remaining_volume_loaded=false`.

Dieser historische Account-/Subscription-Nachweis belegt weder den heutigen
Sitzungszustand noch Tarif, Restvolumen, Gratisangebot oder Buchungsbereitschaft.
Er ersetzt insbesondere nicht die Prüfung neuerer Main-Commits. Ein grüner
Jobstatus allein ist kein Ersatz für den strukturierten Ergebnisbericht.

Der frühere Hinweis auf ein fehlendes Zielkonto aus dem Voraussetzungenlauf vom
23.10.2026 ist historisch; er darf nicht ohne neue Prüfung als heutiger Blocker
übernommen werden. Damalige Secret-Präsenz beweist ebenso wenig heutige Gültigkeit.

## Voraussetzungen ohne ALDI-Kontakt prüfen

Der bestehende Workflow **WATCH Read-only Live Prerequisites** kann mit
`private_runtime=false` Konfigurations-Booleans und den gespeicherten
GitHub-Journal-/Queue-Zustand prüfen. Er meldet sich nicht bei ALDI an und ersetzt
keinen geschützten Kontoabruf. Der private Runner wird dabei nicht gestartet.

Nur sichere Präsenzwerte, feste Statuscodes und strukturelle Zähler auswerten.
Fehlende oder unlesbare Historie nicht durch einen leeren Zustand ersetzen.
Aktive Auth-Sperren nicht löschen oder umgehen. Ein abgelaufener Backoff beweist
weder eine aufgehobene Provider-Kontosperre noch die Zulässigkeit eines Logins.
Neue Zugangsdaten allein aktivieren keinen deaktivierten Workflow.

## Verbliebene Implementierung

`aldi_http_login_probe.py` enthält weiterhin den früheren Einmal-Login mit
Zielkonto-Prüfung, bestehendem Journal-/Queue-Abgleich und einer vorab per
Datei-SHA-CAS reservierten 24-Stunden-Sperre. Unbestätigte Schreibvorgänge,
Konflikte und unbekannte Ergebnisse dürfen nicht durch Wiederholung aufgelöst
werden. Die Reservation gilt nur für kooperierende Pfade; sie ist keine atomare
Transaktion über alle unabhängigen Queue-Dateien.

`AldiHttpLogin.verify_session(phone)` ist ein technischer Baustein für geschützte
GETs ohne neue Passwortübermittlung. Auch diese Requests greifen auf das
Kundenkonto zu und sind durch den aktuellen Projektstand nicht zur Ausführung
freigegeben. Die Existenz des Codes beweist keinen laufenden Dienst.

Eine künftige Aktivierung benötigt zunächst die nachgewiesene Anbieterfreigabe
und danach eine gesonderte technische Sicherheitsprüfung auf dem aktuellen
Commit. Dieser Text erteilt weder diese Freigabe noch eine Buchungsfreigabe.

## Protokollreferenz

Historische Implementierungsreferenz:

- https://github.com/JonasJoKuJonas/homeassistant-AldiTalk
- Revision `8d0b432e61094c4dc316b04c4180d276be577e41` (2026-09-02)
- `custom_components/aldi_talk/aldi_talk.py`, MIT-Hinweis:
  `third_party/homeassistant-alditalk-LICENSE.txt`

Diese Referenz beschreibt Technik und begründet keine Erlaubnis, den derzeitigen
Sperrhinweis des Projekts zu umgehen.
