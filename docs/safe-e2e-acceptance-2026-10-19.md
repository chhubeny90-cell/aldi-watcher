# Sichere End-to-End-Abnahme
Stand: 2026-10-19, Europe/Berlin. Status: BLOCKED.
Nutzergrenze: Erst Simulation, danach Konto-, Tarif-, Preis- und Abschlussnachweise. Kein automatischer Live-Buchungsversuch ohne ausdrückliche Freigabe.

## Verbindliche Reihenfolge
| Stufe | Nachweis | Bestehensbedingung |
| --- | --- | --- |
| SIM-01 | Anonymisierte Mail → Queue → persistentes Journal → simulierte Anbieterantwort | Keine echten Netz-/Login-/SMS-/Buchungsaufrufe; Instrumentierung weist null externe Aktionen nach |
| SIM-02 | Replay, Paralleltrigger, Crash vor/nach Reservierung, Neustart | Höchstens eine simulierte Buchung; kein Wiederholen ungeklärter Vorgänge |
| SIM-03 | Falschkonto, falscher Tarif, positiver/unklarer Preis, veraltete Bestätigung, Timeout | Kein Klick bei ungeklärten Vorbedingungen; nach unklarem Ausgang UNKNOWN und dauerhafte Sperre |
| ACCOUNT-01 | Frische authentifizierte Anbieteridentität | Exakter Vergleich mit konfiguriertem Ziel; in Berichten nur pseudonymisierte Kennung |
| TARIFF-01 | Aktiver Tarif und zugeordnetes Refill-Angebot | Genau das berechtigte kostenlose 1-GB-Angebot, kein Tarifwechsel |
| PRICE-01 | Preis desselben Angebots | Eindeutiger Nullpreis oder ausdrücklich kostenlos; Widerspruch/Mehrdeutigkeit blockiert |
| RECEIPT-01 | Vorhandener autoritativer Anbieterbeleg und Detektor-Fixture | Dem Konto und Vorgang zugeordnet, frisch; Bestelleingang, Banner oder Volumenzuwachs allein genügen nicht |
| APPROVAL-01 | Ausdrückliche Nutzerfreigabe nach Vorlage der Nachweise | Gilt nur für benannten Commit, Ziel, Angebot und genau einen Versuch; abgelaufene/verbrauchte Freigabe sperrt |
| LIVE-01 | Erst nach APPROVAL-01: einmaliger kontrollierter Versuch | Journal vor Aktion persistent; kein automatischer Retry/Kanalwechsel; Abschluss nur mit tatsächlichem Beleg |

Fehlt vor dem Versuch ein realer Abschlussbeleg als Detektorgrundlage, bleibt dies offen. Er darf nicht durch eine unfreigegebene Buchung beschafft werden. Der neue Vorgangsabschluss kann erst nach dem ausdrücklich genehmigten Versuch nachgewiesen werden; Vorabprüfung und tatsächlicher Abschluss sind getrennte Nachweise.

## Belegbindung und Zustände
Jeder Beleg enthält Kriterien-ID, genaue Commit-ID, Prüfzeit/Zeitzone, Quelle/Artefakt, Prüfer und Ergebnis. Anbieterdaten zusätzlich mit derselben Sitzung/Konto-/Angebotszuordnung und dokumentierter Gültigkeit. Änderungen an Auth, Buchung, Journal oder CAS invalidieren betroffene Belege. Fehlende, unbekannte oder doppelte Kriterien und fremde/veraltete Commits blockieren. Keine Secrets oder vollständigen Kontokennungen veröffentlichen.

DRY_RUN_READY bezeichnet ausschließlich die belegte Simulation und erlaubt keine externe Aktion. LIVE_READY startet keine Buchung; die Ausführung verlangt eine separate, einmalige Freigabeprüfung unmittelbar vor dem Seiteneffekt. PENDING/UNKNOWN sperren weitere Versuche dauerhaft bis zur belegten Klärung.

## Tatsächlich ausgeführte Teilprüfung
Quelle: PR #107, Commit `1dda8df2cbea07c516cba532e6bfb7257d43c0e7`, Dateien core/release_status.py und tests/test_release_status.py über GitHub gelesen. Isolierte lokale Ausführung ohne Anbieterzugriff. Acht vorhandene Testfunktionen direkt ausgeführt: bestanden. pytest ist lokal nicht installiert; kein pytest-/CI-Gesamtlauf behauptet. Keine vollständige Mail-zu-Aktor-Simulation ausgeführt.

Zusätzlicher Negativfall: ready()-Fixture mit `live={"UNDEFINED": True}`, live_authorization=True, provider_receipt_verified=True und account_binding_verified=True liefert LIVE_READY, obwohl separate Tarif-/Preisnachweise fehlen. Das ist ein Fehler der Entwurfs-Statusprüfung, kein Nachweis einer ausführbaren Livebuchung. Mit live_authorization=False liefert dieselbe Fixture DRY_RUN_READY.

Reproduktion auf exakt dem genannten PR-Commit:
```python
import runpy
from core.release_status import evaluate
ready = runpy.run_path("tests/test_release_status.py")["ready"]
data = ready()
data.update(live={"UNDEFINED": True}, live_authorization=True,
            provider_receipt_verified=True, account_binding_verified=True)
assert evaluate(data)["status"] == "LIVE_READY"  # reproduzierter Fehlbefund
```

## Offene Abnahme
- [ ] Fest definierte Pflichtkriterien einschließlich Tarif, Preis, Simulation und Freigabe im Evaluator erzwingen; unbekannte Kriterien ablehnen.
- [ ] Belege auf genau den geprüften Commit und die passende Konto-/Angebotsbindung prüfen.
- [ ] End-to-End-Simulation einschließlich Neustart/Replay/UNKNOWN tatsächlich ausführen und externe Aktionen ausschließen.
- [ ] Konto-, Tarif-, Preis- und Abschlussdetektornachweise getrennt erbringen.
- [ ] Einmalige Freigabe am tatsächlichen Ausführungspfad prüfen und erneut testen.

Bezug: Issue #106 und Draft PR #107. Diese Dokumentation ändert weder Produktivcode noch Zeitpläne oder Buchungsflags.
