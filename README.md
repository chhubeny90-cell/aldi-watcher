# aldi-watcher

Überwachung von Prepaid-Datenvolumen für ALDI TALK und Lidl Connect.
[Sicherheit und ALDI-Zugriffsgrenzen](SECURITY.md) · [Entwicklung und Konfiguration](DEVELOPERS.md)

## Quickstart (5 Minuten)

```bash
git clone https://github.com/chhubeny90-cell/aldi-watcher.git
cd aldi-watcher
pip install -r requirements.txt
playwright install chromium
```

## Kernmodule

| Verzeichnis | Aufgabe |
| --- | --- |
| `core/` | Konfiguration, Credential-Schutz, SQLite-Protokolle und Buchungsjournale |
| `plugins/` | Gemeinsamer `BaseWatcher` und Provider-Implementierungen für ALDI TALK und Lidl Connect |
