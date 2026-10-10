> **V3.3 safety update:** ALDI live booking is blocked in code until verified
> per-operation provider reconciliation exists. Scheduled workflow runs perform
> regression tests only. The proposed durable-journal deployment and remaining
> activation requirements are documented in `docs/monitoring-recovery.md`.

# aldi-watcher

Überwachung von Prepaid-Datenvolumen für **ALDI Talk** und **Lidl Connect**, mit einem streng abgesicherten ALDI-Live-Refill.

## Aktiver Betrieb und Full Run

Der aktuelle Workflow führt **stündlich nur Regressionstests** aus. Er startet
dabei weder einen ALDI-Login noch eine Buchung. Ein Read-only-Watch ist separat
manuell über `workflow_dispatch` mit `watch` oder `all` startbar; auf einem
Push wird er nur bei `[live-watch]` im Commit ausgelöst.

Der Modus `live-refill` ist ausschließlich manuell auf `main` vorgesehen und
verlangt zusätzlich `ALDI_V33_LIVE_ENABLED=true`, einen konfigurierten
`ALDI_JOURNAL_PATH` sowie einen dauerhaften privaten Self-hosted-Linux-Runner
mit dem Label `aldi-journal`. Der Workflow begrenzt den Lauf auf höchstens
eine Nachbuchung.

**Der ALDI-Buchungscode ist trotzdem gesperrt:** `aldi_live_refill.py` setzt
`ALDI_RECONCILIATION_VERIFIED = False` und beendet den Lauf vor dem Login mit
`provider_reconciliation_unverified`. Ein echter Buchungserfolg und eine
eindeutige ALDI-Belegabfrage sind nicht nachgewiesen. Ein manueller Start,
`AUTO_BOOK_ENABLED=true` oder die interne Zustimmung des Kontoinhabers heben
diese Sperre nicht auf. Zusätzlich muss EPS den automatisierten Portalzugriff
ausdrücklich autorisieren; siehe [ALDI-TALK-AGB](https://www.alditalk.de/leistungsbeschreibung),
Ziffer 10.3 g. Einen Einmal-Lauf kann man dort anfragen, aber er ist nicht
automatisch von der Autorisierungspflicht ausgenommen.

Der frühere README-Hinweis auf einen stündlichen Live-Refill und einen
`[live-refill]`-Push-Auslöser war falsch. Die aktuelle Workflow-Definition ist
maßgeblich. Details zu offenen Gates: [Monitoring-Recovery](docs/monitoring-recovery.md).
```bash
# Tests: ohne echte Providerzugriffe
python -m pytest -q
# Monitoring: Zugangsdaten vorher über sichere Umgebungsvariablen bereitstellen
AUTO_BOOK_ENABLED=false python watcher.py --run-once
# Nur ALDI prüfen
AUTO_BOOK_ENABLED=false python watcher.py --run-once --provider aldi_talk
```

Für GitHub Actions identifiziert `ALDI_PROFILE_1_USER` (Fallback `ALDI_USER`)
das Main-Profil. Falls der Loginname abweicht, verwende
`ALDI_PROFILE_1_LOGIN_USER` (Fallback `ALDI_LOGIN_USER`); ohne separaten
Loginnamen verwendet der Code die Profilkennung. `ALDI_PASS` liefert das Passwort.
Die vorhandenen verschlüsselten Alternativen `ALDI_LOGIN_USER_ENC`,
`ALDI_USER_ENC`, `ALDI_PASS_ENC` und `CREDENTIAL_ENCRYPTION_KEY` werden ebenfalls
an den Lauf übergeben. Hinterlege Werte unter **Settings → Secrets and variables
→ Actions**. Andere Profile werden vom Workflow nicht verarbeitet.
`LIDL_USER` und `LIDL_PASS` gehören zum separaten Pluginbetrieb.
Details stehen in [docs/monitoring-recovery.md](docs/monitoring-recovery.md).

Tarif S ist nur bei einem explizit kostenlosen 1-GB-Angebot buchbar; der Preis
der Tarifverlängerung zählt nicht als Preisnachweis für dieses Zusatzangebot.

Ein abgeschlossener Lauf benötigt `finished_at` im bereinigten JSON-Bericht.
Exitcodes: 0 erfolgreich, 1 fehlgeschlagen, 2 teilweise erfolgreich,
3 Konfigurationsfehler. LIDL meldet zusätzlich `refill_eligible`, `refill_type` und `refill_reason`,
wenn die verifizierten Konto-Selektoren konfiguriert sind. Tarif-/Refill-
Berechtigung und echte Status-Reconciliation sind noch nicht live nachgewiesen. Ein Session-/Volumen-Erfolg ist keine
Buchungsfreigabe.

`main.py` ist der separate Plugin-Dauerbetrieb mit `.env` und SQLite.
Seine DB muss über Neustarts auf demselben persistenten Datenträger liegen.
Der sichere Standard ist `DRY_RUN=true`, `AUTO_BOOK_ENABLED=false`.
Ungültige Flags werden abgelehnt. Live-Pluginbetrieb verlangt beide expliziten
Flags `DRY_RUN=false` und `AUTO_BOOK_ENABLED=true`, darf aber erst nach belegter
Tarifentscheidung und Provider-Reconciliation aktiviert werden.

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
separate ALDI-One-shot-Runner braucht keine DB und prüft den Buchungserfolg nach dem Klick.

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
