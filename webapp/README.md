# Webapp – passiver Sicherheitsstatus (seit 05.11.2026)

Die frühere automatische Filmmodus-Webapp wurde aus Sicherheitsgründen deaktiviert.

## Lokale Ansicht

1. `pip install -r requirements.txt`
2. `python webapp/app.py`
3. Auf demselben Rechner `http://127.0.0.1:8000` öffnen.

Es gibt keine Netzwerkfreigabe für andere Geräte oder iPhones im WLAN. Der Server bindet ausschließlich an die Loopback-Adresse. Zugriffe anderer Geräte sowie fremde Hostnamen werden abgewiesen.

Die Webapp ist nur informativ. Alle früheren POST-Endpunkte für Konfiguration, Start, Stop und Tests melden HTTP 410. Es erfolgt kein Provider-Login, keine Kontoabfrage, kein Browserstart und kein Buchungsklick.

## Altinstallation absichern

1. Einen bereits laufenden Altprozess stoppen und den aktualisierten Dienst neu starten. Ein GitHub-Commit stoppt keinen laufenden Server.
2. Eine vorhandene Datei `webapp/local_config.json` auf dem Rechner löschen. Sie enthält unter Umständen ein unverschlüsseltes Passwort. Die neue App liest oder erstellt sie nicht mehr.
3. Betroffene Anbieterpasswörter ändern, besonders wenn die alte Webapp aus dem Netzwerk erreichbar war. Auch Backups auf mögliche Kopien prüfen.
4. Das ALDI-Konto nur selbst über die offizielle App oder Website prüfen; Details in `docs/aldi-safe-manual-live-check.md`.

## Anforderungen vor einer Wiederinbetriebnahme

- Freigabe eines zulässigen Anbieterzugriffs, sichere Authentifizierung und Secret-Verwaltung
- Zugriffskontrolle und CSRF-/Origin-Schutz vor Netzwerkfreigabe
- Persistenter `PENDING`/`UNKNOWN`-Journal-Eintrag vor jedem Klick und eindeutige Duplikatsperre
- Vorgangsbezogene offizielle Bestätigung und kontrollierte Reconciliation
- Negative Tests, Crash- und Neustartsimulationen sowie gesonderte Freigabe

Bis dahin bleibt der Filmmodus fail-closed.
