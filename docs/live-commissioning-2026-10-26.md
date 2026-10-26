# Live-Inbetriebnahme – 26. Oktober 2026

Gesamtstatus zum Zeitpunkt dieser Dokumentation: **nicht betriebsbereit**.
Konfiguration, historische Nachweise und aktuelle Aktionen werden getrennt bewertet.

## Tatsächlich beobachtet

- Der lesende Login vom 25.10.2026 war erfolgreich: passendes Konto und eine
  geschützte Subscription wurden bestätigt. Tarif, Restvolumen und Buchung
  waren nicht Teil dieses Nachweises:
  https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40241870678
- Ein frischer Chrome-Lauf vom 26.10.2026 hat die offizielle ALDI-Anmeldeseite
  geöffnet. Das ist öffentlicher Browserzugriff ohne Passwortübermittlung und
  kein aktueller authentifizierter Statusnachweis:
  https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40270069325
- Über die verbundenen Gmail-Konten wurden echte Warnungen und wiederholte
  Verbrauchsmeldungen untersucht. Warnung und vollständiger Verbrauch verwenden
  denselben Betreff. Die betrachteten Verbrauchsmails enthalten keine belastbare
  SIM- oder Anbieter-Vorgangskennung. Allgemeine Optionsbestätigungen belegen
  keine kostenlose 1-GB-Nachbuchung. Es wurden keine Nachrichten geändert und
  keine enthaltenen Aktionslinks geöffnet.
- Der öffentliche Authentifizierungszustand enthielt beim lesenden Abruf keine
  offenen Vorgänge und eine Sperrfrist bis 26.10.2026, 22:48:21 UTC. Das beweist
  keine vollständige private Buchungshistorie. Es wurde keine Sperre gelöscht.
- Der letzte untersuchte Mailmonitor-Lauf war wegen fehlendem Deduplizierungs-
  schlüssel blockiert. Er beweist keine gültige IMAP-Anmeldung:
  https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/40251018433
- Die GitHub-Verbindung erhält HTTP 403 für Secrets, Repository-Variablen und
  die Liste privater Runner. Es wurden keine Secretwerte ausgelesen.

## Technische Fertigstellung

PR #115 wurde nach unabhängiger Prüfung und 150 bestandenen, einschlägigen
Offline-Tests auf aktuellem Main übernommen. Ein beschriftetes Prepaid-Guthaben
ist kein Refillpreis; kostenpflichtige, unlesbare und mehrdeutige Angebote bleiben
gesperrt. Andere alte Entwürfe werden nicht pauschal als Live-Fortschritt gemergt.

Die anschließenden Änderungen verbinden den vorhandenen gehosteten Ablauf mit
der vollständigen Zielprüfung, maskieren die Zielkonfiguration und korrigieren
das nachgewiesene internationale Cookie-Format in der Browser-Kontoprüfung.
Jeder echte Buchungs- und Bestätigungsklick verlangt ausdrücklich numerisch
belegten Nullpreis; Tarif-/Vertragsänderungen und Folgekosten bleiben gesperrt.

Der Mailmonitor erkennt Warnungen, Verbrauch, eingegangene Bestellungen,
allgemeine Optionsbestätigungen und ausdrücklich kostenlose Refill-Bestätigungen
getrennt. Ein dauerhafter UID-Fortschritt verarbeitet auch gelesene Nachrichten
und Rückstände; ein UIDVALIDITY-Wechsel verwirft die Nachrichtenhistorie nicht.
Mailbenachrichtigungen lösen nur eine frische authentifizierte Kontoprüfung aus.
Sie ersetzen weder Preis-/SIM-Nachweis noch den operationgebundenen Anbieterbeleg.

## Betriebsumgebung und offene Hindernisse

GitHub-gehostete Standard-Linux-Jobs sind für dieses öffentliche Repository die
vorhandene Lösung ohne eingerichteten kostenpflichtigen Dienst. Vorgesehen sind
eine stündliche Prüfung und zusätzliche Prüfungen nach erfolgreichem Mailmonitor.
Jeder Job stellt den geschützten Zustand wieder her. Es läuft kein dauerhafter
Browserprozess; GitHub kann Zeitpläne verzögern oder auslassen. Diese Umgebung
wird nicht als garantiert lückenloser Dauerbetrieb bezeichnet.

Die Work-Cloud-Sitzung ist eine Bearbeitungsumgebung und kein nachgewiesener
Dauerhost. Ein Windows-Gerät ist nicht angebunden; eine Aufgabenplanung wurde
dort nicht installiert. Private Runner können mit der aktuellen Berechtigung
nicht als vorhanden oder eingerichtet bestätigt werden.

Für den aktiven gehosteten Pfad sind `ALDI_STATE_ENCRYPTION_KEY` und das maskierte
Secret `ALDI_REQUIRED_TARGET_SUFFIX` zu prüfen beziehungsweise einzurichten.
Der Schlüssel wird unabhängig vom Anbieterpasswort erzeugt. Ein vorhandener
Mail-Deduplizierungsschlüssel bleibt erhalten; ansonsten wird aus dem separaten
Speicherschlüssel ein eigener, stabiler Mail-Schlüssel abgeleitet.

Die bestehenden Rufnummer-/Passwort-Secrets und ein konfiguriertes Mailkonto
sind allein noch kein Funktionsnachweis. Die erneuten Vorprüfungen müssen die
Konfiguration und die IMAP-Verbindung bestätigen. Ohne Deduplizierungsschlüssel
ist nur ein lesender Verbindungscheck erlaubt, keine Nachrichtenverarbeitung.

Eine aktuelle authentifizierte Tarif-/Volumenprüfung, die erste tatsächliche
0,00-Euro-Buchung samt Anbieterbeleg sowie ein echter Wiederanlauf der gespeicherten
Sitzung sind **noch nicht nachgewiesen**. Ungeklärte Buchungsvorgänge bleiben
gesperrt. Fehlende historische Daten werden nicht durch eine leere Historie ersetzt.

Nachweise der verbleibenden Live-Schritte werden nur nach realer Durchführung
ergänzt. Offline-Tests und erfolgreiche reine Vorprüfungen gelten nicht als
Live-Buchungs- oder Dauerbetriebsnachweis.
