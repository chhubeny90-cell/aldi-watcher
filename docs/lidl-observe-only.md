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
