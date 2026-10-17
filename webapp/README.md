# Unlimited Filmmodus – automatische lokale Web-Oberfläche

1. Server starten:

```bash
pip install -r requirements.txt
pip install flask
python webapp/app.py
```

2. Am iPhone in Safari öffnen:

```text
http://DEINE-PC-IP:8000
```

3. Beim ersten Öffnen Anbieter, Rufnummer/E-Mail und Passwort eingeben.
4. Die Zugangsdaten werden nur lokal in `webapp/local_config.json` gespeichert.
5. Danach genügt ein Tipp auf „Unlimited Filmmodus starten“.

Wichtig: Teste zuerst mit einem eigenen Konto und deaktiviertem Auto-Buchungsmodus. Fremde Rufnummern oder Zugangsdaten dürfen nicht verwendet werden.

ALDI bucht ab 1,0 GB unbegrenzt oft je 1 GB. Lidl bucht einen verifizierten kostenlosen 1-GB-Refill, sobald er verfügbar ist; dafür müssen die Lidl-Selektoren in `.env` hinterlegt sein.
