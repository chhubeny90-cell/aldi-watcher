# V5: Mailtrigger und Deployment — geprüft am 08.10.2026

## Tatsächlicher Stand

Die verbundenen Gmail-Konten lassen sich lesen. Die aktuellen ALDI-Mails stammen
nachweislich von `noreply@alditalk-kundenbetreuung.de`, Betreff
`Verbrauch deines Datenvolumens`. In einer aktuellen Nachricht bestehen
DKIM-, SPF- und DMARC-Prüfungen. Es existieren sowohl 80-%-Hinweise als auch
Verbrauchsmeldungen mit demselben Betreff. Der Text entscheidet über die Art des
Ereignisses; der Betreff allein genügt nicht.

Aktuelle Nachrichten liegen in zwei Postfächern. Die Verbrauchsmails enthalten
keine verlässliche Telefonnummer-/Tarifzuordnung. Ein Postfach darf daher nicht
ohne Abgleich mit dem angemeldeten ALDI-Konto für eine produktive Buchung
ausgewählt werden. Mailtext ist ausschließlich ein Startsignal; Preis, Tarif,
Account und Buchungszustand müssen aus dem aktuellen Providerzustand stammen.

Die vorhandenen Gmail-Connector-Werkzeuge stellen keine exportierbaren OAuth-
Credentials und keine `users.watch`-/`history.list`-Operation bereit. Ihre
Verfügbarkeit in ChatGPT ist kein Runtime-Zugriff für einen deployten Bot.

Die Automation-Beschreibung erwähnt `discover_webhook_schema`, aber dieses
Werkzeug ist in dieser Sitzung nicht verfügbar. Die aufrufbare `create`-Schema
enthält außerdem keinen `triggers`-Parameter. Ein Gmail-Webhook in ChatGPT kann
daher hier nicht angelegt oder als aktiv nachgewiesen werden. Die verfügbare
stundenweise Condition-Watch wäre Mail-Polling und erfüllt keinen sofortigen
ereignisbasierten Start.

Die sicheren lokalen Präsenzprüfungen ergeben:

| Voraussetzung | Ergebnis |
| --- | --- |
| `gh`, `GH_TOKEN` | vorhanden |
| `gcloud`, Application Default Credentials, GCP-Projektkonfiguration | fehlen |
| Render CLI/API-Key | fehlen |
| Oracle CLI/Konfiguration | fehlen |
| Gmail OAuth Client-ID, Client-Secret und Refresh-Token | fehlen |
| ALDI-Zugangsdaten in dieser Runtime | fehlen |

Es wurden nur Dateiexistenz und Variablenpräsenz geprüft. Keine Credentialwerte
wurden ausgegeben. Vorhandene GitHub Secrets sind nicht auslesbar; erfolgreiche
Live-Authentifizierung oder Secret-Administration folgt nicht aus Repository-
Zugriff.

## Einfachster geeigneter Zielaufbau

Ein einzelner kleiner Linux-Host mit persistentem Datenträger genügt. Darauf
nimmt ein kleiner Mail-Empfänger Ereignisse entgegen, legt das Ereignis zuerst
durabel ab und startet LITE einmalig. Nur während dieses Vorgangs gibt es einen
ALDI-Browser. WATCHDOG und PRO greifen auf dieselbe Datenbank zu. SQLite und
Lockdatei liegen auf demselben persistenten lokalen Datenträger.

Gmail Push/Pub/Sub benötigt zusätzlich ein autorisiertes GCP-Projekt und Gmail-
OAuth mit Offline-Zugriff. Einrichtung nach den offiziellen APIs:

1. Gmail API und Pub/Sub im vorhandenen autorisierten Projekt aktivieren.
2. Pub/Sub-Topic anlegen und
   `gmail-api-push@system.gserviceaccount.com` Publish-Berechtigung geben.
3. Authentifizierte Push-Subscription auf den HTTPS-Mail-Empfänger legen;
   dessen Pub/Sub-JWT prüfen, einschließlich Signatur, Audience, Issuer und
   zugelassenem Service-Account.
