# Betriebsprüfung 14.10.2026

Geprüfter main-Commit: `484aafd32dd8bfde54d97512fa9200e04a633e3f`.

## Belegte Befunde

- `47c0b9f` deaktivierte den Account-Monitor am 13.10.2026 und nennt einen
  Anbieterhinweis. Öffentliche Grundlage: ALDI-TALK-Leistungsbeschreibung & AGB,
  Ziffer 10.3 g, PDF-Seite 16, abgerufen 14.10.2026:
  https://media.medion.com/cms/medion/alditalkde/ALDI-TALK-Leistungsbeschreibung.pdf
  Die Klausel betrifft Zugriffe über nicht autorisierte Software einschließlich
  Automatisierungssoftware. Eine konkrete Automationsfreigabe liegt nicht vor.
- Run 38568574294: öffentliche Probe erfolgreich, kein Login/keine Buchung.
- Run 38565976011: Mail-Monitor fehlgeschlagen, `no_mailboxes_configured`.
- `usage_mail_notify.py` startet keinen Portalzugriff. Eine vollständige
  Mailkonfiguration würde deshalb allein noch keine Nachbuchung ermöglichen.
- `core/aldi_refill.py::_free_offer_evidence` akzeptiert bereits die verifizierte
  Gratis-Tarifberechtigung ohne explizite Nullpreis-Anzeige.
- `aldi_live_refill.py` setzt SUCCESS anhand des Volumenzuwachses. Dieser
  Indikator ist kein offizieller, vorgangsgebundener Buchungsbeleg.
- README und booking-readiness enthielten überholte Aktivierungsangaben.

## Umsetzungsreihenfolge

1. IMAP-Secrets für mindestens ein eindeutig zugeordnetes Postfach plus
   ALDI_RECOVERY_KEY im Secret Store bereitstellen. Werte nicht im Chat oder
   Repository veröffentlichen. Vorhandensein ist über den aktuellen Connector
   nicht direkt auslesbar; der bestehende Run belegt nur seine Laufzeitkonfiguration.
2. Mail-Monitor separat prüfen; keine automatische SIM-Zuordnung aus bloßem
   Postfachindex ableiten. Noch keine Buchung durch Mail-Eingang.
3. Einen vom Anbieter freigegebenen Automationsweg klären. Keine erfundene
   API und keine Reaktivierung allein aufgrund vorhandener Zugangsdaten.
4. Auf diesem Weg Login, ausgewählte SIM, aktiven Tarif und Gratisangebot
   nachweisen. Für diesen einmaligen Test wäre keine Verbrauchsmail nötig.
5. Offizielle Buchungsbestätigung im echten Konto beobachten und erst danach
   deren Erkennung implementieren. Unbekannte Selektoren oder Statusendpunkte
   nicht raten. Volumenzuwachs allein darf die Abnahme nicht bestehen.
6. Persistentes Journal, Ausschluss paralleler Buchungen und Abgleich unklarer
   Vorgänge prüfen. Erst danach einen echten Einzellauf und Dauerbetrieb abnehmen.

## Grenzen dieser Änderung

Nur Dokumentationskorrektur. Keine Zugangsdaten geändert, kein Login ausgelöst,
keine Buchung durchgeführt, kein dauerhafter Buchungsbetrieb aktiviert.

## Run-Quellen

- https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38568574294
- https://github.com/chhubeny90-cell/aldi-watcher/actions/runs/38565976011
