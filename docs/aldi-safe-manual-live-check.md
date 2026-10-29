# Sichere ALDI-Live-Prüfung (manuell)

Stand: 26.10.2026. Diese Anleitung ermöglicht eine echte, aber vom Kontoinhaber selbst durchgeführte Read-only-Prüfung. Sie aktiviert keine automatisierte Anmeldung oder Buchung.

## Warum nur manuell?

Die aktuellen ALDI-TALK-AGB untersagen in Ziffer 10.3(g) den Zugriff auf die für die Vertragsleistungen bereitgestellten Software und Systeme über nicht autorisierte Software, Skripte oder Bots. Eine ausdrückliche Freigabe für den automatisierten Kundenportalzugriff ist in diesem Repository nicht nachgewiesen.

Quelle: [ALDI TALK Leistungsbeschreibung & AGB, Ziffer 10.3(g), PDF-Seite 16](https://media.medion.com/cms/medion/alditalkde/ALDI-TALK-Leistungsbeschreibung.pdf).

Deshalb führen GitHub Actions und Watcher-Code keinen ALDI-Login, authentifizierten Statusabruf, Passwort-Reset oder Buchungsklick aus. Die früheren Login-, Diagnose- und Refill-Workflows sind als Policy-Guard deaktiviert. Der Mailmonitor darf Nachrichten als Signal erkennen, aber das Signal startet keine Provider-Aktion.

## Read-only-Prüfung durch den Kontoinhaber

1. Öffne selbst die offizielle ALDI-TALK-App oder gib die offizielle Portaladresse manuell ein. Melde dich dort selbst an. Gib Passwort und SMS-/2FA-Code niemals in Chat, GitHub, ein Skript oder einen Workflow ein.
2. Prüfe im angemeldeten Konto anhand deiner privat hinterlegten Zielrufnummer, dass es die vorgesehene SIM ist. Teile außerhalb des Kontos nur mit, ob die Zuordnung stimmt; weder vollständige Rufnummer noch Endziffern in GitHub, Screenshots oder Logs speichern.
3. Notiere den angezeigten Tarif exakt und das aktuell verbleibende Highspeed-Volumen. Tarif S allein belegt keine Unlimited-Berechtigung.
4. Falls ein 1-GB-Angebot erscheint, prüfe den vollständigen Angebotskontext und Preis. Nur ein eindeutig für dieses Konto angezeigtes Angebot mit **genau 1 GB** und **0,00 €** besteht diese Preisprüfung. Ein fehlender Preis, „kostenlos“ ohne Betrag, ein positiver Betrag oder ein Hinweis auf Guthabenabzug bedeutet: **stoppen, nichts anklicken**.
5. Prüfe, dass keine Kontosperre oder offene, ungeklärte Buchung angezeigt wird. Bei Sperre oder unklarem Zustand keine weiteren Loginversuche und keine Buchung.

### Einmalige manuelle Buchung

Die Read-only-Prüfung kann ohne Buchung abgeschlossen werden. Eine Buchung ist ein eigener Schritt. Falls der Kontoinhaber nach Sichtprüfung selbst eine Buchung durchführen möchte, darf er höchstens einmal das eindeutig mit 0,00 € ausgezeichnete 1-GB-Angebot auswählen. Keine zweite Buchung für dieselbe Verbrauchsmail, kein Doppelklick und kein automatischer Retry. Bei Ladefehler, Timeout oder unklarem Ergebnis nicht erneut klicken.

Als Erfolg zählt nur eine offizielle ALDI-Bestätigung, die genau diese 1-GB-Option dem Vorgang zuordnet. Ein veränderter Restvolumenstand oder eine allgemeine Bestellbestätigung allein reicht nicht. Danach den neuen Reststand manuell prüfen. Ein zweites Gigabyte wäre ein separater Vorgang und benötigt eine neue, ausdrücklich angezeigte Berechtigung und 0,00-€-Prüfung.

## Datenschutz und Ergebnisnotiz

Keine Zugangsdaten, SMS-/2FA-Codes, Session-Cookies, vollständige Rufnummern oder ungeschwärzten Screenshots weitergeben. Für eine technische Rückmeldung reicht diese minimierte Notiz:

```text
Zeitpunkt (Europe/Berlin):
Zielkonto-Endziffern stimmen: ja/nein
Tarif exakt angezeigt:
Restvolumen (GB):
Genau 1 GB angeboten: ja/nein
Expliziter Preis 0,00 €: ja/nein
Hinweis auf Guthabenabzug oder Zusatzkosten: ja/nein
Kontosperre/offener Vorgang angezeigt: ja/nein
Buchung ausgeführt: nein/ja
Offizielle vorgangsbezogene Bestätigung: nein/ja
Neuer Reststand (GB), falls gebucht:
```

Diese Notiz unterstützt die Fehleranalyse. Sie ist keine automatische Freigabe: Code, CI, E-Mail-Signal oder eine manuelle Beobachtung erteilen keine Berechtigung für spätere automatisierte Providerzugriffe. Dafür wäre eine ausdrückliche Anbieterfreigabe und eine separate technische Abnahme nötig.
