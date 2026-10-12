# ALDI TALK: kostenlose Unlimited-1-GB-Nachbuchung

Stand: 2026-10-12

## Verifizierte Anbieterregel

ALDI TALK beschreibt für die Unlimited-on-Demand-Tarife die kostenlose Nachbuchung von jeweils 1 GB, sobald das verbleibende Highspeed-Datenvolumen unter 1 GB liegt. Die Nachbuchung kann wiederholt genutzt werden.

Offizielle Quelle:
- https://www.alditalk.de/tarife-unlimited-gb-nachbuchen

## Entscheidung im Watcher

`core/aldi_refill.py` darf ein lokales 1-GB-Angebot ohne sichtbare `0,00 €`-Angabe nur dann als kostenlos einstufen, wenn gleichzeitig:

1. weniger als 1 GB Restvolumen verifiziert ist,
2. genau ein aktiver Unlimited-Tarif erkannt ist,
3. genau ein aktivierter 1-GB-Nachbuchungs-Button lokal zugeordnet ist,
4. derselbe lokale Angebotskontext ausdrücklich `Unlimited` oder `On Demand` und Nachbuchung erkennen lässt,
5. keine positive, widersprüchliche oder nicht eindeutig parsebare Preisangabe vorhanden ist.

Ein generisches `1 GB nachbuchen` ohne Preis bleibt gesperrt. Ebenso bleiben Jahrespakete, Basistarife, unklare Tarife, mehrere Kandidaten und deaktivierte Buttons gesperrt. Ein positiver Preis blockiert immer, auch wenn gleichzeitig `gratis`, `kostenlos` oder `0,00 €` im Kontext steht.

`Tarif S` ohne Unlimited-Nachweis erhält keine implizite Kostenfrei-Freigabe und benötigt weiterhin einen expliziten kostenlosen Preis-/Gratis-Nachweis.

## Keine Live-Freigabe

Diese Erkennung entscheidet nur, ob ein Angebot als kostenlos und passend klassifiziert werden darf. Sie aktiviert keine Live-Buchung und ändert die bestehenden Sperren für fehlende Reconciliation, Journal-/Runner-Konfiguration oder ungeklärten Loginstatus nicht.
