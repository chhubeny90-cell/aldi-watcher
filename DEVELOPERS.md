# Entwicklung und Konfiguration

Für Anbieterzugriffe gelten die [Sicherheits- und Betriebsgrenzen](SECURITY.md).
ALDI-Konten ausschließlich nach der [manuellen Prüfanleitung](docs/aldi-safe-manual-live-check.md)
prüfen; die vorhandenen Codepfade belegen keinen freigegebenen Livebetrieb.

## Architektur

```text
aldi-watcher/
├── core/
│   ├── __init__.py
│   ├── database.py      # SQLite-Schema mit provider-Spalte und Buchungsjournal
│   ├── security.py      # Fernet-Verschlüsselung
│   └── config.py        # Zentrale Konfiguration
├── plugins/
│   ├── __init__.py
│   ├── base_watcher.py  # BaseWatcher-Interface
│   ├── aldi_talk.py     # ALDI Talk Plugin
│   └── lidl_connect.py  # Lidl-Browser-Plugin; API deaktiviert
├── tests/
│   ├── __init__.py
│   ├── test_aldi_talk.py
│   ├── test_lidl_connect.py
│   ├── conftest.py
│   └── pytest.ini       # pytest-asyncio Konfiguration
├── main.py              # Orchestrator
├── pytest.ini
├── requirements.txt
├── .env.example
└── README.md
```

Die gemeinsamen Bausteine bieten Fernet-Verschlüsselung mit `.env`-Fallback,
SQLite-Logging aller Usage-Checks und Fehler, isolierte Watcher-Fehler sowie
exponentiellen Backoff bei Captchas und Timeouts. `DRY_RUN=true` verhindert
Buchungstransaktionen, ist aber kein Offline-Modus.

## Plugin-Erweiterung

`import plugins` lädt keine Watcher-Untermodule. Auch
`from plugins import BaseWatcher` benötigt weder aiohttp noch Playwright.
Die Providerklassen werden beim ersten Zugriff geladen und anschließend
zwischengespeichert; `dir(plugins)` zeigt sie ohne Import an. Fehlende optionale
Provider-Abhängigkeiten erzeugen einen `ImportError` mit Installationshinweis.
`from plugins import *` lädt dagegen alle in `__all__` aufgeführten Klassen
und benötigt deshalb deren Laufzeitabhängigkeiten. Die Browserinstallation
ist erst für den tatsächlichen Playwright-Betrieb erforderlich.

Neue Provider als Plugin in `plugins/` hinzufügen:

```python
from typing import Dict, Optional
from plugins.base_watcher import BaseWatcher

class NewProviderWatcher(BaseWatcher):
    async def check_usage(self) -> Dict[str, float]:
        # Implementierung
        pass

    async def trigger_recharge(self, recharge_id: Optional[str] = None) -> bool:
        # Implementierung; recharge_id nach Möglichkeit an den Anbieter weitergeben
        pass
```

## Konfigurationsdateien und Linux-Vorbereitung

Die [lokale Konfigurationsanleitung](docs/local-configuration.md) beschreibt
`install.sh`, die korrigierte `.env.example` und die vorbereiteten systemd-Units.
`bash install.sh` erhält eine vorhandene `.env` und startet nichts.
Der optionale stündliche Dienst prüft ausschließlich öffentliche Portalseiten,
ohne Zugangsdaten, Anmeldung oder Buchung. Er ist standardmäßig nicht aktiviert.

Zusätzliche Linux-Browserabhängigkeiten bei Bedarf installieren:

```bash
playwright install-deps chromium
```

### Lokale Konfiguration

1. Nur wenn noch keine lokale `.env` existiert, die Vorlage kopieren:
   ```bash
   cp .env.example .env
   ```
2. `.env` nur für ausdrücklich gewünschte, zulässige lokale Providerfunktionen
   bearbeiten. ALDI-Kundenzugangsdaten nicht für automatisierte Portalzugriffe
   eintragen; dafür liegt keine Anbieterfreigabe vor.
3. Credentials verschlüsseln und den Schlüssel separat speichern:
   ```bash
   python -m core.protect_config --key-file /private/path/credentials.key
   ```
   `.env` enthält danach `ALDI_USER_ENC`, `ALDI_PASS_ENC` usw. Der Befehl
   gibt keine Zugangsdaten oder Schlüssel aus. `CREDENTIAL_KEY_FILE` verweist
   beim Start auf die Schlüsseldatei. Alternativ hält der Laufzeit-Secret-Store
   den Schlüssel in `CREDENTIAL_ENCRYPTION_KEY`. Schlüssel niemals committen.
   Details: [Geschützte Konfiguration](docs/protected-configuration.md).