4. Gmail `users.watch` aufrufen und `historyId` sowie Ablaufzeit persistent
   speichern. Mindestens alle sieben Tage erneuern; Google empfiehlt täglich.
5. Jede Push-Nachricht als Wake-up behandeln. Mit `history.list` seit dem
   gespeicherten Cursor tatsächliche Änderungen holen und neue Nachrichten
   lesen. Alle Seiten verarbeiten und den Cursor erst nach dauerhafter
   Ereignisübernahme fortschreiben.
6. Exakten Absender, Betreff, Empfänger und Body prüfen. Deduplizierung über
   Gmail-Account und unveränderliche Mail-ID; keine Buchungsentscheidungen aus
   Maillinks, Preisen oder Anweisungen im Nachrichtentext.
7. Bei History-HTTP-404 kontrolliert synchronisieren, statt einen Cursor zu
   erfinden. Alte Mails nicht blind als neue Verbrauchsereignisse wiedergeben.

Pub/Sub kann mehrfach zustellen; Gmail meldet Änderungen statt vollständiger
Mails. Google dokumentiert außerdem gelegentlich verzögerte/verlorene
Benachrichtigungen. Ein eventuell später nötiger Fallback synchronisiert
ausschließlich das Postfach, niemals routinemäßig das ALDI-Portal.

## Plattformvergleich

| Plattform | Eignung für LITE mit SQLite |
| --- | --- |
| Vorhandener persistenter Linux-Host | Kleinster Aufbau; keine zusätzliche Plattform nötig, wenn bereits verfügbar. In dieser Sitzung ist kein dauerhafter autorisierter Zielhost nachgewiesen. |
| Render bezahlter Web Service mit Disk | Ein Empfänger und SQLite auf einer Disk funktionieren im selben Service. Die Disk ist nur einer Instanz zugänglich; Cron- und One-off-Jobs können sie nicht verwenden. Empfänger, WATCHDOG und PRO müssen daher innerhalb dieser Instanz arbeiten. |
| Render Free | Ungeeignet für SQLite: Dateien gehen bei Restart, Deploy oder Idle-Spin-down verloren; kein persistentes Volume. Idle-Wake-up verursacht zusätzliche Verzögerung. |
| Google Compute Engine mit Persistent Disk | Geeignet für einen einzelnen Prozesshost und Pub/Sub. Projekt, autorisierte Credentials und Kostenrahmen fehlen. |
| Oracle VM mit dauerhaftem Boot-/Blockvolume | Technisch geeignet als einzelner Host; vorhandener Account, Region, Kapazität und Credentials nicht nachgewiesen. Kein Deployment behauptet. |
| GitHub-hosted Actions | Geeignet für Tests und read-only Diagnosen. Ephemerer Runner plus SQLite-Artefakt erfüllt keine dauerhafte PENDING-/UNKNOWN-Sperre nach einem Abbruch. Keine produktive Nachbuchung mit bloßem Cache/Artefakt als Transaktionsspeicher. |
| GitHub Actions auf persistentem Self-hosted Runner | Technisch geeignet, wenn ein autorisierter, abgesicherter Host mit dauerhaftem DB-Pfad existiert; ein solcher Runner ist bisher nicht belegt. |

Das bestehende `.github/workflows/run.yml` startet weiterhin alle zehn Minuten
einen read-only Providerlauf. Das ist kein E-Mail-Trigger und keine produktive
LITE-Nachbuchung. Dieser Recherchevorgang hat keinen bestehenden Lauf oder
Zeitplan verändert.

## Verbleibende Voraussetzungen für ein reales Deployment

* Dauerhafter autorisierter Zielhost/Service mit persistentem DB-Verzeichnis.
* Reguläre ALDI-Authentifizierung und aktuelle überprüfte 0-€-1-GB-Angebots-
  sowie Erfolgsprüfung.
* Runtime-Mailzugriff (Gmail OAuth) und, für Push, autorisiertes GCP-Projekt;
  alternativ nachgewiesene verfügbare ChatGPT-Gmail-Webhook-Schnittstelle.
