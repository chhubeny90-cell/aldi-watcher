# aldi-watcher

Überwachung von Prepaid-Datenvolumen für ALDI TALK und Lidl Connect.

## Verifizierter Betriebsstand vom 14. Oktober 2026

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

### Mail-Konfiguration

Für mindestens ein Postfach sind `MAILBOX_1_HOST`, `MAILBOX_1_USER` und
`MAILBOX_1_PASS` als Actions Secrets erforderlich; `MAILBOX_1_PORT` ist optional
(Standard 993). Für ein zweites Postfach entsprechend `MAILBOX_2_*`.
Zusätzlich ist `ALDI_RECOVERY_KEY` für die dauerhafte HMAC-Deduplizierung nötig.
Der Workflow übergibt seinen eigenen `GITHUB_TOKEN` für den State-Branch.
Eine ChatGPT-Gmail-Verbindung stellt diese IMAP-Secrets nicht bereit.

### Vorhandener Buchungscode ist kein Live-Nachweis

`core/aldi_refill.py` akzeptiert bereits ein eindeutig zugeordnetes Gratisangebot
bei verifiziertem Tarif auch ohne numerische Nullpreis-Anzeige. Positive oder
unklare Preise werden abgelehnt. Diese Prüfung muss nicht pauschal entfernt werden.

`aldi_live_refill.py` verwendet derzeit einen frischen Volumenzuwachs als
Erfolgsindikator. Das erfüllt die Anforderung einer offiziellen, dem Vorgang
zugeordneten Buchungsbestätigung nicht. Historische PENDING/UNKNOWN-Vorgänge
bleiben ungeklärt; `ALDI_RECONCILIATION_VERIFIED` ist false.

Die folgenden Installations- und Pluginbeispiele beschreiben vorhandene
Codepfade, nicht eine freigegebene oder nachgewiesene ALDI-Live-Konfiguration.

## Quickstart (5 Minuten)

```bash
# 1. Clone & Install
git clone https://github.com/chhubeny90-cell/aldi-watcher.git
cd aldi-watcher
pip install -r requirements.txt
playwright install chromium

# 2. Config
cp .env.example .env
# .env bearbeiten: ALDI_USER, ALDI_PASS, LIDL_USER, LIDL_PASS

# 3. Test (DRY_RUN=true!)
python main.py
```

## Features

- **ALDI Talk**: HTTP/API-basierte Überwachung
- **Lidl Connect**: Hybrid-Ansatz (API + Playwright Fallback)
- **Sicherheit**: Fernet-Verschlsselung (.secret.key) mit .env-Fallback
- **Safety-First**: DRY_RUN-Modus (default) verhindert echte Transaktionen
- **Resilienz**: Fehler-isolierte Watcher, exponentieller Backoff für Captchas/Timeouts
- **Datenbank**: SQLite-Logging aller Usage-Checks und Fehler

## Installation

```bash
# Clone Repository
git clone https://github.com/chhubeny90-cell/aldi-watcher.git
cd aldi-watcher

# Dependencies installieren
pip install -r requirements.txt

# Playwright-Browser installieren (für Lidl Fallback)
playwright install chromium

# Linux: Zusätzliche Systemabhängigkeiten
# playwright install-deps chromium
```

## Konfiguration

1. `.env.example` als `.env` kopieren:
   ```bash
   cp .env.example .env
   ```

2. `.env` bearbeiten:
   ```env
   ALDI_USER=your-aldi-username
   ALDI_PASS=your-aldi-password
   THRESHOLD_ALDI_MB=500
   
   LIDL_USER=your-lidl-username
   LIDL_PASS=your-lidl-password
   THRESHOLD_LIDL_MB=500
   
   DRY_RUN=true
   POLL_INTERVAL_SECONDS=3600
   DB_PATH=aldi_watcher.db
   ```

