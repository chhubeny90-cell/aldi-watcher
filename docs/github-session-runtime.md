# Sitzung und kostenlose Nachbuchung auf GitHub

Der Workflow **ALDI Session and Free Refill** ist für GitHub-gehostete
Standard-Linux-Runner vorbereitet. Er richtet keinen kostenpflichtigen Dienst
ein und verwendet keine kostenpflichtigen Runner. Für öffentliche Repositorys
sind solche Standard-Runner grundsätzlich kostenlos; maßgeblich bleiben die
aktuellen GitHub-Konditionen und Kontoeinstellungen. Es werden ausschließlich
eindeutig kostenlose 1-GB-Angebote für die konfigurierte Ziel-SIM berücksichtigt.
Bezahlte Angebote und Tarifwechsel sind ausgeschlossen.

## Einmal einrichten

Rufnummer und Passwort verwenden die vorhandenen Repository-Secrets
`ALDI_PROFILE_1_USER` und `ALDI_PASS` beziehungsweise `ALDI_PASS_ENC` zusammen mit
`CREDENTIAL_ENCRYPTION_KEY`. Das Repository-Secret `ALDI_REQUIRED_TARGET_SUFFIX`
enthält zusätzlich die letzten vier Ziffern der Ziel-SIM. Der vollständige
Kontoabgleich bleibt maßgeblich; die Endziffern allein autorisieren nichts.
Die Endziffern werden als Secret übergeben, damit sie auch in Actions-Schrittköpfen
maskiert bleiben. Fehlende oder falsche Zielkonfiguration stoppt vor der Anmeldung.
Zusätzlich ist ein unabhängig erzeugter
Fernet-Schlüssel als Repository-Secret **`ALDI_STATE_ENCRYPTION_KEY`** erforderlich.
Das Passwort wird nicht als Verschlüsselungsschlüssel wiederverwendet.
Ohne diesen zusätzlichen Schlüssel erfolgen weder ALDI-Zugriffe noch Buchungen.

Den Schlüssel privat und außerhalb des Repositorys sichern. Ein Schlüsselverlust
ist kein Anlass, den gespeicherten Zustand oder die Buchungshistorie zu löschen.
Die GitHub-Anbindung dieser Sitzung kann Repository-Secrets nicht selbst setzen.

1. Unter **Actions → ALDI Session and Free Refill → Run workflow** auf `main`
   einmal **initialize** auswählen. Dieser Schritt richtet den verschlüsselten
   Zustand ein; er meldet sich nicht bei ALDI an und bucht nichts.
2. Mit **observe** die Sitzung und die aktuelle SIM-/Tarif-/Volumen-/Angebotsprüfung
   kontrollieren. Ein neuer Login bleibt an die bestehende Authentifizierungssperre
   gebunden. Nach dem bestätigten Login-Test vom 25.10.2026 ist ein neuer
   Passwortversuch frühestens am **26.10.2026 um 22:48:21 UTC** möglich.
3. Mit **refill** die erste kostenlose Nachbuchung freigeben und prüfen.
   Ist noch kein Angebot verfügbar oder der neue Login noch gesperrt, bleibt
   diese Freigabe gespeichert. Der Zeitplan prüft weiter und darf die erste
   Nachbuchung bei tatsächlicher Verfügbarkeit auslösen, ohne erneute Rückfrage.
   Pro Lauf ist höchstens eine Nachbuchung möglich. Erst eine durch den Anbieter
   bestätigte, dem konkreten Vorgang zugeordnete erfolgreiche Nachbuchung schaltet
   die wiederholten automatischen Nachbuchungen im geschützten Zustand frei.

Die Initialisierung ersetzt keinen verlorenen Zustand. Ein vorhandener
Initialisierungsmarker bei fehlendem oder unlesbarem Zustand führt zum Abbruch.
Ungeklärte frühere Buchungsvorgänge müssen erhalten und geklärt werden.

## Wiederkehrende Läufe

Der Zeitplan prüft stündlich zur Minute 17. Zusätzlich stößt ein erfolgreich
beendeter Mailprüflauf auf `main` eine frische Kontoprüfung an. Nur der benannte
Workflow aus demselben Repository mit zulässigem Auslöser wird akzeptiert;
Forks, Pull-Request-Läufe und fehlgeschlagene Mailprüfungen starten keinen Aktor.
Eine Mail ist lediglich ein Prüfhinweis, kein Preis-, SIM- oder Buchungsnachweis.
Ohne Freigabe der ersten
Nachbuchung beobachten diese Läufe nur. Mit gespeicherter Erstfreigabe versucht
der Zeitplan den ersten tatsächlich verfügbaren Gratis-Refill. Nach dessen
bestätigtem Erfolg kann jeder automatische
Lauf erneut eine kostenlose 1-GB-Nachbuchung ausführen, wenn die frische Prüfung
von Ziel-SIM, Tarif, Restvolumen und aktivem Gratisangebot dies erlaubt. Ein
Mailkonto ist für die stündliche Rückfallprüfung nicht erforderlich.