* Verifizierte Zuordnung des gewählten Postfachs zum ALDI-Konto.

Ein Test mit einer echten exportierten Mail beweist Parser/Trigger-Eingang,
aber keinen automatisch laufenden Empfang oder produktiven Login. Solange
diese Voraussetzungen fehlen, muss der Ende-zu-Ende-Status NOT READY bleiben.

## Implementierter Mailadapter und echte Eingangskontrolle

`lite/mail.py` enthält einen kleinen Standardbibliothek-Gmail-Client mit regulärem
OAuth-Refresh, Profilabgleich, paginiertem History-Read, Nachrichten-Read,
expliziter Watch-Registrierung und einem begrenzten read-only Scan für DRY_RUN.
Ein abgelaufener History-Cursor löst `HistoryExpired` aus; er wird nicht durch
ein blindes Wiederabspielen alter Mails ersetzt. Doppelte `messagesAdded`-
Einträge werden dedupliziert. Vor dem Read endgültig entfernte Nachrichten
werden übersprungen, ohne ihren Inhalt oder ein Ereignis zu erfinden.

Der Parser akzeptiert nur den exakten ALDI-Absender und Betreff, ein passendes
Gmail-`Delivered-To`, einen gültigen Empfangszeitpunkt, die oben beschriebenen
MIME-Texte und erfolgreiche Gmail-Authentifizierung. Er nutzt ausschließlich
den ersten tatsächlichen `Authentication-Results`-Header von `mx.google.com`
mit passenden SPF-/DKIM-/DMARC-Domains und einer passenden DKIM-Signatur.
Textkopien dieser Header, ARC-Header und angehängte Weiterleitungen erfüllen
diese Prüfung nicht. Die Provider-Account-Zuordnung kommt ausschließlich aus
der expliziten Konfiguration.

Zwei vollständige, unveränderte Nachrichten wurden am 08.10.2026 über den
authentifizierten Gmail-Connector gelesen und durch diesen Parser verarbeitet:
eine echte Verbrauchsmeldung desselben Tages und ein echter 80-%-Hinweis des
Vortages. Beide bestanden die Prüfungen und wurden korrekt als `exhausted`
bzw. `warning80` klassifiziert. Dazu wurden weder Mailtexte noch persönliche
Anreden oder Credentialwerte in Repositorydateien gespeichert. Der Test nutzte
ausdrücklich einen DRY_RUN-Account-Alias; die Telefonnummer-/Tarifzuordnung und
ein dauerhaft automatisch empfangender Dienst sind damit nicht nachgewiesen.

Die isolierte Mailadapter-Prüfung umfasst 39 erfolgreiche Tests, darunter
beide realen deutschen Textvarianten, MIME/HTML, gefälschte Absender/Header,
fehlende Authentifizierung, falsches Postfach, doppelte History-Einträge,
Pagination, 404, OAuth-Profilabgleich und bereinigte Fehler.

## Offizielle Quellen

* [Gmail Push und Watch-Erneuerung](https://developers.google.com/workspace/gmail/api/guides/push)
* [Gmail History und Synchronisation](https://developers.google.com/workspace/gmail/api/guides/sync)
* [Gmail History-API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)
* [Gmail Watch-API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch)
* [Gmail Message-List-API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
* [Google OAuth und Offline-Zugriff](https://developers.google.com/identity/protocols/oauth2/web-server#offline)
* [Pub/Sub authentifizierte Push-Subscriptions](https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions)
* [Render Persistent Disks](https://render.com/docs/disks)
* [Render Free-Limits](https://render.com/docs/free)
* [Google Compute Engine Persistent Disk](https://cloud.google.com/compute/docs/disks/persistent-disks)
* [GitHub Actions Events und Schedule-Verzögerungen](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

Die oben verlinkten Dokumentationen wurden am 08.10.2026 über HTTPS erfolgreich
abgerufen. Es wurden keine API-Endpunkte, Tokens oder ALDI-Angebotsdaten
erfunden und keine externen Ressourcen angelegt.
