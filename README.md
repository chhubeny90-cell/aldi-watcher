# aldi-watcher

Automatische Überwachung und Nachbuchung von Prepaid-Datenvolumen für **ALDI Talk** und **Lidl Connect**.

## Features

- **ALDI Talk**: HTTP/API-basierte Überwachung
- **Lidl Connect**: Playwright (Headless Browser) mit exponentiellem Backoff
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

# Playwright-Browser installieren
playwright install chromium

# Linux: ZusÃ¤tzliche SystemabhÃ¤ngigkeiten
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

3. (Optional) Credentials verschlsseln:
   ```bash
   python -c "from core.security import SecurityManager; s=SecurityManager(); print(s.encrypt('your-password'))"
   ```
   Output als `ALDI_PASS_ENC`, `LIDL_PASS_ENC` in `.env` speichern.

## Usage

```bash
# Einmaliger Durchlauf
python main.py

# Dauerbetrieb (mit Polling)
python main.py
```

### DRY_RUN-Modus

- **DRY_RUN=true** (default): Nur Simulation, keine echten Buchungen
- **DRY_RUN=false**: Echte Nachbuchungen werden ausgelst

## Architektur

```
aldi-watcher/
â»¿â»¿core/
â»¿â»¿â»¿â»¿â»¿â»¿__init__.py
â»¿â»¿â»¿â»¿â»¿â»¿database.py      # SQLite-Schema mit provider-Spalte
â»¿â»¿â»¿â»¿â»¿â»¿security.py      # Fernet-Verschlsselung
â»¿â»¿â»¿â»¿â»¿â»¿config.py        # Zentrale Konfiguration
â»¿â»¿plugins/
â»¿â»¿â»¿â»¿â»¿â»¿__init__.py
â»¿â»¿â»¿â»¿â»¿â»¿base_watcher.py  # BaseWatcher-Interface
â»¿â»¿â»¿â»¿â»¿â»¿aldi_talk.py     # ALDI Talk Plugin
â»¿â»¿â»¿â»¿â»¿â»¿lidl_connect.py  # Lidl Connect Plugin (Playwright)
â»¿â»¿tests/
â»¿â»¿â»¿â»¿â»¿â»¿__init__.py
â»¿â»¿â»¿â»¿â»¿â»¿test_aldi_talk.py
â»¿â»¿â»¿â»¿â»¿â»¿test_lidl_connect.py
â»¿â»¿â»¿â»¿â»¿â»¿conftest.py
â»¿â»¿main.py              # Orchestrator
â»¿â»¿requirements.txt
â»¿â»¿.env.example
â»¿â»¿README.md
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

## ⚠️ Wichtiger Hinweis: Lidl Connect CSS-Selektoren

Die CSS-Selektoren in `plugins/lidl_connect.py` sind **PLATZHALTER** und müssen angepasst werden!

### So ermittelst du die echten Selektoren:

1. **Playwright Codegen** (empfohlen):
   ```bash
   playwright codegen https://www.lidl-connect.de/login
   ```
   - Melde dich im Codegen-Fenster an
   - Klicke durch die UI
   - Kopiere die generierten Selektoren

2. **DevTools manuell**:
   - Öffne lidl-connect.de im Browser
   - Rechtsklick → "Untersuchen"
   - Notiere die echten IDs/Klassen für:
     - Login-Form
     - Username/Password-Inputs
     - Login-Button
     - Datenvolumen-Anzeige
     - Nachbuchungs-Button
     - Erfolgsmeldung

3. **Ersetze in `plugins/lidl_connect.py`**:
   ```python
   SELECTORS = {
       "login_form": "form#actualFormId",
       "username_input": "input#actualUsernameId",
       # ... etc.
   }
   ```

## License

MIT
