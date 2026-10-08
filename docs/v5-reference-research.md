# V5: öffentliche technische Referenzen

Untersucht am **08.10.2026**, ausschließlich lesend. Keine fremden Skripte ausgeführt,
keine Nachbuchung ausgelöst und kein fremder Quellcode in LITE übernommen.
Die folgenden Endpunkte und Datenfelder sind durch Repository-Code belegt;
damit ist ihre aktuelle Funktion für den Benutzeraccount **nicht** bestätigt.

## Ergebnis

Die brauchbarsten Erkenntnisse sind die reguläre CIAM/OIDC-Anmeldekette,
Webkomponenten mit offenem Shadow DOM sowie dynamisch ermittelte
Vertrags-/Angebotsdaten. Keine untersuchte Referenz bietet den für V5 geforderten
Preisnachweis, dauerhafte Idempotenz und unabhängige Erfolgskontrolle zusammen.
E-Mail-basierte Auslösung ist bei keiner dieser vier Referenzen implementiert.

| Referenz | geprüfter Stand | Lizenz | praktisch brauchbar | verworfen |
| --- | --- | --- | --- | --- |
| [Otmanraad/auto-aldi-talk](https://github.com/Otmanraad/auto-aldi-talk) | `fb788ac38ca81efa386b3b7d2de66a0a0b752342`, 13.07.2025 | AGPL-3.0 | BFF-Leseendpunkte, existierender `updateUnlimited`-Request | erster Vertrag/erstes Angebot, feste Verbrauchsschwellen, Endlosschleife, Klartext-Cookies, keine Preissicherung |
| [subhamgrv/Mobile-Network-Auto-Refill-Bots](https://github.com/subhamgrv/Mobile-Network-Auto-Refill-Bots) | `15becd98df2a8cd890160883ba773f12bb17ed1e`, 13.07.2026; ALDI-Code im Juli 2026 aktualisiert | keine Lizenzdatei erkannt | CIAM-Webkomponenten, Shadow-DOM-Login | generisches Klicken auf „1 GB“, keine Preis-/Accountprüfung, keine Buchungsbestätigung |
| [JonasJoKuJonas/homeassistant-AldiTalk](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk) | `8d0b432e61094c4dc316b04c4180d276be577e41`, 02.09.2026 | MIT | nachvollziehbarer Login, OIDC-Redirects, Datenformatkorrekturen | nur Sensorik, kein produktiver Nachbuchungsweg |
| [Mxxel/AldiTalk-Unlimited](https://github.com/Mxxel/AldiTalk-Unlimited) | `fc398eb859fe797d0d00fab26b2c7a3190e176a3`, 29.09.2026 | keine Lizenzdatei erkannt | neuere Playwright-Loginhinweise | permanenter Browser, periodisches Reload, beliebiger kreisförmiger Button, keine Preis-/Erfolgskontrolle |

Fehlende Lizenz bedeutet: keinen Quellcode kopieren. Bei AGPL-Wiederverwendung
müssen die Lizenzpflichten gesondert eingehalten werden; hier wurden nur technische
Konzepte untersucht. Kein Repository war archiviert. Die GitHub-Issue-Abfragen
für Otmanraad, subhamgrv und Mxxel lieferten keine Threads; das ist kein
Funktionsnachweis. Homeassistant hat aktuelle Fehlerberichte und Fixes.

## Offizielle Tarifbedingungen: live gelesen

Die [offizielle ALDI-TALK-Seite zu Unlimited GB nachbuchen](https://www.alditalk.de/tarife-unlimited-gb-nachbuchen)
wurde am 08.10.2026 öffentlich gelesen. Ihre FAQ nennt „Unlimited on Demand S, M, L“
und sagt ausdrücklich:

> Sobald dein verfügbares Datenvolumen weniger als 1 GB beträgt, kannst du über
> die ALDI TALK App oder online über das Kundenportal weiteres Datenvolumen in
> 1 GB-Schritten nachbuchen – kostenlos und so oft du möchtest.

Die Produktkarten nennen aktuell „Tarif S“, „Tarif M“, „Tarif L“; die Fußnote
nennt 25 / 50 / 100 GB anfängliches Inklusivvolumen. Diese öffentliche Beschreibung
beweist weder den gebuchten Tarif des Benutzeraccounts noch den konkreten Preis
seines aktuellen Angebots. Die operative Schwelle ist **weniger als 1 GB**, nicht
pauschal 80 % Verbrauch. Die 80-%-Mail bleibt ausschließlich ein Ereignis zur
aktuellen Zustandsprüfung. Tarifkennung und Buchungspreis müssen im eigenen
Kundenportal festgestellt werden.

## Authentifizierung: konkrete Quellen

[subhamgrv/aldi.py](https://github.com/subhamgrv/Mobile-Network-Auto-Refill-Bots/blob/15becd98df2a8cd890160883ba773f12bb17ed1e/aldi.py)
verwendet `https://login.alditalk-kundenbetreuung.de/signin/XUI/#login/` und:

- `one-input#idToken3_od` für die Rufnummer;
- `one-input#idToken4_od` für das Passwort;
- offene Shadow Roots mit internen `input`-Elementen;
- versteckte Callback-Inputs `idToken3` / `idToken4`;
- `one-button#IDToken5_4_od_2` mit internem `[part="base"]` für „Anmelden“.

Dies sind fremdbelegte Selektoren, **keine live bestätigten Selektoren**.
Ein regulärer Browser sollte zunächst seine normalen Eingabeereignisse auslösen;
keine beliebigen versteckten Werte oder Callback-IDs erfinden.
Im öffentlichen Beispielcode stehen credentialartige Literalwerte. Diese wurden
nicht übernommen und werden hier weder zitiert noch als Testzugang verwendet.
Screenshots und HTML können persönliche Kontoinformationen enthalten und gehören
nicht ungeprüft in öffentliche Actions-Artefakte.

[Homeassistant/aldi_talk.py](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/blob/8d0b432e61094c4dc316b04c4180d276be577e41/custom_components/aldi_talk/aldi_talk.py)
zeigt einen Requests-basierten ForgeRock/OIDC-Ablauf:

1. Portalübersicht `https://www.alditalk-kundenportal.de/portal/auth/uebersicht/`
   mit Redirects öffnen, um die normale Portalanmeldung zu starten.
2. `POST https://login.alditalk-kundenbetreuung.de/signin/json/authenticate`
   mit `realm=/alditalk`, `authIndexType=service`, `authIndexValue=Login`.
3. Callback-Antwort auswerten; `NameCallback` und `PasswordCallback` dynamisch
   mit den eigenen Zugangsdaten befüllen. `authId` aus genau dieser Antwort erhalten.
4. Die zurückgegebenen `successUrl` und die komplette OIDC-Redirectkette verfolgen;
   erst der Callback setzt die Portalsession.
5. Portalzustand und danach identitätsbezogene Providerdaten prüfen.

Die Referenz enthält auch einen Proof-of-Work-Callback-Solver und ein pauschales
`ConfirmationCallback=2`. Beides darf nicht blind übernommen werden. Für V5 den
regulären Browserweg bevorzugen; MFA, CAPTCHA und persönliche Bestätigungen
melden und nicht umgehen.

Belegte Fehlerkorrekturen in dieser Referenz:

- [PR #7](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/pull/7):
  vorzeitig abgebrochene OIDC-Redirectketten führen zu falschem Loginfehler.
- [PR #11](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/pull/11):
  vor regulärer Neuanmeldung alte abgelaufene Session-Cookies verwerfen.
- [PR #13](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/pull/13):
  transienter Redirectfehler ist nicht gleich falsches Passwort.
- [PR #15](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/pull/15):
  Mengen können Dezimal-/Exponentialstrings sein, z.B. `6.291456E7`;
  Einheiten pro Pack auswerten, nicht `int(raw_string)` verwenden.
- [Issue #9](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/issues/9):
  mehrere Rufnummern sind nicht sauber unterstützt. V5 muss den richtigen
  Vertrag eindeutig zuordnen und darf nicht den ersten Listeneintrag wählen.
- [Issue #2](https://github.com/JonasJoKuJonas/homeassistant-AldiTalk/issues/2):
  kostenlose 1-GB-Nachbuchung weiterhin als offene Erweiterung; diese Integration
  liefert daher keinen belegten Buchungserfolg.

## Nachbuchung: belegte API-Hinweise, keine Live-Freigabe

[Otmanraad/get_data.py](https://github.com/Otmanraad/auto-aldi-talk/blob/fb788ac38ca81efa386b3b7d2de66a0a0b752342/get_data.py)
liest auf `https://www.alditalk-kundenportal.de`:

```text
GET /scs/bff/scs-207-customer-master-data-bff/customer-master-data/v1/navigation-list
GET /scs/bff/scs-209-selfcare-dashboard-bff/selfcare-dashboard/v1/offers/C-{billing-id-suffix}?warningDays=1&contractId={contractId}
```

Das zweite URL-Muster baut der fremde Code durch Entfernen der ersten beiden
Zeichen von `billingAccountId`. Dieses Format muss aus echten Kontodaten bestätigt
werden. Die neuere Homeassistant-Referenz verwendet stattdessen:

```text
GET /scs/bff/scs-209-selfcare-dashboard-bff/selfcare-dashboard/v1/offers?contractId={contractId}&productType=
```

[Otmanraad/request.py](https://github.com/Otmanraad/auto-aldi-talk/blob/fb788ac38ca81efa386b3b7d2de66a0a0b752342/request.py)
sendet per Browser-`fetch`, mit bestehender Session:

```text
POST /scs/bff/scs-209-selfcare-dashboard-bff/selfcare-dashboard/v1/offer/updateUnlimited
```

Die Quellcode-Payload enthält `amount`, `offerId`, `refillThresholdValue`,
`subscriptionId` und `updateOfferResourceID`. `amount` und `refillThresholdValue`
werden dort beide aus `refillThresholdValueUid`, `subscriptionId` aus `contractId`,
`updateOfferResourceID` aus `resourceId` befüllt. Das ist lediglich beobachteter
Fremdcode. Bedeutung, Zulässigkeit, CSRF-Anforderungen und heutige Antwortstruktur
sind **nicht** für diesen Account verifiziert. Keine Tarif-ID, Preisinformation,
Transaktions-ID oder Buchungsbestätigung daraus ableiten.

Die Referenz nimmt beim Extrahieren einfach `subscribedOffers[0]` und
`subscriptions[0]`; sie überprüft keinen Preis und interpretiert HTTP-Ausgabe nicht
als unabhängig bestätigtes Ergebnis. Ein Timeout wird nicht dauerhaft als UNKNOWN
gesichert. Deshalb ist diese Buchungsimplementierung kein geeigneter Live-Ersatz.
Die [README](https://github.com/Otmanraad/auto-aldi-talk/blob/fb788ac38ca81efa386b3b7d2de66a0a0b752342/README.md)
benennt selbst ablaufende Termux-Cookies als Funktionsproblem.

## Konsequenzen für die kleine LITE-Version

- Einmaliger, normaler Login pro relevantem Ereignis; vorhandene gültige Session
  nur sicher wiederverwenden, abgelaufene Session vor erneutem Login entfernen.
- Angebot, Vertrag, Menge und Preis anhand aktueller eigener Providerdaten
  bestätigen. Fehlendes oder mehrdeutiges Ergebnis beendet den Lauf ohne Buchung.
- Nur eindeutig angebotene kostenlose 1 GB ausführen. Kein heuristisches Klicken
  auf einen beliebigen Button und kein Request aus historischen IDs.
- PENDING vor Provideränderung dauerhaft speichern, unklaren Ausgang UNKNOWN
  lassen und erst nach Providerabgleich neue Transaktion erlauben.
- Nach Änderung eine unabhängige Status-/Volumen-/Portalbestätigung einholen.
- Mailtrigger, dauerhafte Datenbank und Recovery selbst ergänzen. Kein gefundenes
  Projekt ersetzt diese Anforderungen; deren Provider-Polling entfällt für V5.

Recherche über GitHub-Repositories zu `aldi-talk`, `aldi talk automation`,
`aldi talk refill` und `aldi talk api`; die exakte `aldi-talk`-Suche lieferte die
beiden zusätzlichen Referenzen. Andere Treffer wurden nicht als geprüfte Quellen
gewertet. Alle Aussagen beziehen sich auf die oben festgehaltenen Commits.