3. Credentials verschlüsseln, Schlüssel separat speichern:
   ```bash
   python -m core.protect_config --key-file /private/path/credentials.key
   ```
   `.env` enthält danach `ALDI_USER_ENC`, `ALDI_PASS_ENC` usw. Der Befehl
   gibt keine Zugangsdaten oder Schlüssel aus. `CREDENTIAL_KEY_FILE` verweist
   beim Start auf die Schlüsseldatei. Alternativ hält der Laufzeit-Secret-Store
   den Schlüssel in `CREDENTIAL_ENCRYPTION_KEY`. Schlüssel niemals committen.
   Details und offene Live-Gates: [Geschützte Konfiguration](docs/protected-configuration.md).

## Usage

```bash
# Einmaliger Read-only-Durchlauf
AUTO_BOOK_ENABLED=false python watcher.py --run-once

# Dauerbetrieb (mit Polling)
python main.py
```

### DRY_RUN-Modus

- **DRY_RUN=true** (default): Nur Simulation, keine echten Buchungen
- **DRY_RUN=false**: Plugin-Livebetrieb erfordert zusätzlich `AUTO_BOOK_ENABLED=true`; die Live-Abnahme steht noch aus.

## Architektur

```
aldi-watcher/
├── core/
│   ├── __init__.py
│   ├── database.py      # SQLite-Schema mit provider-Spalte
│   ├── security.py      # Fernet-Verschlsselung
│   └── config.py        # Zentrale Konfiguration
├── plugins/
│   ├── __init__.py
│   ├── base_watcher.py  # BaseWatcher-Interface
│   ├── aldi_talk.py     # ALDI Talk Plugin
│   └── lidl_connect.py  # Lidl Connect Plugin (API + Playwright Fallback)
├── tests/
│   ├── __init__.py
│   ├── test_aldi_talk.py
│   ├── test_lidl_connect.py
│   └── conftest.py
│   └── pytest.ini       # pytest-asyncio Konfiguration
├── main.py              # Orchestrator
├── requirements.txt
├── .env.example
└── README.md
```

## Tests

```bash
# Alle Tests ausfhren
pytest

# Tests mit Coverage
pytest --cov=.
```

## Plugin-Erweiterung

Neue Provider als Plugin in `plugins/` hinzufügen:

```python
from plugins.base_watcher import BaseWatcher

class NewProviderWatcher(BaseWatcher):
    async def check_usage(self) -> Dict[str, float]:
        # Implementierung
        pass
    
    async def trigger_recharge(self) -> bool:
        # Implementierung
        pass
```

## LIDL: kostenlose 1-GB-Unlimited-Nachbuchung

Der Pluginbetrieb nutzt denselben `BaseWatcher`-Ablauf wie ALDI: prüfen,
entscheiden, `PENDING` persistent schreiben, einmal buchen, Ergebnis speichern.
`LIDL_REFILL_MODE=available` reagiert auf den freigeschalteten kostenlosen
Refill-Button, unabhängig vom Verbrauch. Optional verlangt `needed` zusätzlich
Restvolumen <= `THRESHOLD_LIDL_MB`; diese Schwelle bezeichnet **verbleibende MB**.

Eine Buchung verlangt einen eindeutig aktiven `Unlimited on Demand S/M/L`,
ein einzelnes sichtbares Angebot für genau 1 GB Unlimited-Refill mit ausdrücklich
kostenlosem Preis und einen sichtbaren, aktivierten Button innerhalb dieses
Angebots. Preis, Sitzung, Tarif oder DOM unklar: keine Buchung. Eine Bestätigung
muss neu erscheinen und ausdrücklich eine erfolgreiche 1-GB-Buchung nennen.
Timeout oder unklare Bestätigung: `UNKNOWN`, keine Wiederholung oder Kanalwechsel.
Eine erfolgreiche Buchung sperrt weitere LIDL-Buchungen für 30 Minuten.
Ungeklärte `PENDING`/`UNKNOWN` bleiben über Neustarts gesperrt, bis ihr tatsächliches
Ergebnis überprüft und in der persistenten DB korrekt abgeglichen wurde.

