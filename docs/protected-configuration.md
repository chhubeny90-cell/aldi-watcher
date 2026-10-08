# Geschützte Konfiguration und belastbarer Betriebsstatus

Stand: 8. Oktober 2026. Die vorhandenen Rufnummern bleiben in der separat
gesicherten privaten Projektkopie in `.env` als Fernet-Chiffretexte erhalten.
Die öffentliche `.env` enthält leere Credential-Felder und verweist auf Secrets
oder die mit `CREDENTIAL_ENV_FILE` verknüpfte private Konfiguration.
Beide Nummern und beide Passwortfelder
wurden durch Entschlüsselung gegen den ursprünglichen Inhalt verifiziert.
Die alten Klartext-Commits bleiben erhalten; diese
Änderung macht bereits veröffentlichte Nummern nicht rückwirkend geheim.
Ein öffentlicher Unterordner schützt keine Geheimnisse.

## Laufzeit-Verknüpfung

`Config` und `watcher.py` nutzen denselben Credential-Resolver. Pro Feld gilt:
ein nichtleeres Laufzeit-Secret gewinnt vor dem `.env`-Fallback. Innerhalb einer
Quelle gewinnt `_ENC`, dann `_FILE`, dann der direkte Wert. `_ENC` und `_FILE`
gleichzeitig sind ein Fehler. Ein defekter Chiffretext fällt niemals auf
Klartext zurück. Leere Actions-Secret-Variablen verdrängen den Fallback nicht.

Die Entschlüsselung nutzt entweder `CREDENTIAL_ENCRYPTION_KEY` oder die durch
`CREDENTIAL_KEY_FILE` bezeichnete Datei (Standard: `.secret.key`). Ein fehlender
Schlüssel wird beim Start niemals neu erzeugt. Auf POSIX müssen Schlüssel und
Credential-Dateien nur für den Eigentümer zugänglich sein (0600).

`ALDI_USER_FILE`, `ALDI_PASS_FILE`, `LIDL_USER_FILE`, `LIDL_PASS_FILE` verbinden
absolute geschützte Dateipfade. Leere Dateien, symbolische Links und öffentlich
lesbare Dateien werden abgewiesen. Windows-Dateirechte müssen über NTFS-ACLs
auf das Dienstkonto begrenzt werden; POSIX-Modusbits garantieren dort nichts.

GitHub Actions bindet `secrets.CREDENTIAL_ENCRYPTION_KEY` und die vier
`secrets.ALDI_USER_ENC`, `secrets.ALDI_PASS_ENC`, `secrets.LIDL_USER_ENC`,
`secrets.LIDL_PASS_ENC` an. Die verschlüsselten Werte aus der privaten `.env`
und den separat gesicherten Schlüssel als Repository-Secrets mit exakt diesen
Namen setzen. Auf einem dauerhaften Host reicht `CREDENTIAL_ENV_FILE` zum
privaten Konfigurationspfad und `CREDENTIAL_KEY_FILE` zum separaten Schlüssel.
Die GitHub-Verbindung dieser Arbeit unterstützt keine Secrets-Schreiboperation;
die Secrets wurden deshalb nicht automatisch eingerichtet. Vorhandene direkte
ALDI-/LIDL-Secrets funktionieren weiterhin und haben Vorrang. Der Schlüssel
darf nicht als Repository-Variable, Commit, Log oder Actions-Artefakt erscheinen.

Lokales Beispiel ohne Werte auszugeben:

```bash
python -m core.protect_config --key-file /private/path/credentials.key
CREDENTIAL_ENV_FILE=/private/path/.env CREDENTIAL_KEY_FILE=/private/path/credentials.key AUTO_BOOK_ENABLED=false python watcher.py --run-once
```

Die Zuordnung der Nummern zu ALDI/LIDL bleibt wie bisher. Sie ist keine
authentifizierte Prüfung des jeweiligen Accounts; weitere Nummern werden nicht
automatisch als zusätzliche Accounts betrieben. Die Passwortfelder des
ursprünglichen `.env` waren Platzhalter. Ihre Verschlüsselung erzeugt keine
gültigen Login-Zugänge.

## Fehler und Buchungsgrenze

Der überprüfte main-Lauf 37836819774 hat die Tests bestanden, konnte aber
keinen Anbieter authentifizieren: ALDI erreichte die SSO-Seite mit HTTP 200,
scheiterte bei `username_field`; LIDL antwortete HTTP 403. Dieses Problem ist
kein erfolgreicher Monitoring-Lauf und darf nicht grün umetikettiert werden.

ALDI sucht nun sichtbare, eindeutige Eingabefelder und Aktionen auch in offenen
Shadow Roots (Helfer aus dem V5-Zweig). Die Domain wird vor jeder Eingabe und
vor dem einmaligen Login-Klick erneut überprüft. CAPTCHA, geschlossene Shadow
Roots, fremde Frames oder serverseitige Zugriffsverweigerung werden dadurch
nicht umgangen. Die Wirkung am echten Account bleibt nachzuweisen.

Konfigurations-/Entschlüsselungsfehler ergeben einen bereinigten Bericht,
Exit 3 und keinen Browserstart für den betroffenen Anbieter. Der legacy-ALDI-
Buchungsendpunkt bleibt ohne Netzwerkanfrage gesperrt. HTTP 200 ist keine
Bestätigung einer kostenlosen Gutschrift. PENDING/UNKNOWN-Sperren bleiben
über Neustarts erhalten. Konsolenlogs geben keine Accountnummer aus.

Noch erforderlich für Live-Bereitschaft: gültige sichere Zugangsdaten,
authentifizierter Account- und Tarifabgleich, ein eindeutig kostenloses
1-GB-Angebot, beobachtete Gutschrift und autoritative nachträgliche Zuordnung
zu genau diesem Buchungsversuch. Der V5-Adapter in PR #11 liefert für
Reconciliation weiterhin UNKNOWN; diese Arbeit ersetzt ihn nicht durch
erfundene Provider-Endpunkte oder Erfolgsmerkmale. Ohne diese Nachweise bleibt
die automatische Buchung blockiert.

## Validierung

158 lokale Tests bestanden, einschließlich persistenter Sperren, Prozessabsturz-
und Concurrency-Tests, verschlüsselter Konfiguration, falscher/fehlender
Schlüssel, Secrets-Priorität, privater Dateien, Logbereinigung und eindeutiger
Login-Aktionen. `git diff --check` bestanden. Ein neuer echter Browserlauf wurde
nicht durchgeführt: Der Chromium-Download lieferte ein unbrauchbares Archiv.
Diese Tests beweisen keine aktuelle Provider-Authentifizierung oder Livebuchung.
