# Lokale Konfiguration und vorbereiteter Linux Dienst

Stand 24. Oktober 2026. Dieses Setup ergänzt die vorhandene Repository-Architektur.
Der Word-Entwurf ist kein Ersatz für `watcher.py`, `core/config.py` oder die
Buchungsjournale. Es gibt weiterhin keinen nachgewiesenen automatischen Livebetrieb.

## Dateien und Geltungsbereich

| Datei | Zweck |
| --- | --- |
| `.env.example` | Leere Zugangsfelder und sichere Standardwerte für vorhandenen Code |
| `requirements.txt` | Bestehende gemeinsame Python-Abhängigkeiten; unverändert weiterverwenden |
| `install.sh` | Lokale Vorbereitung, optional Abhängigkeiten; kein Start |
| `deploy/public-probe.env.example` | Nur lokale Browserpfade für öffentliche Diagnose |
| `aldi-watcher.service` | Einmalige öffentliche Diagnose, keine Formulareingabe |
| `aldi-watcher.timer` | Optional stündlicher Start der öffentlichen Diagnose |

Die Unit ruft ausschließlich `portal_probe.py` auf. Sie prüft öffentliche Seiten
von ALDI und Lidl, weder Restvolumen noch ein angemeldetes Konto. Auch ein
Ergebnis `complete` belegt nur den Abschluss der Diagnose, keine Provider-Verfügbarkeit
oder Live-Reife. Kein Mail-Sensor, kein Buchungsaktor und kein Windows-Task wird
hier eingerichtet. Bestehende Scheduler nicht zusätzlich für denselben Zweck starten.

## Lokale Vorbereitung

Aus einem überprüften Checkout mit Python 3.10 oder neuer:

```bash
bash install.sh
# Optional: venv anlegen und bestehende requirements installieren (Netzzugriff):
bash install.sh --install-deps
```

Ohne Option wird nur eine noch nicht vorhandene `.env` mit Modus 0600 angelegt.
Bestehende `.env` einschließlich Inhalt und Rechten bleibt unverändert. Symlinks
werden abgewiesen. Kein Schlüssel und keine Datenbank werden angelegt, keine
bestehende Historie wird ersetzt. Abhängigkeiten sind im Repository teilweise
als Versionsbereiche definiert; dies ist kein reproduzierbarer Lockfile-Build.

Zugangsdaten ausschließlich privat pflegen. `ALDI_USER` bezeichnet die SIM;
`ALDI_LOGIN_USER` ist ein optionaler abweichender Portal-Benutzername. Ein leeres
Konto ist absichtlich nicht startbereit. Für Verschlüsselung die vorhandene
[Anleitung](protected-configuration.md) verwenden. Der normale Start erzeugt
keinen Schlüssel. `CREDENTIAL_KEY_FILE` muss auf den passenden bestehenden
Credential-Schlüssel zeigen. Der HMAC-Schlüssel `ALDI_RECOVERY_KEY` ist davon
getrennt und darf nicht durch einen neu erzeugten Ersatzwert ersetzt werden.

`DRY_RUN=true` und `AUTO_BOOK_ENABLED=false` bleiben die Defaults. Alte Variablen
wie `ALDI_DRY_RUN`, `ALDI_RUN_MODE` oder `ALDI_LOG_PAYLOAD` aus dem Word-Entwurf
steuern diesen Repository-Code nicht. Ein Dry-Run kann je nach Einstiegspunkt
Netzzugriffe und Anmeldungen enthalten und ist deshalb kein Offline-Test.

## Linux systemd Vorbereitung

Die Vorlagen setzen voraus:

- überprüfter Checkout und seine venv unter `/opt/aldi-watcher`, für das
  Dienstkonto lesbar, aber nicht schreibbar;
- eigenes unprivilegiertes Systemkonto und Gruppe `aldi-watcher`;
- systemd sowie lokal installiertes Chrome/Chromium und dazu passender ChromeDriver;
- `/etc/aldi-watcher/public-probe.env` als root-verwaltete Datei mit Modus 0600,
  kopiert aus `deploy/public-probe.env.example`, mit den tatsächlich installierten
  absoluten Browserpfaden. Die Beispielpfade sind distributionsabhängig.

Keine Provider-Zugangsdaten oder Schlüssel in diese Dienstkonfiguration kopieren.
`env -i` übergibt dem Prozess nur die explizit in der Unit aufgeführten Variablen.
Die öffentliche Diagnose lädt keine Credential-Konfiguration. Berichte liegen
unter `/var/lib/aldi-watcher-public/portal-probe-report.json`; systemd erstellt
State- und Cache-Verzeichnis privat. Das Repository bleibt schreibgeschützt.
Der vorhandene Browserstarter verwendet `--no-sandbox`; das dedizierte Konto
und die systemd-Härtung ersetzen keinen Browser-Sandbox-Nachweis.

Nach manueller Einrichtung der Voraussetzungen können die Units installiert
und syntaktisch geprüft werden. Diese Befehle starten keinen Dienst:

```bash
sudo install -m 0644 aldi-watcher.service /etc/systemd/system/aldi-watcher.service
sudo install -m 0644 aldi-watcher.timer /etc/systemd/system/aldi-watcher.timer
sudo systemd-analyze verify /etc/systemd/system/aldi-watcher.service /etc/systemd/system/aldi-watcher.timer
sudo systemctl daemon-reload
```

Der Installer führt diese Befehle nicht aus. Die zusätzliche Freigabedatei
`/etc/aldi-watcher/public-probe.enabled` fehlt absichtlich. Erst wenn der Betreiber
sie bewusst anlegt und `aldi-watcher.timer` aktiviert, startet die öffentliche
Diagnose stündlich mit bis zu 60 Sekunden Verzögerung. Es gibt keine automatischen
Fehler-Neustarts und kein Nachholen ausgefallener Termine. Ein laufender
One-shot-Dienst wird durch seinen Timer nicht parallel erneut gestartet.
`TimeoutStartSec=180` begrenzt einen Lauf; Fehler werden nicht als Erfolg maskiert.

## Bewusste Aktivierung ausschließlich der öffentlichen Diagnose

Nur auf dem vorbereiteten Linux-Host und nach Prüfung obiger Voraussetzungen:

```bash
sudo touch /etc/aldi-watcher/public-probe.enabled
sudo systemctl enable --now aldi-watcher.timer
systemctl list-timers aldi-watcher.timer
journalctl -u aldi-watcher.service
```

Abschalten:

```bash
sudo systemctl disable --now aldi-watcher.timer
sudo systemctl stop aldi-watcher.service
sudo rm -f /etc/aldi-watcher/public-probe.enabled
```

Diese Anleitung wurde nicht auf dem Nutzergerät ausgeführt. Ein grüner lokaler
Test oder GitHub-CI-Lauf ersetzt keine tatsächliche Dienstprüfung auf diesem Host.

## Angemeldeter Betrieb bleibt separat

Die kontrollierte ALDI-Anmeldung hat eigene Konto-, Journal- und Backoff-Prüfungen;
siehe [kontrollierter Login](aldi-http-login.md). Den öffentlichen Dienst nicht
auf `watcher.py`, `main.py` oder einen Buchungsaktor umbiegen, um diese Prüfungen
zu umgehen. Tatsächliche IMAP-/SIM-/Tarifzuordnung, historienkompatibler Recovery-Key,
privates Journal und offizieller Abschlussnachweis bleiben eigene Voraussetzungen.
