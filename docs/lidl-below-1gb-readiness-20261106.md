# Lidl Connect: 1-GB-schwellengebundene Nachbuchung – Draft (2026-11-06)

Priorität hinter ALDI TALK, vor NettoKOM (#157). Diese Änderung erteilt **keine Live-Freigabe**.

## Ausgangslage

`main` verwendete `LIDL_REFILL_MODE=available` und `THRESHOLD_LIDL_MB=500` als Defaults. In `available` konnte ein als kostenlos erkanntes Angebot unabhängig vom angezeigten Restvolumen in die Buchungsentscheidung gelangen. Das entsprach nicht dem Nutzerziel: Nachbuchung **erst bei weniger als 1 GB Rest**.

## Änderungen im Draft

- `THRESHOLD_LIDL_MB=1024` (bestehender Code rechnet 1 GB in 1024 MB um)
- Standard `LIDL_REFILL_MODE=needed`
- Für **beide** Modi ist die nachgewiesene kostenlose Option bei strikt **weniger als 1024 MB** Restvolumen Voraussetzung.
- Vor einem potenziellen Buchungsklick wird **immer** der aktuelle Reststand erneut geprüft, auch bei explizit konfiguriertem Legacy-Modus `available`.
- Offline-Regressionsfälle prüfen die scharfe Schwelle, ungültige Volumenwerte, unklare/kostenpflichtige Angebote und Dry-Run ohne Buchung.

## Unverändert blockiert

Keine verifizierte Lidl-API; vorhandene Portal-Selektoren müssen anhand des **eigenen authentifizierten Kontos** nachgewiesen werden. Eine bestätigte SIM-/Tarifbindung, ein eindeutiges kostenloses 1-GB-Angebot und eine zugehörige Abschlussbestätigung sind offene Gates. Getrennte, persistente Vorgangs-IDs und Schutz vor Doppelklick/UNKNOWN bleiben verpflichtend. Ohne Prüfbelege kein Live-Start, kein Workflow oder Secret.

`LIDL_REFILL_MODE=available` bleibt für ältere Konfigurationen als Eingabewert erhalten, hebt aber die Restvolumenschwelle **nicht mehr auf**.

**Status:** Code-/Testvorschlag im separaten Draft, nicht gemergt und nicht live aktiviert.
