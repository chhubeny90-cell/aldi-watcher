# Betriebsabnahme und Triage — 2026-11-24

Basis: [5e45253](https://github.com/chhubeny90-cell/aldi-watcher/commit/5e4525331384e2da53dce0d5dbdb59a30ad13035).
Keine Livebuchung, kein Secret-Zugriff, keine neue Anbieteranmeldung.

## Belegte Ergebnisse am Basis-Commit

- [Test-CI](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/45183438883): 1874 bestanden, 1 Skip, 12 Subtests.
- [Python-Kompatibilität](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/45183438882) und [CodeQL](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/45211507467): success.
- [ALDI-Mailmonitor](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/45335478363): 0 konfigurierte Postfächer, dedup_key_configured=true, no_mailboxes_configured. MAILBOX_2_USER/PASS/HOST für den Lauf nicht verfügbar. Keine Aussage über den Inhalt oder die Existenz gespeicherter Secrets außerhalb dieses Laufs.
- [Lidl-Beobachtung](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/45183438947): configuration_missing (LIDL_EXPECTED_MSISDN, LIDL_ACCOUNT_SELECTOR, LIDL_REMAINING_SELECTOR, LIDL_ACTIVE_TARIFF_SELECTOR). Kein Konto- oder Volumennachweis.
- [Lidl-Folgelauf](https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/45306778555): Installation abgebrochen, keine Beobachtung.

## 6 offene Issues — Abnahmebedingungen

| Issue | Status / nächste Aktion |
|---|---|
| #116 | BLOCKED: Mailkonfiguration reparieren; private Laufzeit und Anbieterfreigabe nachweisen. |
| #125 | BLOCKED: Mail ist nur Prüfsignal; SIM, Angebot, Journal und Anbieterabschluss separat belegen. |
| #126 | Separate KI-Box, nicht Kernumfang; Kostenfreiheit und geschützte Umgebung vor jeder externen Ausführung nachweisen. |
| #133 | BLOCKED: aktuelle authentifizierte Ziel-SIM und exaktes kostenloses Einzelangebot nachweisen. |
| #149 | BLOCKED: Vorgangsbezogene offizielle Abschlussbestätigung und Reconciliation fehlen. |
| #150 | Hilfsanfrage zu #149; erst nach tatsächlicher Klärung schließen. |

## 35 offene PRs — Triage nach Zweck (keine Merge-Freigabe)

| Gruppe | PRs | Disposition |
|---|---|---|
| Lidl-Kernfunktion | #158 | Prioritär auf aktuellem main prüfen: strikte <1024 MB, persistente Sitzung, Polling, Journal. Live-Abnahme separat. |
| Mail und Betrieb | #124, #132, #122, #148, #11 | Gegen aktuelles main auf Überschneidungen und fehlende Regressionen prüfen; keine parallelen Aktoren. |
| Buchungssicherheit | #155, #154, #145, #130, #121, #120, #119, #117, #114, #107, #108, #20, #19, #15 | Bestehende Schutzmechanismen vergleichen und nur fehlende, getestete Teile übernehmen; alte Zweige nicht blind mergen. |
| ALDI-Portalpfade | #156, #45, #26, #10 | Automatisierung gemäß SECURITY.md deaktiviert; keine Reaktivierung ohne Anbieterfreigabe und Nachweis. |
| KI-Box / Erweiterungen | #157, #131, #123 | Vom Kernabschluss trennen; NettoKOM offline, KI-Box getrennt. |
| Abhängigkeiten / CI | #160, #63, #62, #61, #60, #59, #57, #55 | Gegen aktuelle Versionen und exakte Head-CI prüfen; alte oder doppelte Änderungen nicht ohne Vergleich schließen. |

Diese Gruppierung ist eine Inventur, keine zeilenweise Diff-Abnahme. Kein PR wird allein wegen seines Alters geschlossen.

## Reihenfolge für echte Abnahme

1. ALDI: vorhandenen Deduplizierungsschlüssel erhalten, MAILBOX_2_USER/PASS als Actions-Secrets sicher bereitstellen; Host nur passend zum Postfach konfigurieren. Manuellen Mailmonitor mit connection_only=true ausführen. Anschließend regulären passiven Lauf mit erfolgreichem IMAP-Abruf belegen.
2. Lidl: fehlende Werte aus einem tatsächlich beobachteten, manuell angemeldeten Zielkonto erheben; keine Selektoren raten. Nur bereinigte Werte/Status, keine Rufnummer im Repo. Vorprüfung, dann authentifizierte Beobachtung mit Zeitstempel und account_verified=true.
3. PR #158 separat gegen aktuellen main testen und prüfen. Keine bezahlten Angebote; vor Buchung exakte SIM, aktuelles Restvolumen strikt unter 1024 MB, einzelnes 1-GB-Angebot zu 0 Euro und atomare dauerhafte Reservierung.
4. Einen zulässigen, dauerhaften Host und persistenten privaten Journalpfad belegen; UNKNOWN/PENDING verhindern Wiederholungen. Providerbestätigung muss dem konkreten Vorgang zugeordnet sein.
5. Erst nach Anbieterfreigabe und nachgewiesener Beobachtung einen gesonderten Live-Abnahmelauf erwägen. ALDI bleibt gemäß SECURITY.md manuell. Keine bezahlte Aktion.
6. Erst dann Betriebsstatus READY vergeben und erfüllte Issues schließen.

## Änderung dieses PRs

Lidl-Vorprüfung ohne Browser vor Chromium-Installation. Fehlende Konfiguration
bleibt rot (Exit 2); vorhandene Konfiguration ist ausdrücklich keine Beobachtung.
Neue Offline-Regressionsfälle. Testergebnis dieses neuen Heads erst nach CI
feststellen; die obigen 1874 Tests gehören ausschließlich zum Basis-Commit.
