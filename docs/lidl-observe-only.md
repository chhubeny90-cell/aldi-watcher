# Lidl Connect: nur beobachten

`lidl-observe.yml` führt `lidl_observe.py` aus. Der Ablauf kann keine Datenoption
buchen. Der einzige Klick übermittelt einmal die Anmeldung auf dem offiziellen
Lidl-Portal. Keine Anmeldung wird nach einem Fehler automatisch wiederholt.

Vorhandene Secrets `LIDL_USER`, `LIDL_PASS` beziehungsweise die verschlüsselten
Varianten und `CREDENTIAL_ENCRYPTION_KEY` werden wiederverwendet. Zusätzlich:

- `LIDL_EXPECTED_MSISDN`: vollständige Zielrufnummer, ausschließlich als Secret.
- `LIDL_ACCOUNT_SELECTOR`: ein sichtbares Element mit genau der ausgewählten
  Rufnummer. Eine Login-Kennung oder maskierte Nummer genügt nicht.
- `LIDL_REMAINING_SELECTOR`: sichtbarer, ausdrücklich als Restvolumen bezeichneter
  Wert, etwa „Restvolumen: 2.024 MB“. Ein Verbrauchswert wird nicht umgedeutet.
- `LIDL_ACTIVE_TARIFF_SELECTOR`: ausschließlich der aktive Tarifname.
- `LIDL_REFILL_OFFER_SELECTOR`: das einzelne kostenlose 1-GB-Unlimited-Angebot.
- `LIDL_REFILL_BUTTON_SELECTOR`: Button innerhalb dieses Angebots.

Selektoren müssen aus einem tatsächlich beobachteten angemeldeten Konto stammen.
Fehlende Konfiguration beendet den Lauf vor dem Browserstart. Ohne nachgewiesene
Zielrufnummer wird kein Restvolumen ausgegeben. Fehlt nur das Refill-Angebot,
kann das bestätigte Restvolumen trotzdem gemeldet werden; die Nachbuchbarkeit
bleibt unbekannt. Ein unsichtbares Angebot beweist keine konkrete Restgrenze.

Der Bericht unterscheidet `checked_at` (Versuch) und `observed_at` (erfolgreiche
Messung). GB werden dezimal mit 1.000 MB ausgewiesen. Vom Nutzer gemeldete Werte
werden nicht als aktuelle Messung gespeichert oder ausgegeben.

Ein Hinweis erscheint in der Actions-Zusammenfassung, sobald aktiver Tarif,
ausdrücklich kostenloses Angebot für genau 1 GB und aktivierter Button belegt
sind. Es erfolgt keine Buchung und kein E-Mail-/SMS-Versand. Der Bericht enthält
keine Rufnummer, Zugangsdaten, Cookies, Screenshots oder rohe Kontotexte.

Start: manueller Actions-Aufruf oder Push einer relevanten Datei auf `main` oder
`feature/lidl-observe-only`. Stündlicher Zeitplan auf dem Default-Branch:
Minute 17 UTC, in Berlin normalerweise ebenfalls Minute 17 jeder Stunde.
GitHub kann geplante Läufe verzögern. Ein Branch-Lauf aktiviert keinen Zeitplan
auf `main`. Fehlgeschlagene oder grüne Vorprüfungen sind kein Betriebsnachweis.

## Offline-Vorprüfung

`python lidl_observe.py --preflight` verwendet dieselbe Konfigurationsprüfung
wie die Beobachtung, ohne Browser oder Netzwerkzugriff. `PREFLIGHT_OK` bedeutet
nur, dass die erforderliche Konfiguration vorhanden und formal gültig ist;
`account_verified=false`, `observed_at=null` und Restvolumen unbekannt bleiben
bis zu einer erfolgreichen echten Beobachtung. `BLOCKED` führt zu Exit 2.
Der Workflow installiert Chromium erst nach erfolgreicher Vorprüfung.
Der bereinigte Bericht wird auch bei einem späteren Installationsfehler gesichert.

## Manuelle 1-GB-Weiterleitung (26.11.2026)

`lidl_observe.py` unterscheidet `refill_available` (ein eindeutig kostenloses
1-GB-Angebot mit aktiviertem Anbieterbutton ist sichtbar) von
`manual_refill_ready` (zusätzlich ist das explizit angezeigte Restvolumen
**strikt unter 1 GB** und das Zielkonto verifiziert). Eine Anzeige von exakt
`1 GB` bzw. `1024 MB` genügt nicht. Bei einer als MB angezeigten Menge gilt
`< 1024 MB`, bei GB-Angaben `< 1 GB`. Das vermeidet einen False-Positive
bei der unterschiedlich dargestellten Dezimal-/Binäreinheit.

Nur wenn alle Kriterien erfüllt sind, enthält der bereinigte Bericht
`manual_refill_url` mit der festen offiziellen URL
`https://kundenkonto.lidl-connect.de/mein-lidl-connect.html`.
Der Link öffnet lediglich das Kundenkonto; der Nutzer prüft das dortige
Angebot **erneut selbst** und betätigt den offiziellen 0,00-€-Button manuell.
Die Anzeige ist keine Buchungsbestätigung, kann veralten und enthält keine
Zugangsdaten oder Kontokennung. Beim Öffnen des Links erfolgen durch den
Watcher keine Anmeldung und keine Nachbuchung.

LIDL Connect teilte am 25.11.2026 per E-Mail mit, dass automatische
Nachbuchungen nicht gewünscht seien und keine Testzugänge bzw. API-Daten
bereitgestellt würden. Daher bleibt `booking_enabled=false` und
`booking_performed=false` unverändert. `UNKNOWN`- oder
`PENDING`-Buchungen werden durch diesen nur lesenden Pfad nicht umgangen.

**Betriebsblocker:** Die authentifizierten Selektoren und der echte
Zielkontonachweis fehlen. CI-Tests mit simulierten HTML-Elementen sind kein
Live-Abnahmebeleg. Keine Aktivierung des Buchungsworkers durch diese Änderung.