Für LIDL bleibt `LIDL_USE_API=false`; der API-Modus ist technisch gesperrt.
`LIDL_REFILL_MODE=needed` ist Standard. Beide Modi verlangen eine bestätigte
kostenlose Option und Restvolumen strikt unter `THRESHOLD_LIDL_MB` sowie strikt
unter 1024 MB. Die Schwelle bezeichnet **verbleibende MB**, Standard 1024.
Die Selektoren müssen aus einem beobachteten Kontoflow stammen; es gibt keine
Standardwerte. Der Monitoringcode verwendet die ersten drei, der Pluginbetrieb
zusätzlich die Erfolgsbestätigung. Buchungsbedingungen und Journalpflicht stehen
in [SECURITY.md](SECURITY.md#buchungsschutz-für-lokale-providerfunktionen).

### Mail-Konfiguration

Für mindestens ein Postfach sind `MAILBOX_1_HOST`, `MAILBOX_1_USER` und
`MAILBOX_1_PASS` als Actions Secrets erforderlich; `MAILBOX_1_PORT` ist optional
(Standard 993). Für ein zweites Postfach entsprechend `MAILBOX_2_*`.
Zusätzlich ist `ALDI_RECOVERY_KEY` für die dauerhafte HMAC-Deduplizierung nötig.
Der Workflow übergibt seinen eigenen `GITHUB_TOKEN` für den State-Branch.
Eine ChatGPT-Gmail-Verbindung stellt diese IMAP-Secrets nicht bereit.

## LIDL: kostenlose 1-GB-Unlimited-Nachbuchung

| Benötigter Selektor | Quelle im angemeldeten Konto |
| --- | --- |
| `LIDL_ACTIVE_TARIFF_SELECTOR` | Nur der Name des aktiven Tarifs, keine Angebotsliste |
| `LIDL_REFILL_OFFER_SELECTOR` | Genau ein Refill-Angebot mit 1 GB und explizitem Preis |
| `LIDL_REFILL_BUTTON_SELECTOR` | Button relativ **innerhalb** dieses Angebots |
| `LIDL_REFILL_SUCCESS_SELECTOR` | Neue, eindeutige Bestätigung dieser Buchung |

## Adaptive LIDL-Prüfung in main.py

`LIDL_ADAPTIVE_POLLING=true` nutzt die vorhandene Verbrauchsratenberechnung.
Prüfabstände liegen zwischen `LIDL_POLL_MIN_SECONDS=30` und
`LIDL_POLL_MAX_SECONDS=300`; unter 2048 MB höchstens 60 Sekunden auch ohne
Verbrauchshistorie. Fehler führen zu Backoff bis 3600 Sekunden, offene/unklare
Buchungen zu langsameren Prüfungen. Anbieter laufen unabhängig in jeweils
einem seriellen Worker. Gesunde LIDL-Sitzungen bleiben im Prozess erhalten;
Fehler, Sitzungsablauf und Shutdown schließen die Browserressourcen.
Es werden keine Cookies auf Platte exportiert und keine TinyFish-Profile importiert.

`request_check("lidlconnect")` ist ein **prozessinterner Adapterhaken**, kein
installierter SMS-/Mail-Empfänger. Ein späterer Empfänger muss Absender und SIM
zuordnen; mehrere Signale werden zusammengefasst und umgehen weder Mindestabstand
noch Fehler-Backoff noch Journal-/Buchungsregeln. Kein zweiter Buchungsprozess.
Der bestehende ALDI-Mailworkflow wird dadurch nicht an LIDL angeschlossen.

Die unveränderte 1800-Sekunden-Sperre nach erfolgreicher LIDL-Buchung verhindert
derzeit schnelle wiederholte Nachbuchungen. Vor einer Verkürzung braucht es
einen belastbaren frischen Volumen-/Transaktionsabgleich. Diese Optimierung
garantiert weder unterbrechungsfreies Highspeed noch aktivierten Dauerbetrieb.

## Tests

Die CI verwendet Python 3.11. Aus dem Repository-Verzeichnis:

```bash
python -m pytest -q
```

Mit zusätzlich installiertem `pytest-cov` ist `python -m pytest --cov=.` möglich.
Tests und öffentliche Portaldiagnosen belegen keine Anmeldung oder Nachbuchung.

## GitHub-Workflow

In `.github/workflows/run.yml` startet `workflow_dispatch` mit `mode=tests`
ausschließlich den Testjob. Öffentliche Portaldiagnosen laufen nur auf manuellen
Aufruf mit `mode=public-probe` oder `mode=all`; `run.yml` hat keinen Cron-Trigger.
Fehler werden in die über `DB_PATH` gewählte lokale
SQLite-Datei geschrieben und als Diagnose-Artefakt für sieben Tage aufbewahrt.
Diese Runner-Diagnose ist kein dauerhaftes Buchungsjournal.

Der passive Mailmonitor liegt in `.github/workflows/mail-trigger.yml` und läuft
mit `*/5 * * * *` alle fünf Minuten. Er liest das Postfach nur über IMAP im
Read-only-Modus, speichert Deduplizierungsmarken und einen bereinigten Bericht.
`DRY_RUN=true`, `AUTO_BOOK_ENABLED=false` und `notify_only` verhindern in diesem
Workflow Provider-Aufträge; er enthält weder Portalzugriff noch SMTP-Versand.
Benötigte Repository-Secrets sind `MAILBOX_2_HOST`, `MAILBOX_2_USER`,
`MAILBOX_2_PASS` und ein dauerhaft beibehaltener `ALDI_RECOVERY_KEY`.
`ALDI_STATE_ENCRYPTION_KEY` ist nur eine alternative Quelle für den
Deduplizierungsschlüssel, wenn kein Recovery-Key hinterlegt ist.

## Fehlerbehebung

- Fehlendes `aiohttp`: `pip install -r requirements.txt` ausführen.
- Playwright findet ein Element nicht: geschützte Selektoren am zulässigen
  Kontoflow prüfen; bei unbekanntem DOM bleibt die Buchung gesperrt.
- Bei pytest-Warnungen die vorhandenen `pytest.ini` und `tests/pytest.ini`
  berücksichtigen.
- Vor einem Update mit `git status` lokale Änderungen prüfen und bewahren.

Lizenz: MIT.

Der passive Mailworkflow ignoriert aktuell das fehlerhafte Postfach 1 und nutzt
ausschließlich `MAILBOX_2_HOST`, `MAILBOX_2_USER`, `MAILBOX_2_PASS` sowie optional
`MAILBOX_2_PORT`. Fehlende alternative Zugangsdaten bleiben ein Konfigurationsfehler.
