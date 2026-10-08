# Start unter Windows

1. [Docker Desktop fuer Windows installieren](https://docs.docker.com/desktop/setup/install/windows-install/).
   Den WSL-2-Modus verwenden, den Rechner neu starten, falls der Installer dies
   verlangt, und Docker Desktop starten. Linux-Container muessen laufen.
2. Den [aktuellen V5-Zweig als ZIP herunterladen](https://github.com/chhubeny90-cell/aldi-watcher/archive/refs/heads/feature/v5-event-lite.zip)
   und vollstaendig entpacken.
3. Im entpackten Repository PowerShell oeffnen und ausfuehren:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\v5\windows-login.ps1
```

Die ExecutionPolicy gilt nur fuer diesen Aufruf. Das Skript prueft Docker,
baut das Image und fragt danach lokal Rufnummer und Passwort ab. Die
Passworteingabe bleibt verborgen. Zugangsdaten werden nicht in Dateien oder
Docker-Kommandozeilenargumenten gespeichert; sie werden dem kurzlebigen
Login-Test ueber dessen Prozessumgebung uebergeben und danach entfernt.
Bestehende Werte der aufrufenden Prozessumgebung werden wiederhergestellt.

Der Test prueft ausschliesslich den Login. Er startet keinen Mailmonitor und
bucht nichts. Gmail-Zugaenge oder ein ausgefuelltes `.env.v5` sind fuer diesen
ersten Test nicht erforderlich. Bei einem Fehler nur `error_class` mitteilen.

Danach Account, Gratisangebot und Mailtrigger nach dem
[Runbook](v5-runbook.md) verifizieren. Ein erfolgreicher Login allein bedeutet
noch keinen laufenden Nachbuchungsbetrieb. Fuer den spaeteren Dauerbetrieb
muessen Windows und Docker laufen; im Energiesparmodus startet kein Bot.
