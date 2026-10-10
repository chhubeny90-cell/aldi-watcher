# Browserfreier ALDI-Login

`aldi_http_login_probe.py` startet genau einen Login mit der konfigurierten
Rufnummer und dem Passwort. Beide kommen über den vorhandenen Credential-Loader
und GitHub Secrets. Es gibt keinen Buchungsaufruf in diesem Test.

Referenz für das beobachtete Login-Protokoll:
- https://github.com/JonasJoKuJonas/homeassistant-AldiTalk
- Revision `8d0b432e61094c4dc316b04c4180d276be577e41` (2026-09-02)
- `custom_components/aldi_talk/aldi_talk.py`
- MIT-Hinweis: `third_party/homeassistant-alditalk-LICENSE.txt`

Zusätzlich geprüft:
https://github.com/kirby-101/AT-Celerceptor. Dessen Code bestätigt denselben
ForgeRock-Callback-Ansatz; eine vollständige Gratis-Nachbuchung wird daraus nicht
übernommen.

Der Test verwendet eine frische HTTP-Sitzung, verarbeitet die vom Server
zurückgegebenen Login-Callbacks und gegebenenfalls dessen SHA-1-Rechenaufgabe,
wählt ausdrücklich den Passwort-Login und folgt der OAuth-Weiterleitung.
Weiterleitungen werden vor jedem GET auf drei bekannte ALDI-Hosts beschränkt;
Credential-POSTs folgen keiner Weiterleitung. SMS, Passwort-Reset und unbekannte
zusätzliche Authentifizierungsanforderungen werden nicht ausgelöst.

`login_ok=true` verlangt eine geschützte JSON-Antwort und die Übereinstimmung der
im Portal-Cookie ausgewählten Rufnummer. Der JSON-Bericht enthält ausschließlich
Phasen, feste Fehlercodes und strukturelle Ergebnisse. Cookies, Tokens,
Rufnummern, Passwort und Accountinhalte werden nicht gespeichert.

Manuell: Workflow **ALDI HTTP Login** starten. Ein Main-Commit mit
`[http-login]` startet ebenfalls einen einzelnen Test. Automatische stündliche
Nachbuchungen bleiben im vorhandenen Live-Workflow. Der HTTP-Zugang wird erst
nach erfolgreicher Prüfung dort verwendet.