Konfiguration: `LIDL_USE_API=false`, `LIDL_REFILL_MODE=available` sowie:

| Variable | Erforderliche Quelle im angemeldeten Konto |
| --- | --- |
| `LIDL_ACTIVE_TARIFF_SELECTOR` | Nur der Name des aktiven Tarifs, keine Angebotsliste |
| `LIDL_REFILL_OFFER_SELECTOR` | Genau ein Refill-Angebot mit 1 GB und explizitem Preis |
| `LIDL_REFILL_BUTTON_SELECTOR` | Button relativ **innerhalb** dieses Angebots |
| `LIDL_REFILL_SUCCESS_SELECTOR` | Neue, eindeutige Bestätigung dieser Buchung |

Es gibt keine erfundenen Standardselektoren für diese geschützten Konto-Elemente.
Sie müssen aus einer erfolgreichen Anmeldung und einem beobachteten Kontoflow
stammen. Die bisherigen API-Endpunkte und die Angaben zu Verbrauchskacheln sind
Altbestand und nicht live verifiziert. API-Verbrauchsabfragen können optional
weiter getestet werden; API-Buchungen sind gesperrt, weil das frühere Auswählen
des ersten DATA-Tarifs eine kostenpflichtige Option buchen konnte.

Für den geplanten GitHub-Monitoringlauf werden die ersten drei Selektoren als
Repository Variables eingebunden. `watcher.py` prüft damit zusätzlich die
Verfügbarkeit und klickt weiterhin nie. Der separate Pluginbetrieb `main.py`
führt bei `DRY_RUN=false` und `AUTO_BOOK_ENABLED=true` genau eine verifizierte
Buchung pro Durchlauf aus. **Die beiden Flags alleine belegen keine Live-Reife:**
Anmeldung, Selektoren und Erfolgsbestätigung sind noch am tatsächlichen Konto
zu validieren. Zuerst denselben Ablauf in `DRY_RUN=true` prüfen.

Der buchende Plugin-Dauerbetrieb benötigt eine dauerhafte SQLite-Datei auf demselben
Datenträger und darf nicht mit einer leeren DB je GitHub-hosted Runner starten. Der
separate ALDI-One-shot-Runner verlangt ein bestehendes privates, dauerhaftes
Buchungsjournal und prüft den Buchungserfolg nach dem Klick.

## Troubleshooting

### **`ModuleNotFoundError: No module named 'aiohttp'`**

```bash
pip install -r requirements.txt
```

### **`pytest` zeigt Warnungen / DeprecationWarnings**

```bash
# pytest.ini ist vorhanden?
cat tests/pytest.ini

# Falls nicht: git pull
git pull origin main
```

### **Lidl-API: `401 Unauthorized`**

- Credentials in `.env` prüfen
- API kann sich geändert haben → Playwright-Fallback wird automatisch genutzt
- Ein API-Fehler kann bei Verbrauchsabfragen einen Browser-Fallback auslösen.
  Nach einer Buchung mit unklarem Ergebnis gibt es niemals einen Fallback.

### **Playwright: `Element not found`**

- Selektoren sind veraltet → `playwright codegen` ausführen
- Die geschützten Refill-Selektoren über die oben genannten Variablen konfigurieren;
  bei unbekanntem Konto-DOM bleibt die Buchung gesperrt.

### **`git pull` gibt Merge-Konflikte**

```bash
# Lokale Änderungen prüfen
git status

# Falls lokale Änderungen: stash oder committen
git stash

# Dann pullen
git pull origin main
```

### **Python Version**

- **Empfohlen**: Python 3.9 oder höher
- **Minimum**: Python 3.8

```bash
python --version  # Sollte 3.8+ sein
```

## License

MIT
