# ALDI TALK Refill – Betriebs- und Alternativpfadplan (2026-10-14)

## Ziel und Definition of Done
Automatische Erkennung des verbrauchten ALDI-TALK-Unlimited-Datenvolumens, genau eine zulässige kostenlose 1-GB-Nachbuchung je eindeutig bestätigtem Bedarf, belastbarer Erfolgsnachweis und 24/7-Betrieb. Keine kostenpflichtige Buchung, keine Umgehung von Login-Sperren oder Schutzmechanismen. 99,99 % ist ein Qualitätsziel, **keine belegte Verfügbarkeit**; Messung erst nach mehrwöchigem Betrieb möglich.

## Verbindliche Knotenpunkte (alle Pfade führen hier zusammen)
K0: Trigger: eindeutige ALDI-Verbrauchsmail oder autorisierte Konto-Statusmeldung.
K1: Normalisierung: Rufnummer-/Tarifzuordnung, Mail-ID, Zeitstempel, Deduplizierung und persistentes Journal.
K2: Autorisierte Kontoanmeldung; Kundenkonto und aktueller Tarif tatsächlich geladen.
K3: Ein einzelnes dem aktiven Unlimited-Tarif zugeordnetes kostenloses 1-GB-Angebot eindeutig identifiziert; positive/unklare Preise gesperrt.
K4: Einmaliger Buchungsversuch mit idempotentem Transaktionsschlüssel und persistiertem PENDING.
K5: Offizielle, zum Versuch gehörende Buchungsbestätigung; sonst UNKNOWN und **kein automatischer Retry**.
K6: Benachrichtigung, revisionsfähiger Status, nächste Überwachung.

## Pfad A – Bevorzugt: freigegebene Anbieter-Schnittstelle
ALDI TALK nach dokumentierter/ausdrücklich autorisierter Schnittstelle für Kontostatus und Gratis-Nachbuchung fragen. Bei Freigabe Adapter implementieren, Testkonto/Staging prüfen und K0→K6 nutzen. Ohne Freigabe nicht aktivieren.

## Pfad B – Autorisierter Web-Kontoweg
Nur falls vom Anbieter erlaubt und Konto entsperrt: Anmeldung, Tarif und Angebot durch echten Kontoflow nachweisen; keine Captcha-, MFA- oder Account-Lock-Umgehung. Bei Loginproblemen zu Pfad D wechseln, niemals wiederholte aggressive Versuche.

## Pfad C – Ein-Klick-Freigabe
Bei K0/K1 einen einmalig verwendbaren Link zum offiziellen ALDI-Kundenkonto bereitstellen. Nutzer bestätigt die kostenlose Buchung selbst. Anschließend Status anhand autorisierter Kontoauskunft oder offizieller Buchungsbestätigung abgleichen. **Nicht als vollautomatische Buchung ausgeben.**

## Pfad D – Sicherer Monitoring-Fallback
Mail-Monitor alle fünf Minuten, Warnung bei 80 %, Refill-Bereitschaft bei Verbrauch; deduplizierte Benachrichtigung mit Kontolink. Kein Portal-Login, keine Buchung, kein Kostenrisiko. Bei Mail- oder State-Fehler sichtbarer Fehlerstatus.

## Pfad E – Lokaler autorisierter Runner
Wenn GitHub-Runner wegen Session-/Gerätebindung nicht funktioniert: lokale Ausführung auf eigenem Gerät, gleiche K0–K6-Schnittstellen, sichere Secret-Verwaltung, Watchdog und Journalsynchronisierung. Nur autorisierte Kontozugriffe; nicht als Umgehung von Provider-Sperren einsetzen.

## Umsetzung in Abhängigkeiten
1. [x] Test-Regression für umbenannten Mail-Monitor-Schritt auf Arbeitsbranch korrigieren.
2. [ ] CI auf Branch prüfen, weitere Testfehler beheben, PR reviewen/mergen.
3. [ ] Secrets **nur durch Berechtigten in GitHub** hinterlegen: MAILBOX_1_HOST/USER/PASS, optional zweites Postfach, ALDI_RECOVERY_KEY. Nie Zugangsdaten in Issues/Logs/Chat.
4. [ ] Mail-Monitor manuell auslösen und echten Mailabruf, Deduplizierung, persistentes State-Journal, Fehlermeldung verifizieren.
5. [ ] Ein-Klick-Link Ende-zu-Ende mit Testereignis validieren; keine falschen Erfolgsmeldungen.
6. [ ] ALDI-Sperrstatus/Anbietergenehmigung klären; autorisierten Login ohne Buchung prüfen (K2).
7. [ ] Tarif, Restvolumen und Gratisangebot mit echter Kontoanzeige validieren (K3).
8. [ ] Ausführung K4 ausschließlich nach Genehmigung, eindeutiger Gratisoption und bestätigter Live-Abnahme.
9. [ ] K5: offizielle Buchungsbestätigung statt bloßer Volumenzunahme; UNKNOWN/PENDING über Neustarts sperren und manuell abgleichen.
10. [ ] Fehlersimulation: IMAP-Ausfall, Duplikate, Race Condition, Konto gesperrt, Tarifwechsel, Preis unklar, Netzwerk-Timeout nach Klick, Wiederanlauf.
11. [ ] Betriebsmetriken: Erkennungszeit, Benachrichtigungszeit, Erfolgsquote, Fehlalarmquote, Duplikate, unbekannte Buchungszustände.
12. [ ] Mehrwöchiger Soak-Test; erst danach SLO wie 99,99 % nach Messdaten beurteilen.

## Freigabematrix
- Monitoring/Benachrichtigung: zulässig konfigurierbar, unabhängig vom Live-Login.
- Ein-Klick-Link: führt zum offiziellen Anbieter; Buchung erfolgt durch Nutzer.
- Vollautomatisches Refill: **gesperrt**, bis Provider-Autorisierung, echter Kontozugang, eindeutiges Gratisangebot und offizieller Erfolgsnachweis vorliegen.
- Bei UNKNOWN/PENDING, Konto gesperrt, unklarem Preis oder unklarem Tarif: keine Wiederholung und keine kostenpflichtige Ausweichbuchung.

## Kommunikationsknoten
- K0/K1: „Verbrauch erkannt / bereits verarbeitet / Postfachfehler“
- K2: „Login erfolgreich / gesperrt / Schutzprüfung erforderlich“
- K3: „Gratis-1-GB bestätigt / unklar / nicht verfügbar“
- K4/K5: „Buchung eingeleitet / bestätigt / UNKNOWN – keine Wiederholung“
- K6: „Status, Zeit, Handlungsbedarf und nächster zulässiger Pfad“
