# Abnahme des ALDI-Abschlussdetektors

Stand: 16.10.2026. Diese Matrix übernimmt die manuell übermittelten
Review-Anforderungen mit korrigierten Freigabestufen. Sie ist keine Betriebsfreigabe.

## Nachweisgrenzen

Die Sicherheitskorrektur in PR #93 verhindert Erfolg allein durch Volumenzuwachs.
Ein offizieller, vorgangsgebundener Abschlussdetektor ist noch nicht implementiert.
Die lokale Suite des implementierten Codes bestand mit 468 Tests und 12 Subtests;
ein bestehender Test wurde übersprungen. Simulationen und allgemeine Journaltests
beweisen weder eine aktuelle Anmeldung noch eine echte Nachbuchung.

`live-login-status-2026-10-16.md` dokumentiert einen früheren erfolgreichen
HTTP-Login und eine geladene Subscription. Dieser historische Bericht wurde für
diese Abnahme nicht durch einen neuen Login oder einen vollständigen Kontoflow
erneut verifiziert. Die Screenshots belegen einen manuellen Bestelleingang.

Status: **abgedeckt** bezeichnet den unten genannten begrenzten Code-/Testnachweis;
**teilweise** oder **offen** darf nicht als bestandene Gesamtanforderung gelten.

## Anforderungen und vorhandene Nachweise

| ID | Präzise Anforderung | Stand und Nachweis |
| --- | --- | --- |
| AC-01 | Kein Erfolg ohne offiziellen, zum Vorgang gehörenden Abschluss | Teilweise: aktueller Neuversuch und Hosted-Recovery bleiben UNKNOWN. Positiver Abschlussdetektor fehlt. |
| AC-02 | Volumenzuwachs ist nur Beobachtung | Abgedeckt: `test_refreshed_volume_without_official_receipt_stays_unknown`, vier Volumenwerte; Report und Journal werden geprüft. |
| AC-03 | Identitätsgleichheit allein beweist keinen Erfolg | Abgedeckt im selben Test. Identitätsabweichungen dürfen weiterhin Aktionen verhindern; das Beobachtungsfeld ist kein Erfolgsbeleg. |
| AC-04 | Bestelleingangs-Banner allein erzeugt keinen Erfolg | Teilweise: aktueller Pfad meldet keinen Erfolg; ein gezielter Test mit echter Bannerstruktur fehlt. |
| AC-05 | Historischer Abschlussbeleg bestätigt keinen neuen Vorgang | Offen für den künftigen Detektor. Der Test alter UNKNOWN-Vorgänge ist kein Test einer alten UI-Bestätigung. |
| AC-06 | Abschlussquelle bindet den Nachweis an genau diesen Vorgang | Offen: Quelle und Bindungsverfahren noch nicht technisch nachgewiesen. Eine lokale UUID allein genügt nicht. |
| AC-07 | Ein belegtes SUCCESS entfernt den Vorgang aus ungelösten Buchungen | Allgemeines Journalmodell abgedeckt; echte ALDI-Bestätigung und positiver Detektorpfad offen. |
| AC-08 | UNKNOWN blockiert neue Buchungen | Abgedeckt: Journal-, Runner- und wiederholte Recovery-Tests. |
| AC-09 | PENDING blockiert neue Buchungen | Abgedeckt: `test_begin_recharge_blocks_duplicate` und Crash-Tests. |
| AC-10 | Recovery erzeugt keinen Erfolg aus Volumendaten | Abgedeckt: `test_recovery_without_official_receipt_does_not_query_volume_or_release_guard`. |
| AC-11 | Live-Auswertung und Recovery verwenden dieselbe autoritative Abschlussquelle | Offen: beide Wege bleiben UNKNOWN, aber es gibt noch keine gemeinsame Abschlussquelle. |
| AC-12 | Erfolgszähler steigt nur nach belegtem SUCCESS | Negativpfad abgedeckt; positiver ALDI-Detektortest offen. |
| AC-13 | verified=True nur bei belegtem SUCCESS | Negativpfad abgedeckt; positiver ALDI-Detektortest offen. |
| AC-14 | confirmation unterscheidet Beobachtung, Eingang und Abschluss | Teilweise: aktuell unverified. Erkennung der beiden offiziellen Phasen offen. |
| AC-15 | Journalfehler und ursprünglicher Ausgang bleiben nachvollziehbar | Abgedeckt: `test_journal_update_failure_preserves_prior_outcome_and_durable_guard`, zwei Fehlerfälle. Keine privaten Fehlermeldungen im Bericht. |
| AC-16 | Bestehende SUCCESS/FAILED-Endzustände bleiben stabil | Allgemeines Journalmodell abgedeckt: `test_recovery_resolves_terminal_outcomes_without_booking` und stale-Recovery-Test. |
| AC-17 | Erneuter Lauf nach unklarem Ausgang erzeugt keinen Zweitklick | Abgedeckt für denselben lokalen Journalpfad; kein Nachweis getrennter Hosts. |
| AC-18 | Wiederholte Recovery ohne neuen Beleg bleibt gesperrt | Abgedeckt: drei weitere Runner-Aufrufe mit gleicher Vorgangs-ID und ohne neuen Klick. Ein späterer autoritativer Abschluss darf den Status ändern. |
| AC-19 | Eindeutig erkannte unabhängige LIDL-Vorgänge blockieren ALDI nicht | Abgedeckt: `test_known_lidl_unknown_does_not_block_independent_aldi_refill`. Unbekannte Provider/Aliase bleiben absichtlich gesperrt; keine pauschale Freigabe aller fremden Datensätze. |
| AC-20 | Ungelöster Vorgang desselben Anschlusses blockiert neuen Vorgang | Abgedeckt für getestete Normalformen und bekannte Aliase. Unklare Zuordnung bleibt gesperrt. |