Der Mailmonitor prüft Warnungen, vollständigen Verbrauch und Bestätigungen
getrennt. Originale Nachrichtenidentität und Empfangsfortschritt werden dauerhaft
und nichtidentifizierend gespeichert; gelesene Nachrichten bleiben einbezogen.
Rückstände werden in aufsteigenden UID-Batches verarbeitet, statt ältere neue
Meldungen durch ein Fenster der letzten 50 Nachrichten zu verlieren. Ein
Server-UID-Wechsel verwirft die gespeicherte Nachrichtenhistorie nicht.
Allgemeine Bestell- oder Optionsbestätigungen bestätigen keine konkrete
kostenlose 1-GB-Nachbuchung und lösen keine Vorgangssperre auf.

Für die Nachrichten-Deduplizierung wird ein vorhandener `ALDI_RECOVERY_KEY`
beibehalten. Fehlt er, kann der Monitor einen getrennten, stabilen HMAC-Schlüssel
aus `ALDI_STATE_ENCRYPTION_KEY` ableiten. Das ALDI-Passwort wird dafür nicht benutzt.
Ohne beide Schlüssel prüft er nur die Mail-Anmeldung lesend und bleibt für
Nachrichtenverarbeitung und Buchungen gesperrt. Die ChatGPT-Gmail-Verbindung
liefert die bestehende Mailanalyse; sie stellt GitHub Actions kein dauerhaftes
IMAP-App-Passwort bereit. Vorhandene `MAILBOX_*`-Secrets müssen dort separat gültig sein.

Eine gültige Sitzung wird zwischen den Jobs übernommen und vor Verwendung erneut
geprüft. Ein gültiger gespeicherter Login verlangt keinen neuen Passwortversuch
pro Zeitplantakt; der bestehende Login-Abstand ist kein Nachbuchungsintervall.
Nur ein bestätigter Sitzungsablauf darf einen kontrollierten neuen Login auslösen.
Nach einem erfolgreich geprüften und verschlüsselt gespeicherten neuen Login
wird ausschließlich die Reservierung dieses eigenen Versuchs wieder freigegeben.
Nach Fehler oder unklarem Ergebnis bleibt sie bestehen. Die bestehende Sperre
des früheren Login-Tests wird nicht vorzeitig gelöscht.
Unklare Netzwerk-, Identitäts- oder Zustandsfehler lösen keinen weiteren
Passwortversuch und keine blinde Wiederholung einer Buchung aus.

GitHub Actions hält keinen Browser dauerhaft offen. Jeder Job startet einen neuen
Browser und übernimmt dafür die geschützte Sitzung. ALDI kann sie serverseitig
beenden. GitHub kann geplante Jobs verzögern oder auslassen und Zeitpläne bei
Inaktivität deaktivieren; dieser Aufbau verspricht deshalb weder sekundengenaue
Nachbuchungen noch lückenlosen Dauerbetrieb.

## Geschützter Zustand und Ergebnisse

Sitzungscookies und das vollständige private SQLite-Journal einschließlich
Anbieterbelegen werden nur verschlüsselt auf dem Zustandsbranch gespeichert.
Vor einem Buchungsklick muss die persistierte Reservierung bestätigt sein.
Datei-SHA-Vergleich und anschließendes Rücklesen verhindern, dass widersprüchliche
oder unbestätigte Schreibvorgänge als erfolgreiche Speicherung gelten.
Terminale Buchungen und eindeutige Anbieter-Vorgangskennungen bleiben über
Jobwechsel erhalten. Ungeklärte Ergebnisse bleiben gesperrt.

Klartext-Cookies, Passwörter, Journaldateien und rohe Anbieterantworten werden
nicht als Actions-Artefakt hochgeladen. Das einzige Ergebnisartefakt ist der
bereinigte Bericht; die deutsche Zusammenfassung erklärt den nächsten Schritt.
Diese Berichte enthalten Zeitpunkte, Phasen, feste Ergebnisgründe und Zähler
für Anmeldungen und Buchungen. Sie bleiben drei Tage als Actions-Artefakt
verfügbar; die vollständige Buchungshistorie bleibt im verschlüsselten Journal.
Unveränderte Sitzungsdaten erzeugen keinen neuen Zustandscommit. Der geschützte
Zustandsbranch verwendet für Datenaktualisierungen einen CI-Skip-Marker, damit
Sitzungswechsel nicht die kompletten Code-Testworkflows erneut starten. Der
Snapshot ist auf 512 KiB begrenzt; bei Erreichen stoppt der Lauf, statt alte
Buchungsnachweise zu löschen. Dann ist eine kontrollierte Erweiterung oder
der spätere Umzug auf Linux nötig.
Eine fehlende Zusammenfassung oder ein fehlender Bericht bestätigt weder Login
noch Buchung.

Ein späterer Umzug auf ein Linux-Gerät kann dieselben Kontoprüfungen,
Nachbuchungsbedingungen und das vollständige Journal übernehmen. Der Umzug
erfordert eine kontrollierte Übernahme des entschlüsselten privaten Zustands;
eine neue leere Buchungshistorie ist kein Ersatz.
