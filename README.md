# aldi-watcher

Automatische Überwachung und Nachbuchung von Prepaid-Datenvolumen für **ALDI Talk** und **Lidl Connect**.

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

## ⚠️ Lidl Connect: API vs. Playwright

`plugins/lidl_connect.py` verwendet einen **Hybrid-Ansatz**:

### **API-Ansatz (Standard)**

- **Endpoints**:
  - Login: `POST https://api.lidl-connect.de/api/authenticate`
  - Usage: `GET https://api.lidl-connect.de/api/consumption`
  - Tariffs: `GET https://api.lidl-connect.de/api/tariff-options`
  - Recharge: `POST https://api.lidl-connect.de/api/tariff-option/book`

- **Vorteile**:
  - ✅ Schnell (kein Browser-Overhead)
  - ✅ Stabil (API ändert sich seltener als UI)
  - ✅ Weniger Dependencies

- **Nachteile**:
  - ⚠️ API kann sich ändern (reverse-engineered)
  - ⚠️ Eventuell Captchas bei zu vielen Requests

### **Playwright-Fallback**

Falls die API nicht verfügbar ist, wechselt das Script automatisch auf Playwright.

**CSS-Selektoren (müssen ggf. angepasst werden)**:
- `input[type='tel']`: Rufnummer-Input
- `input[type='password']`: Passwort-Input
- `button[type='submit']`: Login-Button
- `div.consumption-tile`: Datenkachel
- `span.consumption-value`: Verbrauchswert
- `button[data-testid='book-tariff']`: Nachbuchung
- `div.alert-success`: Erfolgsmeldung

### **Selektoren ermitteln (falls API nicht geht)**

```bash
# Playwright Codegen starten
playwright codegen https://kundenkonto.lidl-connect.de/mein-lidl-connect.html
```

- Im Browser anmelden
- Durch die UI navigieren
- Generierte Selektoren in `plugins/lidl_connect.py` eintragen

### **API-Modus umschalten**

In `plugins/lidl_connect.py`:

```python
# Standard: API-first
LidlConnectWatcher(username, password, threshold_mb, dry_run, use_api=True)

# Nur Playwright (falls API gar nicht geht)
LidlConnectWatcher(username, password, threshold_mb, dry_run, use_api=False)
```

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
- Console-Log: `"Lidl API failed, falling back to Playwright"`

### **Playwright: `Element not found`**

- Selektoren sind veraltet → `playwright codegen` ausführen
- Neue Selektoren in `plugins/lidl_connect.py` eintragen

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
