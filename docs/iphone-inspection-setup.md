# Safari-Diagnose auf dem iPhone

Dies ist eine Anleitung mit JavaScript, keine importierbare `.shortcut`-Datei.
Sie erfasst nur technische Merkmale möglicher Nachbuchungsbuttons, keine
Rufnummern, Texte der Kontoseite, Zugangsdaten, Cookies oder URLs.
Sie klickt nicht, lädt nichts neu und sendet keine Netzwerkanfragen.

1. In Kurzbefehle einen neuen Kurzbefehl „ALDI Diagnose“ erstellen.
2. Unter Details „Im Share-Sheet anzeigen“ aktivieren; als Eingabetyp nur
   „Safari-Webseiten“ wählen.
3. Aktion „JavaScript auf Webseite ausführen“ hinzufügen. Als Webseite die
   Kurzbefehleingabe verwenden. Den gesamten Inhalt von
   `scripts/iphone/inspect-refill.js` in das Skriptfeld kopieren.
4. Danach „Ergebnis anzeigen“ hinzufügen und die Ausgabe der JavaScript-Aktion
   als Ergebnis verwenden.
5. Falls verlangt: in Einstellungen > Apps > Kurzbefehle > Erweitert die
   Ausführung von Skripten erlauben. Die Menübezeichnungen können variieren.
6. In Safari die bereits angemeldete ALDI-Kontoübersicht neu laden und warten,
   bis das Restvolumen sichtbar ist. Teilen > ALDI Diagnose wählen und die
   gegebenenfalls angeforderte Berechtigung für diese Webseite erteilen.
7. Den angezeigten JSON-Bericht hier teilen. Er enthält keine Zugangsdaten.

Bei `wrong_page` ist nicht die Kundenportal-Seite geöffnet. Kein Kandidat
bedeutet nicht, dass keine Nachbuchung möglich ist: geschlossene Shadow-DOMs,
Frames oder andere Steuerelemente können von dieser Diagnose unzugänglich sein.
Ein Kandidat ist noch kein verifizierter Buchungsaufruf. Das Skript wurde lokal
mit einer simulierten Seite geprüft, noch nicht auf dem tatsächlichen iPhone.

Ein Neuladen innerhalb derselben JavaScript-Aktion wird absichtlich vermieden:
eine Navigation kann den laufenden Skriptkontext zerstören. Daher zuerst in
Safari aktualisieren, danach die Diagnose über das Teilen-Menü starten.