Runnernachweise stehen in `tests/test_aldi_live_refill.py`, Hosted-Recovery in
`tests/test_hardening_v4.py`, allgemeine Journalnachweise in
`tests/test_recharge_safety.py`. Testbezeichnungen beschreiben Simulationen,
keine realen Providerbelege.

## Noch erforderliche Betriebsnachweise

| ID | Nachweis | Stand |
| --- | --- | --- |
| GO-01 | Offizielle Abschlussquelle technisch identifiziert; Eingang und Abschluss getrennt | Offen |
| GO-02 | Nachweis gehört zu SIM, Gratisangebot und konkretem Vorgang; Altbelege ausgeschlossen | Offen |
| GO-03 | Positiver SUCCESS-Pfad mit repräsentativen Belegen implementiert und getestet | Offen |
| GO-04 | Wiederaufnahme nach Abbruch über dieselbe Quelle ohne zweiten Buchungsklick | Offen |
| GO-05 | Dauerhafter Host, Journal, Mailzuordnung, sichere Konfiguration und vollständiger realer Mail-bis-Abschluss-Lauf nachgewiesen | Offen für diese Abnahme |

GO-01/02 allein machen den Watcher nicht eingeschränkt betriebsbereit.
Eine Zusammenführung der Sicherheitskorrektur ist von einer Aktivierung zu
unterscheiden. Betriebsfreigabe erfordert GO-01 bis GO-05 sowie bestandene
relevante Kriterien; die aktuelle Matrix vergibt sie nicht.

## Nächster technischer Schritt: gezielte Beobachtung

Vor zusätzlicher Instrumentierung ist zu prüfen, ob bereits vorhandene
sanitisierte Diagnosen die benötigte Struktur liefern. Der vorhandene
`aldi_frontend_submit_probe.py` beobachtet die Anmeldung; er ist kein validierter
Buchungsabschlussdetektor.

Für einen ohnehin autorisierten beobachteten Vorgang sind Ausgangszustand,
neu auftretender Bestelleingang und späterer offizieller Abschluss getrennt zu
erfassen. Eine Vorgangs-ID ist eine mögliche Bindung, aber kein zwingend
vorgeschriebenes Portalmerkmal. Andere Bindungen müssen ihre Eindeutigkeit und
Wiederherstellbarkeit ebenfalls nachweisen.

Keine unbeschränkten HTML-, URL-, Header- oder Antwortkörper-Dumps in normale
Reports oder öffentliche CI-Artefakte übernehmen. Nur explizit ausgewählte
Strukturmerkmale, Statusklassen und redigierte Referenzen persistieren; keine
Passwörter, Cookies, Tokens oder unnötigen Kontodaten. Beobachtung allein
ändert keinen Journalstatus auf SUCCESS und erzeugt keine zusätzlichen
Buchungsklicks. Ohne tatsächlich beobachtete Quelle keine Selektoren oder
Statusendpunkte erfinden.
