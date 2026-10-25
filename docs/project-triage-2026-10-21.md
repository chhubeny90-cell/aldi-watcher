# Watcher-Arbeitsregister

Stand: 25.10.2026. Geprüfter Main: `27d46e90c6ec8d640f2c75cc3abfb3af865b4e7a`.
Dieses Register ordnet vorhandene Arbeit. Es aktiviert keinen Dienst und bestätigt keine Live-Betriebsbereitschaft.
24 offene PRs wurden über GitHub erfasst; ihre CI, Diffs und Reviews wurden für dieses Register nicht vollständig neu geprüft.

## 1. Klare Aufteilung

| Bereich | Zuständiger Einstieg | Ergebnis / Grenze |
| --- | --- | --- |
| Mailtransport und lokaler Betrieb | [PR #124](https://github.com/chhubeny90-cell/aldi-watcher/pull/124) | UID-Sensor, Neustart und Windows-Vorbereitung; kein Nachweis für laufenden Dienst |
| Nachrichtenduplikate und Verbrauchskandidaten | [PR #132](https://github.com/chhubeny90-cell/aldi-watcher/pull/132) | Nachrichten von Vorgangskandidaten trennen; kein authentifizierter Zyklusprüfer |
| ALDI-Buchung und Journal | [PR #121](https://github.com/chhubeny90-cell/aldi-watcher/pull/121) | Integrationskandidat für Sicherheitsarbeit; gegen kleinere PRs abgleichen |
| Offline-Abnahme | [PR #130](https://github.com/chhubeny90-cell/aldi-watcher/pull/130) | Simulation; kein Live-Nachweis |
| LIDL | [PR #137](https://github.com/chhubeny90-cell/aldi-watcher/pull/137) | Lesender Readiness-Helper; unabhängig von ALDI-Mailtriggern |
| GitHub Actions | [PR #122](https://github.com/chhubeny90-cell/aldi-watcher/pull/122) | Workflow-Effizienz; separat von Providerfehlern prüfen |
| KI-Auftragsbox | [PR #123](https://github.com/chhubeny90-cell/aldi-watcher/pull/123) | Eigenständiger Kommunikationsstrang, keine Buchungsfreigabe |
| Übersicht und Dokumentation | [PR #131](https://github.com/chhubeny90-cell/aldi-watcher/pull/131) | Dieses Register; keine zusätzliche parallele Aufräum-PR |

## 2. Was im geprüften Main und was nur im Entwurf liegt

Im Main sind `usage_mail_notify.py`, `core/mail_handoff_queue.py`,
`mail_actor_preflight.py` und die gesperrte Mailübergabe in `github_live_refill.py` vorhanden.
Die Mailqueue behandelt einzelne Nachrichten. Sie ist kein Beweis für einen neuen Verbrauchszyklus.

In PR #132, geprüft auf `6320754be5cff6ed4e1f81655cb51391dca91ce2`,
liegt zusätzlich `core/mail_cycle_guard.py`:
- Ein explizit konfiguriertes Profil erhält höchstens einen offenen UNVERIFIED-Kandidaten.
- Neue Message-IDs und verstrichene Zeit geben keinen weiteren Kandidaten frei.
- UNKNOWN wird nicht automatisch aufgehoben.
- `reserve_verified_provider_cycle` lehnt alle Aufrufe ab.
- Ein Profilname ist keine authentifizierte SIM-Identität.
- Queue und Kandidatenregister liegen in getrennten Dateien; Teilwrites benötigen Abgleich.

Diese Funktionen sind Entwurfsstand und dürfen nicht als produktiv integrierte Zykluserkennung beschrieben werden.

## 3. Mailbefund vom 24./25.10.2026

Lesend geprüft: sieben Nachrichten in einem Thread, sieben unterschiedliche Gmail-IDs
und RFC-Message-IDs, identischer HTML-Inhalt, SPF/DKIM/DMARC jeweils bestanden.
Keine konkrete SIM, Option oder eindeutige Verbrauchsvorgangs-ID im Text.
Private Adressen, Namen, Nachrichten-IDs und Mailtexte werden hier nicht veröffentlicht.

| Date-Header UTC | Europe/Berlin |
| --- | --- |
| 24.10.2026 13:37:25 | 24.10.2026 15:37:25 |
| 24.10.2026 17:07:22 | 24.10.2026 19:07:22 |
| 24.10.2026 18:18:43 | 24.10.2026 20:18:43 |
| 24.10.2026 21:06:20 | 24.10.2026 23:06:20 |
| 24.10.2026 21:43:46 | 24.10.2026 23:43:46 |
| 25.10.2026 07:18:25 | 25.10.2026 08:18:25 |
| 25.10.2026 09:19:10 | 25.10.2026 10:19:10 |

Ergebnis: sieben eigenständige Mails, aber keine sieben nachgewiesenen Verbrauchsvorgänge.
Die erste Mail ist nur der früheste Hinweis dieses Threads. Auch sie beweist keinen neuen Zyklus.
Weitere Mails bleiben Hinweise zu einem ungeklärten Kandidaten; dass tatsächlich nur
ein Verbrauchsvorgang stattgefunden hat, ist ebenfalls nicht bewiesen.
Zwischenzeitliche Nachbuchungen sind durch diesen Thread weder bestätigt noch ausgeschlossen.

## 4. Zielvertrag für Mail und Buchung

| Eingang / Zustand | Zulässige Verarbeitung |
| --- | --- |
| Bereits gespeicherte Nachricht | Kein zweites Ereignis erzeugen |
| Neue 80-%-Warnung | Warnung; keine Buchung |
| Neue Verbrauchsmail | Nachricht speichern, lesende Prüfung vormerken |
| Mehrere mögliche SIMs | Keine automatische Auswahl allein aus Mailadresse oder Anrede |
| Ungeklärter Kandidat vorhanden | Weitere Hinweise zuordnen, keinen neuen Buchungsauftrag ableiten |
| Authentifiziert neues Kontingent und spätere Erschöpfung | Neuen Verbrauchszyklus prüfen |
| Buchung PENDING oder UNKNOWN | Keine erneute Buchung; offiziellen Vorgangsstatus abgleichen |
| Preis, Angebot, Tarif oder Identität unklar | Buchung blockieren |

Nachrichtenschlüssel und Zyklusschlüssel bleiben getrennt. Zeitstempel in UTC speichern,
lokal mit Europe/Berlin anzeigen. Kein Tagesreset und keine zeitbasierte Freigabe.
Thread-ID, gleicher Text und neue Message-ID reichen nicht zur Zyklusentscheidung.

Wichtig: Ein beobachteter Volumenzuwachs kann einen Kontingentwechsel unterstützen,
beendet aber keinen ungeklärten Buchungsauftrag. Das vorhandene Journal verlangt
einen offiziellen, vorgangsgebundenen Abschlussnachweis. Diese stärkere Bedingung bleibt bestehen.
Ein lokaler Einmal-Auftrag garantiert ohne Provider-Abgleich keine genau einmalige externe Buchung.

## 5. Reihenfolge der Weiterarbeit

1. **PR #132 zuerst fachlich abgleichen:** Nachrichtendedupe, Profilkandidat und Providerzyklus
   eindeutig benennen; sieben neue Zeitpunkte als synthetische Regression ergänzen.
   Offene Punkte: authentifizierte SIM-/Kontingentbindung und Abgleich von Queue/Journal/Kandidatenregister.
2. **PR #124 anbinden:** UID-Zustand, Wiederanlauf und dauerhafte Speicherung gegen denselben
   Vertrag prüfen. Keine Task-Registrierung allein aufgrund grüner Offline-Tests.
3. **Journal-/Preisarbeit zusammenführen:** #121 mit #114, #115, #117 und #120 vergleichen.
   Überlappung ist noch kein belegtes Duplikat; kleinere PRs erst nach Diff-Nachweis schließen.
4. **Gezielte Offline-Abnahme:** Neustart, parallele Verarbeitung, Teilwrites, verspätete Mails,
   gleiche Inhalte in echten Folgezyklen und UNKNOWN testen. #130 als vorhandenen Einstieg nutzen.
5. **Danach Betriebsnachweise:** tatsächliche Laufzeitkonfiguration, authentifiziertes Konto,
   konkretes Gratisangebot und offizieller Abschlussvertrag. Bis dahin keine Mail-Aktorfreigabe.

## 6. Alle offenen PRs zugeordnet

| PRs | Bereich | Behandlung |
| --- | --- | --- |
| #132, #124 | Mail und lokaler Betrieb | Priorisierte gemeinsame Schnittstelle |
| #121, #120, #117, #115, #114 | Preis, Journal und Recovery | Überlappungen anhand Diffs prüfen |
| #119, #45, #26, #10 | Login und Diagnose | Historische Ansätze gegen Main prüfen; keine zusätzlichen Loginversuche ableiten |
| #20, #15, #13 | Ältere Buchungs-/Sicherheitsansätze | Übernahme in Main nachweisen, dann erst über Schließen entscheiden |
| #11, #19 | Alternative Runner-/Betriebswege | Mit #124 und Main abgleichen; keinen zweiten Dauerbetrieb etablieren |
| #130, #108, #107 | Tests und Abnahmestatus | Ergebnisse nur dem tatsächlich geprüften Commit zuordnen |
| #122, #55 | CI/Actions/CodeQL | Workflowänderungen getrennt prüfen |
| #137 | LIDL | Eigenständiger lesender Helper; keine ALDI-Abhängigkeit erfinden |
| #123 | KI-Auftragsbox | Separater Projektstrang |
| #131 | Dokumentation | Führendes Aufräumregister |

Die Gruppierung enthält alle 24 beim Abruf offenen PRs. Sie ist keine Merge-Empfehlung.
Kein PR wurde in dieser Sortierung geschlossen, gemergt oder als fertig bewertet.

## 7. Dokumentation und Statusregeln

Die README beginnt mit einem Prüfstand vom 17.10.2026. Dieser darf nicht als neuer
Live-Befund vom 25.10. ausgegeben werden. Eine spätere README-Kürzung muss historische
Betriebsberichte erhalten und aktuelle Aussagen an überprüfbare Laufquellen binden.

- BLOCKED: notwendiger Nachweis fehlt.
- OFFLINE_VERIFIED: benannte Tests für einen konkreten Commit bestanden.
- LIVE_READY: alle notwendigen Live-Gates belegt, noch kein Buchungserfolg.
- LIVE_VERIFIED: konkrete Anbieteraktion mit offiziellem vorgangsbezogenem Beleg.

Kommentare nur nach Prüfung des jeweiligen Threads beantworten; keine automatischen
Sammelantworten. Keine Review-Threads ohne Prüfung auflösen. Keine persönlichen
Mailinhalte, Zugangsdaten, Rufnummern oder Tokens veröffentlichen.

## Änderung dieser Fassung

Vorhandenes Register aktualisiert: 24 PRs geordnet, Main und Entwurf getrennt,
Mailbefund vom 24./25.10. datensparsam eingeordnet und konkrete Bearbeitungsreihenfolge festgelegt.
Nur Dokumentation geändert. Keine Produktionslogik, Secrets, Workflows oder Dienste geändert.
