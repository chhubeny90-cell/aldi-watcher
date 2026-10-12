# ALDI TALK: belegte kostenlose 1-GB-Nachbuchung (Stand 2026-10-12)

## Verifizierte Anbieterinformationen

ALDI TALK beschreibt für die Tarifoptionen S, M und L die kostenlose 1-GB-Nachbuchung bei einem verbleibenden Datenvolumen unter 1 GB. Das Angebot kann wiederholt genutzt werden. Die offizielle Beschreibung nennt ausdrücklich die **ALDI TALK App** als Buchungsweg.

- https://www.alditalk.de/tarife-unlimited-gb-nachbuchen
- https://www.alditalk.de/tarif-s
- https://www.alditalk.de/tarif-m
- https://www.alditalk.de/tarif-l

Die Tarifgebühr (9,99/14,99/19,99 EUR je vier Wochen, je nach Tarif) ist **nicht** der Preis der einzelnen kostenlosen Nachbuchung. Das Wort „kostenlos“ oder eine „0,00 €“-Anzeige muss nicht auf jeder Nachbuchungsschaltfläche stehen.

## Sicherheitsentscheidung im Code

`core/aldi_refill.py` kann bei nachgewiesenem aktivem Tarif und eindeutig lokal zugeordneter **Unlimited-/On-Demand-1-GB-Nachbuchung** die offiziellen Tarifbedingungen als Kostenfrei-Nachweis verwenden. Ohne Preisangabe bleibt ein generisches 1-GB-Angebot gesperrt. Positive Preise, mehrere Schaltflächen, falsche Tarife, unklare Sitzung, Restvolumen ab 1 GB und deaktivierte Buttons bleiben gesperrt. Die Erkennung ist ein rein lokaler Test der Berechtigung; sie klickt nicht.

## Offene Freigaben für den Start

1. **Schriftliche Autorisierung** von E-Plus Service GmbH für den geplanten automatisierten Portal-/App-Zugriff; eine Anfrage wurde gestellt, eine Antwort steht aus. Der Anbieter nennt die App als regulären Buchungsweg; ein browserbasiertes Portal ist nicht automatisch gleichwertig.
2. **Realer Konto-Nachweis**: korrekte aktive Tarifoption, Sitzung, konkretes Refill-Angebot, genau ein freigeschalteter 1-GB-Button und kein kostenpflichtiges Angebot.
3. **Eindeutige Buchungs-Reconciliation**: ein Providerbeleg oder eine dokumentierte offizielle Statusabfrage, die genau den gestarteten Vorgang als SUCCESS/FAILED/UNKNOWN identifiziert. Volumenzunahme oder ein allgemeiner Toast reichen nicht.
4. **Dauerhaftes Journal und Runner** sowie geprüfter Wiederanlauf ohne Doppelbuchung, belastbares Monitoring und Benachrichtigung.
5. **Erst dann** kann ein kontrollierter manueller Einmallauf freigegeben werden. Bis dahin bleibt `ALDI_RECONCILIATION_VERIFIED = False` unverändert; GitHub Actions startet keine Live-Buchung.

Diese Änderung ermächtigt weder eine Abbuchung von Guthaben noch einen Tarifwechsel oder eine kostenpflichtige Zusatzoption.
