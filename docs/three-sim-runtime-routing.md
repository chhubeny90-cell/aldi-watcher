# Drei SIMs, zwei Kontozugänge, ein Mail-Auslöser

Stand 16.10.2026. Keine Zugangsdaten oder persönlichen Nummern in dieser Datei.

## Zielzuordnung

- account_a und account_b: zwei vom Nutzer im Konto-Umschalter gezeigte SIMs, gemeinsamer Login.
- account_c: separate Router-SIM, separater Login.
- Laut Nutzer dieselbe Kontakt-Mailadresse für alle drei; Screenshot bestätigt die Adresse des gemeinsamen Kontos.
- Eine neue gültige Verbrauchsmail löst die Prüfung aller drei bekannten Ziel-SIMs aus. Die Mail allein wählt kein Buchungskonto und beweist keine Gratisberechtigung.

## Vorbereitete Konfiguration

Ein privates verschlüsseltes Manifest im vorhandenen Format ALDI_ACCOUNTS_ENC wurde lokal für drei aktivierte monitor_only-Profile und zwei unterschiedliche Login-Identitäten erzeugt, validiert und nach Entschlüsselung erneut validiert. Es ist nicht in GitHub-Secrets hochgeladen und nicht Teil dieses Repositorys. Aktuelle lokale Dateien sind kein dauerhaft eingerichteter Secret-Store.

## Bestehende Fähigkeiten und Grenzen

core/aldi_accounts.py unterstützt Ziel-SIM und separate Login-Identität sowie die Auswahl verknüpfter SIMs im Browser. aldi_accounts_monitor.py ist rein lesend und startet derzeit einen eigenen Browser und Login pro Profil: eine gemeinsame Sitzung für zwei SIMs ist noch NICHT umgesetzt. Der Actions-Workflow accounts.yml ist deaktiviert. Die Vorbereitung des Manifests aktiviert keinen Zeitplan.

Für die Router-SIM wurde HTTP-Login samt Kontoabgleich nachgewiesen. Für das gemeinsame Konto scheitert die eigene Cookie-Prüfung noch; ein Token beziehungsweise eine Weiterleitung allein bestätigt nicht beide Ziel-SIMs. Aktuelles Volumen und Buttonzustand sind für keine der drei SIMs automatisiert belegt. Keine automatische Buchung.

## Ausführung

1. Neue echte ALDI-Verbrauchsmail erkennen und dauerhaft deduplizieren.
2. Alle drei Zielprofile getrennt prüfen; Fehler eines Profils dürfen die übrigen Prüfungen nicht verdecken.
3. Seite frisch laden und vollständige Daten abwarten; Ziel-SIM nach jeder Navigation erneut bestätigen.
4. Tarif und kostenloses Angebot separat pro SIM belegen. Ein SIM-Spitzname beweist keinen Tarif. Basis-/Jahrestarif nicht pauschal als Unlimited behandeln.
5. Nur verfügbare eindeutig kostenlose 1-GB-Nachbuchung auslösen; deaktivierte Elemente nicht künstlich aktivieren.
6. Anbieterbestätigung, aktualisiertes Volumen und unabhängiges Vorgangsprotokoll pro SIM führen. Unklare Ergebnisse nicht blind wiederholen.

## Benötigte Dienste

GitHub: alleinige Code- und Konfigurationsdokumentation. Gmail: Quelle für Verbrauchsmails. Ein dauerhafter Runner mit Secret-Store und Browser: tatsächliche Ausführung. Drive, Dropbox, Adobe und Replit werden nicht zusätzlich eingerichtet, solange keine konkrete technische Lücke dies erfordert. Die bestehende ChatGPT-Gmail-Verbindung stellt kein IMAP-App-Passwort für Actions bereit.

## Noch zu leisten

Browserlaufzeit bereitstellen; gemeinsame Kontoauswahl verifizieren; frische Volumen-/Buttonprüfung durchführen; eigene Mailauthentifizierung und dauerhafte Secrets einrichten; erst danach unbeaufsichtigten Gesamtbetrieb nachweisen. Keine Betriebsfreigabe aus einem validierten Manifest ableiten.
