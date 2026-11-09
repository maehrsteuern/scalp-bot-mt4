# Bot auf einem kleinen Server (VPS) betreiben

Ziel: Der Bot läuft rund um die Uhr, startet nach einem Neustart von selbst und kann jederzeit gestoppt werden.
Erst Paper-Modus, später live. Dauerlauf = `python -m ewbot run`.

## 1. Server mieten

- Z. B. **Hetzner Cloud CX22** (2 vCPU, 4 GB RAM), Ubuntu 24.04. Preis **ungefähr 4–5 € pro Monat** (Preis ändert sich, bitte
  auf der Hetzner-Seite prüfen). Jeder kleine Ubuntu-Server reicht.
- SSH-Schlüssel hinterlegen (kein Passwort-Login). Notiere die **feste IPv4-Adresse** – sie kommt in die API-Whitelist.

## 2. Erste Einrichtung (als root)

```bash
apt update && apt -y upgrade
apt -y install python3 python3-venv git chrony ufw logrotate
adduser --disabled-password --gecos "" ewbot          # eigener Benutzer ohne Root-Rechte
ufw allow OpenSSH && ufw --force enable               # Firewall: nur SSH
systemctl enable --now chrony                         # Zeit-Synchronisierung (wichtig: die API-Signatur braucht eine genaue Uhr)
timedatectl                                           # "System clock synchronized: yes" prüfen
```

## 3. Bot installieren (als Benutzer ewbot)

```bash
su - ewbot
git clone -b wip-crypto-ew-bot <URL-DEINES-REPOS> repo
cd repo/crypto-ew-bot
bash deploy/install.sh        # legt .venv an, installiert Pakete, kopiert config.yaml und .env-Vorlage
```

`deploy/install.sh` ändert nichts an System-Dateien. Den systemd-Dienst richtest du danach als root ein (Schritt 5).

## 4. Geheimnisse und Config

```bash
nano .env          # nur bei Live nötig: CDC_API_KEY=...  CDC_API_SECRET=...
chmod 600 .env     # nur du darfst die Datei lesen
nano config.yaml   # capital_usd, risk_pct ... ; live_enabled bleibt erst einmal false
```

API-Key nur mit Recht "Handeln", **ohne Auszahlung**, mit IP-Whitelist (siehe README).

## 5. Dienst einrichten (als root)

```bash
cp /home/ewbot/repo/crypto-ew-bot/deploy/ewbot.service /etc/systemd/system/ewbot.service
# Pfade in der Datei prüfen (User ewbot, Ordner /home/ewbot/repo/crypto-ew-bot)
systemctl daemon-reload
systemctl enable --now ewbot       # startet jetzt und nach jedem Neustart
systemctl status ewbot             # soll "active (running)" zeigen
journalctl -u ewbot -f             # Log live ansehen (Strg+C beendet nur die Ansicht)
```

Der mitgelieferte Dienst startet im **Paper-Modus**. Für live: in der Datei die Zeile `ExecStart=` auf
`... run --mode live --confirm-live` ändern, vorher `live_enabled: true` in `config.yaml` setzen, dann
`systemctl daemon-reload && systemctl restart ewbot`. `Restart=always` startet den Bot nach einem Absturz neu –
der Zustand liegt in `state/*.json` und wird beim Start mit der Börse abgeglichen.

## 6. Log-Rotation

Der Bot schreibt `logs/ewbot.log` und rotiert selbst (2 MB, 5 Dateien). Das systemd-Journal rotiert Ubuntu automatisch.
Zusätzlich (optional) als root `/etc/logrotate.d/ewbot`:

```
/home/ewbot/repo/crypto-ew-bot/logs/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

## 7. Updates einspielen

```bash
su - ewbot
cd repo/crypto-ew-bot
git fetch && git checkout wip-crypto-ew-bot && git pull
. .venv/bin/activate && pip install -r requirements.txt 2>/dev/null || pip install requests pyyaml
python -m pytest -q                  # Tests müssen grün sein
exit
sudo systemctl restart ewbot         # (als root)
```

Offene Positionen bleiben im Zustand erhalten. Starte neu am besten, wenn keine Position offen ist (`python -m ewbot status`).

## 8. Stoppen

- **Sanft:** `systemctl stop ewbot` – der Bot beendet den Durchlauf. **Achtung:** Danach gibt es keinen Stop mehr für offene Positionen!
- **Not-Aus ohne Dienst zu stoppen:** `python -m ewbot kill` (keine neuen Trades, Einstiege stornieren) oder
  `python -m ewbot kill --flatten` (zusätzlich Positionen verkaufen).
  - `kill` **immer im Bot-Ordner** ausführen (`cd /home/ewbot/repo/crypto-ew-bot`, das ist `WorkingDirectory` im Dienst) – sonst
    legt der Befehl die Datei `state/KILL` an einem anderen Ort an und der Bot sieht sie nicht.
  - `kill` schreibt nur die Datei; der **laufende Bot** führt sie innerhalb einer Minute aus. Ohne laufenden Bot passiert nichts.
- **Dauerhaft:** `systemctl disable --now ewbot`, danach Orders in der Crypto.com-Oberfläche prüfen und den API-Key löschen.

## 8a. Wichtig: Ohne laufenden Prozess gibt es KEINEN Stop-Schutz

Der Stop-Loss ist **synthetisch** (der Bot prüft ihn selbst, die Börse kennt ihn nicht). Ist der Bot aus, abgestürzt oder
der Server weg, wird nichts verkauft, auch wenn der Kurs weit unter den Stop fällt. Deshalb:

- Der Dienst nutzt `Restart=always` (siehe `deploy/ewbot.service`, ist gesetzt, `RestartSec=10`). Nach einem Absturz oder
  Neustart läuft der Bot von selbst weiter, holt verpasste Kerzen nach und prüft alle Stops. Nach Pausen eröffnet er aus alten
  Kerzen **keine** neuen Einstiege.
- `systemctl status ewbot` regelmäßig ansehen, bei offener Position besonders.
- **Mögliche spätere Sicherung (NICHT aktiv, nicht geprüft):** ein Stop-Loss-Auftrag direkt bei der Börse (`STOP_LOSS` bei
  `private/create-order`). Ob und wie das für Spot bei Crypto.com funktioniert, ist nicht verifiziert; der Bot nutzt es heute nicht.
  Bis dahin ist der Stop nur so zuverlässig wie der Server.

## 9. Täglicher Blick (1 Minute)

`python -m ewbot status` und `journalctl -u ewbot -n 50`. Bei "FEHLER"-Zeilen oder "Sperre neue Trades: JA" erst Ursache klären
(`status --clear-halt` erst, wenn der Abgleich mit der Börse stimmt).
