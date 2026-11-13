# Sicherheit und Betriebsgrenzen

**ALDI-Kundenkonto: nur manuell prüfen.** Automatisierter Login, Statusabruf,
Diagnose und Buchung sind in den Repository-Workflows deaktiviert. Ohne
ausdrückliche Anbieterfreigabe keine Skripte oder Bots gegen das ALDI-Kundenportal
ausführen. Sichere Anleitung: [manuelle ALDI-Live-Prüfung](docs/aldi-safe-manual-live-check.md).

## Sicherheitsfix Webapp (05.11.2026)

Die alte Webapp (`webapp/app.py`) konnte ohne Authentifizierung im Netzwerk
aufgerufen werden, speicherte Zugangsdaten in Klartext und klickte ohne
dauerhaftes Buchungsjournal. Am 05.11.2026 wurde sie zunächst vollständig auf
eine **passive, nur lokal erreichbare Statusseite** reduziert. Die früheren
POST-Endpunkte `/api/config`, `/api/start`, `/api/stop` und `/api/test` waren dort
gesperrt (HTTP 410); kein Anbieterzugriff und kein Klick. Diese Zwischenlösung
band ausschließlich an Loopback und wies andere Geräte sowie fremde Hostnamen ab.
Das Verzeichnis `webapp/` ist inzwischen vollständig entfernt; auch diese lokale
Flask-Statusseite wird nicht mehr betrieben.

Der separate ALDI-Live-Runner prüft zusätzlich **`DRY_RUN=false` explizit** vor
jeder Anmeldung oder Journalauswertung. Ein nicht gesetztes, wahres oder
ungültiges `DRY_RUN` bricht mit `dry_run` ab. `AUTO_BOOK_ENABLED=true` allein
genügt nicht.

### Altinstallation absichern

1. Vorhandene alte Webapp-Prozesse stoppen. Ein Commit oder die Löschung des
   Verzeichnisses beendet keinen laufenden Server. Andere aktualisierte
   Altprozesse müssen gestoppt und neu gestartet werden, damit neue Prüfungen greifen.
2. Eine eventuell noch vorhandene `webapp/local_config.json` auf dem bisherigen
   Host löschen. Sie kann ein unverschlüsseltes Passwort enthalten. Auch Backups
   auf mögliche Kopien prüfen.
3. Betroffene Anbieterpasswörter ändern, besonders wenn die alte Webapp aus dem
   Netzwerk erreichbar war.
4. Das ALDI-Konto nur selbst über die offizielle App oder Website prüfen;
   [manuelle ALDI-Live-Prüfung](docs/aldi-safe-manual-live-check.md).

### Anforderungen vor einer Wiederinbetriebnahme

- Freigabe eines zulässigen Anbieterzugriffs, sichere Authentifizierung und Secret-Verwaltung
- Zugriffskontrolle und CSRF-/Origin-Schutz vor Netzwerkfreigabe
- Persistenter `PENDING`/`UNKNOWN`-Journal-Eintrag vor jedem Klick und eindeutige Duplikatsperre
- Vorgangsbezogene offizielle Bestätigung und kontrollierte Reconciliation
- Negative Tests, Crash- und Neustartsimulationen sowie gesonderte Freigabe

Der frühere Filmmodus bleibt stillgelegt.

## Prüfstand vom 26. Oktober 2026

**Keine automatisierte ALDI-Konto-Prüfung oder Nachbuchung.** Die aktuellen AGB
untersagen nicht autorisierte Skripte und Bots im Zugriff auf Vertragssysteme.
Die GitHub-Workflows für ALDI-Login, Diagnose und Refill sind deshalb deaktiviert.
Der Mailmonitor erkennt nur Nachrichten und startet keine Provider-Aktion.

Ein sicherer Konto-Live-Test ist nur manuell in der offiziellen ALDI-TALK-App
oder im Kundenportal vorgesehen. Tarif, Restvolumen, exakte 1-GB-Option und
0,00 € müssen im richtigen Konto sichtbar geprüft werden. Details:
[Sichere manuelle ALDI-Live-Prüfung](docs/aldi-safe-manual-live-check.md).

Die allgemeinen CLI-Beispiele `watcher.py` und `main.py` sind keine freigegebenen
ALDI-Live-Testwege. `DRY_RUN` und `AUTO_BOOK_ENABLED` sind keine Erlaubnis für
automatisierte ALDI-Portalzugriffe. Workflow-Guards können durch diese Variablen
nicht aufgehoben werden.

## Historischer Prüfstand vom 14. Oktober 2026

