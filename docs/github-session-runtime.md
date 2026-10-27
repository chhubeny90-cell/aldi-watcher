# GitHub-Sitzung und Nachbuchung: derzeit deaktiviert

## Aktueller Workflow-Status

`.github/workflows/hosted-session.yml` heißt auf `main`
**ALDI Session and Free Refill (disabled)**. Der Workflow enthält nur einen
Sperrhinweis und endet mit Exit-Code 2. Er besitzt keine Initialize-, Observe-
oder Refill-Auswahl, keinen Zeitplan und keine Verkettung mit dem Mailmonitor.
Er lädt keine Zugangsdaten und kontaktiert ALDI nicht.

Die aktuelle Projektregel sieht ohne nachgewiesene ausdrückliche Anbieterfreigabe
keinen skriptgesteuerten Zugriff auf das geschützte Kundenkonto vor. Deshalb sind
auch vermeintlich nur lesende Session- oder Statusabrufe nicht über diesen
Workflow ausführbar. Neue Secrets oder ein manueller Dispatch heben die Sperre
nicht auf.

Die früher hier beschriebene Inbetriebnahme über `initialize`, `observe` und
`refill` sowie die stündliche automatische Nachbuchung sind **kein aktueller
Bedienweg**. Diese Funktionen nicht durch direkte Python-Aufrufe, alte Commits,
alternative Workflows oder das Entfernen von Sperren starten.

## Zulässiger nächster Read-only-Schritt

Der Kontoinhaber prüft die richtige SIM, den aktiven Tarif, das frische
Restvolumen und gegebenenfalls den vollständigen 1-GB-Angebots-/Preiskontext
selbst in der offiziellen App oder im Portal. Siehe den Read-only-Abschnitt der
[manuellen Prüfanleitung](aldi-safe-manual-live-check.md).

Der aktuelle Arbeitsauftrag umfasst keine Buchung, Tarifänderung oder bezahlte
Aktion. Eine in anderen Abschnitten beschriebene manuelle Buchungsmöglichkeit
ist keine Freigabe für diesen Auftrag. Eine Mail ist ein Hinweis für den
Kontoinhaber, kein Preis-, SIM- oder Buchungsnachweis und kein Provider-Trigger.

Für technische Rückmeldungen nur minimierte Angaben teilen: Zeitpunkt mit
Zeitzone, richtige SIM geprüft, exakter Tarif, Restvolumen mit Einheit und
angezeigte Angebots-/Kostenhinweise. Keine Zugangsdaten, SMS-Codes, Rufnummern,
Cookies, vollständigen Journaldateien oder rohen Anbieterantworten veröffentlichen.
Manuelle Angaben als solche kennzeichnen; sie sind kein automatischer Nachweis.

## Vorhandene Bausteine sind keine laufende Installation

`aldi_hosted_runtime.py` und `github_encrypted_runtime.py` enthalten weiterhin
Bausteine für Sitzungswiederverwendung, Kontoprüfung und verschlüsselte
Zustandspersistenz. Ihr Vorhandensein oder bestandene Offline-Tests beweisen
weder eine aktive Sitzung noch einen produktiven Dauerbetrieb.

Der frühere Observe-Bericht meldet strukturelle Werte wie `status_verified` und
`free_refill_available`. Diese Booleans allein belegen keinen exakt angezeigten
Tarif und keinen konkreten aktuellen Volumenwert. Ein erfolgreicher historischer
Login bestätigt kein kostenfreies Angebot und keine automatische Freigabe.
Der dokumentierte Login vom 25.10.2026 ist in
[der Login-Statusbeschreibung](aldi-http-login.md) eingeordnet.

Vorhandene verschlüsselte Sitzungsdaten, Journalhistorie, Recovery-Schlüssel und
ungeklärte Vorgänge erhalten. Fehlender oder unlesbarer Zustand darf nicht als
leere Historie initialisiert werden. Schlüssel weder auslesen/veröffentlichen
noch blind ersetzen. Unbekannte Ergebnisse und aktive Auth-Sperren bleiben
ungeklärt beziehungsweise gesperrt; keine automatische Wiederholung.

## Voraussetzungen einer späteren Neubewertung

Eine künftige Aktivierung setzt zuerst eine nachgewiesene Anbieterfreigabe für
den vorgesehenen Zugriff voraus. Danach sind der aktuelle Code, Ziel-SIM,
Sitzungsbindung, Persistenz, Auth-Backoff, Wiederanlauf und Fehlerfälle unabhängig
zu prüfen. Keine Freigabe durch einen Teststatus oder durch Einrichten von Secrets
ableiten. Dieses Dokument fordert keine neue Schlüsselanlage oder Aktivierung an.

Eine spätere Buchung wäre ein eigener, gesondert freizugebender Schritt:
frisches Restvolumen strikt unter 1 GB, genau 1 GB zum expliziten Preis 0,00 €,
keine widersprechenden Kostenhinweise, richtige SIM/Tarifberechtigung, bestätigtes
Journal und kein ungeklärter früherer Vorgang. Bei Timeout oder unklarem Ergebnis
kein zweiter Klick; Erfolg nur mit vorgangsbezogener offizieller Bestätigung.
Wiederkehrender Livebetrieb bleibt außerhalb des aktuellen Auftrags.

Die Login-Aufgaben und tatsächlichen Blocker stehen in
[Issue #116](https://github.com/chhubeny90-cell/aldi-watcher/issues/116);
weitere Betriebsaufgaben in
[Issue #125](https://github.com/chhubeny90-cell/aldi-watcher/issues/125).