**Keine aktive automatische ALDI-Nachbuchung.** Auf dem geprüften Hauptbranch
`484aafd32dd8bfde54d97512fa9200e04a633e3f` führt `run.yml` nur Tests und
öffentliche Portalprüfungen aus. Die Modi sind `all`, `tests`, `public-probe`.
`all` bedeutet hier nicht Login oder Buchung. `AUTO_BOOK_ENABLED=false`.
Accounts, Status-Probe und Watchdog sind deaktiviert.

Der Mail-Monitor läuft laut Zeitplan alle fünf Minuten, ruft ausschließlich
Postfächer ab und startet keine Portalaktion. Lauf `38565976011` meldete
`no_mailboxes_configured`. Eine grüne öffentliche Probe ist kein Nachweis für
Anmeldung, geladenes Kundenkonto oder Nachbuchung.

Die Anbieterbedingungen zu nicht autorisierter Software stehen in den
[ALDI-TALK-AGB, Ziffer 10.3 g, PDF-Seite 16](https://media.medion.com/cms/medion/alditalkde/ALDI-TALK-Leistungsbeschreibung.pdf).
Eine Freigabe für den vorgesehenen Automationsweg ist nicht belegt.
Details und konkrete offene Schritte: [Betriebsprüfung](docs/operations-audit-2026-10-14.md).

## Vorhandener Buchungscode ist kein Live-Nachweis

`core/aldi_refill.py` akzeptiert bereits ein eindeutig zugeordnetes Gratisangebot
bei verifiziertem Tarif auch ohne numerische Nullpreis-Anzeige. Positive oder
unklare Preise werden abgelehnt. Diese Prüfung muss nicht pauschal entfernt werden.

`aldi_live_refill.py` protokolliert einen frischen Volumenzuwachs nur als
Beobachtung. Ohne offizielle, dem Vorgang zugeordnete Abschlussbestätigung
bleibt eine neue Buchung `UNKNOWN`; der Lauf endet mit Exit 2 und weitere
Buchungen bleiben über das persistente Journal gesperrt. Auch die
GitHub-Recovery darf alte Vorgänge nicht allein anhand eines Volumenzuwachses
als erfolgreich abschließen. `ALDI_RECONCILIATION_VERIFIED` ist false.
Die Erkennung der offiziellen Abschlussbestätigung ist noch nicht implementiert;
diese Sperre stellt keinen betriebsbereiten Nachbuchungsablauf her.

Installations- und Pluginbeispiele beschreiben vorhandene Codepfade, nicht eine
freigegebene oder nachgewiesene ALDI-Live-Konfiguration.

## Buchungsschutz für lokale Providerfunktionen

Der Pluginbetrieb nutzt den `BaseWatcher`-Ablauf: prüfen, entscheiden, `PENDING`
persistent schreiben, einmal buchen, Ergebnis speichern. Für LIDL verlangt eine
Buchung einen eindeutig aktiven `Unlimited on Demand S/M/L`, ein einzelnes
sichtbares Angebot für genau 1 GB Unlimited-Refill mit ausdrücklich kostenlosem
Preis und einen sichtbaren, aktivierten Button innerhalb dieses Angebots.
Preis, Sitzung, Tarif oder DOM unklar: keine Buchung. Eine Bestätigung muss neu
erscheinen und ausdrücklich eine erfolgreiche 1-GB-Buchung nennen.

Timeout oder unklare Bestätigung: `UNKNOWN`, keine Wiederholung oder Kanalwechsel.
Eine erfolgreiche Buchung sperrt weitere LIDL-Buchungen für 30 Minuten.
Ungeklärte `PENDING`/`UNKNOWN` bleiben über Neustarts gesperrt, bis ihr tatsächliches
Ergebnis überprüft und in der persistenten DB korrekt abgeglichen wurde.

`watcher.py` prüft die Verfügbarkeit und klickt weiterhin nie. Der separate
Pluginbetrieb `main.py` sieht bei `DRY_RUN=false` und `AUTO_BOOK_ENABLED=true`
eine verifizierte Buchung pro Durchlauf vor. **Die beiden Flags alleine belegen
keine Live-Reife:** Anmeldung, Selektoren und Erfolgsbestätigung sind noch am
tatsächlichen Konto zu validieren. Zuerst denselben zulässigen Ablauf in
`DRY_RUN=true` prüfen. Ein Dry-Run kann Netzzugriffe und Anmeldungen enthalten
und ist kein Offline-Test.

Der buchende Plugin-Dauerbetrieb benötigt eine dauerhafte SQLite-Datei auf
demselben Datenträger und darf nicht mit einer leeren DB je GitHub-hosted Runner
starten. Der separate ALDI-One-shot-Runner verlangt ein bestehendes privates,
dauerhaftes Buchungsjournal und prüft den Buchungserfolg nach dem Klick.
