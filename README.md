# ewbot – Elliott-Wave-Trading-Bot für Crypto.com

## Kernaussage zuerst

- **Was er macht:** Der Bot beobachtet rund um die Uhr Bitcoin, Ether, Solana und Gold (PAXG) an der
  Crypto.com Exchange. Er sucht in den Kursen nach typischen Elliott-Wellen-Mustern und kauft, wenn
  eine Korrektur wahrscheinlich vorbei ist und die nächste Aufwärtswelle beginnt. Jeder Trade hat
  sofort einen Stop-Loss (Verlustbegrenzung) und zwei Kursziele.
- **Zwei Bots parallel:** einer handelt auf 15-Minuten-Kerzen (`ewbot-15m`), einer auf 30-Minuten-Kerzen
  (`ewbot-30m`). Beide nutzen die 1-Stunden- und 4-Stunden-Kerzen als Richtungsfilter.
- **Standard ist Papierhandel:** Nach der Installation handelt der Bot nur mit Spielgeld (20 USD). Erst wenn
  Sie in der Konfiguration `mode: live` eintragen, werden echte Orders geschickt.
- **Keine Gewinngarantie.** Elliott-Wellen sind eine Deutung, keine Gesetzmäßigkeit. Mit 5 % Risiko pro
  Trade können wenige Verlusttrades in Folge das Konto deutlich verkleinern. **Die eingesetzten 20 Euro
  können komplett verloren gehen.** Setzen Sie nur Geld ein, dessen Verlust Sie verkraften.

---

## Inhalt

1. [Elliott-Wave-Logik in einfachen Worten](#1-elliott-wave-logik-in-einfachen-worten)
2. [Risiko- und Geldmanagement](#2-risiko--und-geldmanagement)
3. [Voraussetzungen](#3-voraussetzungen)
4. [Installation auf einem Oracle-Cloud-Server, Schritt für Schritt](#4-installation-auf-einem-oracle-cloud-server-schritt-für-schritt)
5. [Von Papierhandel auf echten Handel umschalten](#5-von-papierhandel-auf-echten-handel-umschalten)
6. [Telegram einrichten](#6-telegram-einrichten)
7. [Backtest ausführen](#7-backtest-ausführen)
8. [Befehle](#8-befehle)
9. [Wichtige Einstellungen](#9-wichtige-einstellungen)
10. [Offene Punkte und Annahmen](#10-offene-punkte-und-annahmen)
11. [Risikohinweise](#11-risikohinweise)

---

## 1. Elliott-Wave-Logik in einfachen Worten

**Wellen.** Kurse bewegen sich nicht gerade, sondern im Zickzack. Die Elliott-Theorie sagt: Ein Trend
besteht aus **fünf Wellen** (1 bis 5). Die Wellen 1, 3 und 5 laufen in Trendrichtung, die Wellen 2 und 4
sind Rücksetzer. Danach folgt meist eine **Korrektur aus drei Wellen** (A, B, C) gegen den Trend.

```
            5
      3    / \          A-B-C = Korrektur
     / \  /   \    B
 1  /   \/     \  / \
/ \/     4      \/   \
   2             A    C
```

**Feste Regeln**, die der Bot nie verletzt (sonst ist es keine gültige Zählung):
- Welle 2 fällt nie unter den Startpunkt von Welle 1.
- Welle 3 ist nie die kürzeste der Wellen 1, 3 und 5.
- Welle 4 läuft nicht in den Bereich von Welle 1 hinein.

**Fibonacci-Zonen.** Rücksetzer enden häufig bei bestimmten Anteilen der vorherigen Welle, zum Beispiel
38,2 %, 50 % oder 61,8 %. Der Bot bewertet jede mögliche Wellenzählung danach, wie gut sie zu diesen
Verhältnissen passt (Punktzahl 0 bis 1). Nur saubere Muster werden gehandelt.

**Wie der Bot die Wellen findet.** Er markiert automatisch Hochs und Tiefs (ein Wendepunkt zählt erst,
wenn der Kurs sich um ein Vielfaches der üblichen Schwankung, der „ATR“, zurückbewegt hat). Diese Punkte
versucht er als Wellen 0-1-2-3-4-5 oder A-B-C zu beschriften.

**Die drei Einstiege:**

| Setup | Situation | Einstieg | Stop-Loss | Ziele |
|---|---|---|---|---|
| Welle 3 (`wave3`) | Welle 1 und der Rücksetzer Welle 2 sind fertig | wenn eine Kerze nach Welle 2 wieder steigend schließt | unter dem Start von Welle 1 | TP1 = Länge von Welle 1, TP2 = 1,618 × Welle 1 |
| Welle 5 (`wave5`) | Wellen 1 bis 4 sind fertig | nach dem Ende von Welle 4 | unter dem Tief von Welle 4 | 0,618 × bzw. 1,0 × Welle 1 |
| Welle C (`waveC`) | Korrektur: A und B sind fertig | nach dem Ende von Welle B | hinter dem Ende von Welle B | 1,0 × bzw. 1,618 × Welle A |

**Richtungsfilter 1h + 4h.** Auf den größeren Zeiteinheiten (1 Stunde und 4 Stunden) bestimmt der Bot die
Grundrichtung (steigend / fallend / unklar), aus der Wellenzählung und hilfsweise aus zwei gleitenden
Durchschnitten (EMA 50 / 200). Ein Kauf ist nur erlaubt, wenn keine der beiden Zeiteinheiten fallend ist und
mindestens eine steigend. Liegt der Einstieg zusätzlich nahe an einer Fibonacci-Marke der großen
Zeiteinheit, steigt die Signalqualität.

**Nur Käufe (Long).** An der Spot-Börse kann man nur kaufen und wieder verkaufen, nicht „leerverkaufen“.
Deshalb ist `allow_short: false` eingestellt. Fallende Märkte werden ausgesessen.

---

## 2. Risiko- und Geldmanagement

| Regel | Standardwert | Bedeutung |
|---|---|---|
| Risiko pro Trade | 5 % | Rechnerische Obergrenze: Wird der Stop-Loss getroffen, verliert das Konto höchstens etwa 5 % (inkl. Gebühren). **Auf Spot ohne Hebel wird das selten erreicht:** Die Position ist auf das freie Guthaben begrenzt, bei engen Elliott-Stops liegt das tatsächliche Risiko je Trade meist nur bei 0,1 bis 1 % des Kontos. |
| Mindestabstand Stop | 4 × Kosten | Ein Signal, dessen Stop näher am Einstieg liegt als das 4-Fache der Hin- und Rückweg-Kosten (Gebühren + Schlupf, ca. 0,2 %), wird ausgelassen. Sonst fressen die Gebühren den Trade. (`min_stop_to_cost`) |
| Teilgewinn | 50 % bei TP1 | Am ersten Ziel wird die Hälfte verkauft. |
| Break-even | an | Nach TP1 wird der Stop auf den Einstiegskurs gezogen – der Rest kann dann (fast) nichts mehr verlieren. |
| Tagesverlustgrenze | 15 % | Ist das Konto an einem Tag (UTC) 15 % im Minus, macht der Bot bis Mitternacht UTC keine neuen Trades. |
| Verlustserie | 4 Verluste | Nach 4 Verlusten in Folge 120 Minuten Pause. |
| Max. Positionen | 3 (je Bot), 1 je Markt | Begrenzung gleichzeitiger Trades. |
| Zeitstopp | 96 Kerzen (15m) / 48 Kerzen (30m) | Ein Trade, der nach ca. 24 Stunden nichts erreicht hat, wird geschlossen. |

**Thesaurierung (Zinseszins).** Gewinne werden nicht entnommen. Die Positionsgröße wird bei jedem neuen
Trade aus dem *aktuellen* Kontostand berechnet: Wächst das Konto, werden die Positionen größer; schrumpft
es, werden sie kleiner. Das gilt in beide Richtungen.

**Kleine Konten.** Mit 20 USD sind die Orders sehr klein. Unterschreitet eine Order den Mindestbetrag der
Börse, wird der Trade ausgelassen (steht im Log). Beim Kauf wird nie mehr als das freie Guthaben eingesetzt.

**Zwei Bots, ein Konto.** Laufen beide Bots live auf demselben Konto, sehen sie das gleiche Guthaben, wissen
aber nichts voneinander. Im schlimmsten Fall sind 6 Positionen offen und das Risiko verdoppelt sich. Für den
Anfang ist es sinnvoll, nur **einen** Bot live zu schalten (siehe Abschnitt 5).

---

## 3. Voraussetzungen

- **Crypto.com Exchange-Konto** (die Börse unter crypto.com/exchange – **nicht** die Crypto.com-App; die App
  hat keine passende Handels-API). Konto verifizieren und USD (oder USDT/USDC, siehe Abschnitt 10) einzahlen.
- **API-Key** in der Exchange anlegen (Einstellungen → API Keys):
  - Rechte: **nur Trade (Spot)**. **Keine** Auszahlungsrechte (Withdrawal)!
  - **IP-Whitelist:** nur die öffentliche IP-Adresse Ihres Servers eintragen.
  - API-Key und Secret sicher notieren; das Secret wird nur einmal angezeigt.
- **Ein Server**, z. B. Oracle Cloud Free Tier (dauerhaft kostenlos) mit Ubuntu 22.04 oder 24.04.
  Beide Prozessortypen funktionieren (Ampere-ARM „VM.Standard.A1.Flex“ oder x86 „VM.Standard.E2.1.Micro“).
- Optional: **Telegram** für Nachrichten und Fernsteuerung.

---

## 4. Installation auf einem Oracle-Cloud-Server, Schritt für Schritt

1. **Server anlegen:** In der Oracle-Cloud-Konsole „Instanz erstellen“, Image *Canonical Ubuntu 22.04 oder
   24.04*, Form z. B. *VM.Standard.A1.Flex* (1 OCPU, 6 GB RAM reichen). SSH-Schlüssel herunterladen oder
   eigenen hochladen. Nach dem Start die **öffentliche IP-Adresse** notieren (für die API-Whitelist).
2. **Verbinden** (auf Ihrem PC, im Terminal bzw. in der Windows-Eingabeaufforderung):
   ```bash
   ssh -i pfad/zum/schluessel.key ubuntu@IHRE-SERVER-IP
   ```
   Oracle-Ubuntu-Images verwenden den Benutzer **ubuntu**.
3. **Installieren** (ein Befehl, dauert einige Minuten):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/maehrsteuern/scalp-bot-mt4/claude/elliott-wave-trading-bot-36grv4/deploy/install_oracle.sh | sudo bash
   ```
   Das Skript installiert Python und Git, lädt den Code nach `/opt/ewbot`, richtet eine Python-Umgebung ein,
   legt `/opt/ewbot/.env` an und startet beide Bots im **Papiermodus**. Es kann gefahrlos erneut ausgeführt werden.
   Ist das GitHub-Repository privat, funktioniert `curl` nicht: dann zuerst
   `git clone -b claude/elliott-wave-trading-bot-36grv4 https://github.com/maehrsteuern/scalp-bot-mt4.git /tmp/ewbot`
   (mit GitHub-Token als Passwort) und anschließend `sudo REPO_URL=/tmp/ewbot bash /tmp/ewbot/deploy/install_oracle.sh`.
4. **Zugangsdaten eintragen:**
   ```bash
   sudo nano /opt/ewbot/.env
   ```
   ```
   CRYPTOCOM_API_KEY=ihr-key
   CRYPTOCOM_API_SECRET=ihr-secret
   TELEGRAM_BOT_TOKEN=          (optional, siehe Abschnitt 6)
   TELEGRAM_CHAT_ID=            (optional)
   ```
   Speichern mit `Strg+O`, `Enter`, beenden mit `Strg+X`. Für den Papierhandel sind die API-Keys nicht nötig.
5. **Prüfen:**
   ```bash
   cd /opt/ewbot && .venv/bin/python -m ewbot check --config config/ewbot-15m.yaml
   ```
   Zeigt, ob die Konfiguration gültig ist, welche Zugangsdaten gesetzt sind (nie deren Inhalt) und ob die
   Börse erreichbar ist.
6. **Neu starten und beobachten:**
   ```bash
   sudo systemctl restart ewbot@ewbot-15m ewbot@ewbot-30m
   systemctl status ewbot@ewbot-15m
   journalctl -u ewbot@ewbot-15m -f        # Live-Log, beenden mit Strg+C
   ```
   Die Bots starten nach einem Server-Neustart und nach Abstürzen automatisch neu (nach 10 Sekunden).
7. **Später aktualisieren:**
   ```bash
   sudo bash /opt/ewbot/deploy/update.sh
   ```

Dateien auf dem Server: `/opt/ewbot/state/` (Zustand, offene Positionen), `/opt/ewbot/logs/` (Logdateien,
max. 5 × 5 MB je Bot), `/opt/ewbot/.env` (Zugangsdaten, nur für den Benutzer lesbar).

---

## 5. Von Papierhandel auf echten Handel umschalten

Empfehlung: erst **mindestens 2–4 Wochen Papierhandel** laufen lassen und Ergebnisse ansehen.

1. `.env` mit API-Key und Secret ausfüllen (Abschnitt 4, Schritt 4).
2. Konfiguration öffnen, z. B. nur den 15-Minuten-Bot:
   ```bash
   sudo nano /opt/ewbot/config/ewbot-15m.yaml
   ```
   Die Zeile `mode: paper` im Abschnitt `exchange:` ändern in `mode: live`.
3. Statusdatei des Papierhandels sichern/entfernen, damit keine Spielgeld-Positionen übernommen werden:
   ```bash
   sudo mv /opt/ewbot/state/ewbot-15m.json /opt/ewbot/state/ewbot-15m.paper-backup.json
   ```
4. Prüfen und neu starten:
   ```bash
   cd /opt/ewbot && .venv/bin/python -m ewbot check --config config/ewbot-15m.yaml
   sudo systemctl restart ewbot@ewbot-15m
   journalctl -u ewbot@ewbot-15m -f
   ```
5. Zurück zum Papierhandel: `mode: paper` eintragen und neu starten. Vorher offene echte Positionen mit
   `/close_all` (Telegram) oder an der Börse schließen.

Hinweis: `update.sh` überschreibt Ihre YAML-Änderungen nicht, solange Sie nicht selbst Änderungen im Git
eintragen. Gibt `git pull` einen Konflikt aus, Datei sichern, mit `git -C /opt/ewbot checkout config/` zurücksetzen,
Update ausführen und die Änderung erneut eintragen.

---

## 6. Telegram einrichten

1. In Telegram den Kontakt **@BotFather** öffnen, `/newbot` senden, Namen vergeben. Sie erhalten einen
   **Token** (sieht aus wie `123456789:ABC...`).
2. Ihren neuen Bot in Telegram öffnen und einmal **Start** drücken (sonst darf er Ihnen nicht schreiben).
3. Ihre **Chat-ID** herausfinden: z. B. dem Bot **@userinfobot** schreiben, er antwortet mit Ihrer ID (Zahl).
4. Token und Chat-ID in `/opt/ewbot/.env` eintragen (`TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`).
5. In beiden YAML-Dateien unter `telegram:` `enabled: true` setzen, dann
   `sudo systemctl restart ewbot@ewbot-15m ewbot@ewbot-30m`.

Beide Bots können denselben Telegram-Bot verwenden; jede Nachricht nennt den Instanznamen. Achtung: Ein
Befehl wie `/pause` wirkt dann auf **beide** Bots.

**Telegram-Befehle:**

| Befehl | Wirkung |
|---|---|
| `/status` | Modus, Pause ja/nein, Kontostand, Tagesergebnis, offene Positionen, letzte Kerze je Markt |
| `/equity` | Kontostand und Tagesergebnis |
| `/positions` | offene Positionen mit Stop, Zielen und aktuellem Gewinn/Verlust |
| `/pause` | keine neuen Trades mehr; offene Trades werden weiter verwaltet |
| `/resume` | Pause aufheben |
| `/close_all` | alle offenen Positionen sofort zum Marktpreis schließen |

Zusätzlich kommen Nachrichten bei Signalen, Käufen, Teilverkäufen, Schließungen und täglich um 21:00 UTC
eine Tagesbilanz.

---

## 7. Backtest ausführen

Ein Backtest spielt die Strategie auf vergangenen Kursen durch – mit **genau derselben Entscheidungslogik**
wie im Live-Betrieb, inklusive Gebühren (0,075 %) und Schlupf (0,03 %). Der Bot sieht dabei zu jedem
Zeitpunkt nur Kerzen, die damals schon abgeschlossen waren.

```bash
cd /opt/ewbot
.venv/bin/python -m ewbot backtest --config config/ewbot-15m.yaml --days 90
```

Optionen: `--equity 20` (Startkapital), `--symbols BTC/USD,ETH/USD` (nur bestimmte Märkte),
`--out reports` (Ausgabeordner). Die Kurse lassen sich auch einmal herunterladen und dann offline testen:

```bash
.venv/bin/python -m ewbot fetch --config config/ewbot-15m.yaml --days 180 --out data
.venv/bin/python -m ewbot backtest --config config/ewbot-15m.yaml --csv-dir data
```

Ausgabe: eine Tabelle (Rendite, Trefferquote, Profit-Faktor, maximaler Rückgang, durchschnittliches
Chance-Risiko-Verhältnis, Gebühren, Ergebnis je Setup und Markt) sowie `report.md`, `equity.csv` und
`trades.csv` im Ordner `reports/<instanz>-<datum>/`. Ein guter Backtest ist **kein Beweis** für zukünftige
Gewinne.

| Kennzahl | Bedeutung |
|---|---|
| Rendite | Veränderung des Kontos in Prozent |
| Trefferquote | Anteil der Trades mit Gewinn |
| Profit-Faktor | Summe Gewinne ÷ Summe Verluste (über 1 = profitabel) |
| Max. Drawdown | größter zwischenzeitlicher Rückgang vom Höchststand |
| Ø R-Multiple | durchschnittlicher Gewinn in Vielfachen des eingesetzten Risikos (−1 = voller Stop) |

---

## 8. Befehle

Alle Befehle im Ordner `/opt/ewbot` ausführen (`cd /opt/ewbot`), Python ist `.venv/bin/python`:

| Befehl | Zweck |
|---|---|
| `python -m ewbot run --config config/ewbot-15m.yaml` | Bot starten (macht normalerweise systemd) |
| `python -m ewbot check --config ...` | Konfiguration, Zugangsdaten und Börsenverbindung prüfen |
| `python -m ewbot status --config ...` | gespeicherten Zustand anzeigen (Kontostand, Positionen, letzte Trades) |
| `python -m ewbot backtest --config ... --days 90` | Backtest |
| `python -m ewbot fetch --config ... --days 90 --out data` | Kursdaten als CSV speichern |

Dienst-Befehle:

| Befehl | Zweck |
|---|---|
| `systemctl status ewbot@ewbot-15m` | läuft der Bot? |
| `sudo systemctl restart ewbot@ewbot-15m` | neu starten (z. B. nach Konfigurationsänderung) |
| `sudo systemctl stop ewbot@ewbot-30m` | anhalten |
| `sudo systemctl disable --now ewbot@ewbot-30m` | anhalten und Autostart abschalten |
| `journalctl -u ewbot@ewbot-15m -f` | Live-Log |
| `journalctl -u ewbot@ewbot-15m --since today` | Log von heute |

Beim Stoppen speichert der Bot seinen Zustand; offene Positionen bleiben bestehen und werden nach dem
Neustart weiter verwaltet. Während der Bot gestoppt ist, gibt es **keinen** Stop-Loss-Schutz durch den Bot
(nur, soweit eine Stop-Order an der Börse platziert werden konnte).

---

## 9. Wichtige Einstellungen

Alle Einstellungen stehen kommentiert in `config/ewbot-15m.yaml` bzw. `config/ewbot-30m.yaml`. Die wichtigsten:

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `exchange.mode` | `paper` | `paper` = Spielgeld, `live` = echte Orders |
| `exchange.paper_start_equity` | `20.0` | Startkapital im Papiermodus (USD) |
| `markets` | BTC, ETH, SOL, PAXG | gehandelte Märkte (`/USD`, Spot) |
| `strategy.exec_timeframe` | `15m` / `30m` | Kerzengröße, auf der gehandelt wird |
| `strategy.htf_timeframes` | `[1h, 4h]` | Richtungsfilter |
| `strategy.min_signal_score` | `0.6` | Mindestqualität eines Signals (0–1) |
| `risk.risk_pct` | `5.0` | Risiko pro Trade in % des Kontos |
| `risk.max_positions` | `3` | max. gleichzeitige Positionen pro Bot |
| `risk.daily_loss_cap_pct` | `15.0` | Tagesverlustgrenze in % |
| `risk.tp1_fraction` | `0.5` | Anteil, der bei TP1 verkauft wird |
| `risk.fee_pct` | `0.075` | Gebühr je Seite in % – an Ihre Gebührenstufe anpassen |
| `telegram.enabled` | `false` | Telegram an/aus |
| `telegram.daily_summary_utc` | `"21:00"` | Uhrzeit der Tagesbilanz (UTC) |

Nach jeder Änderung: `sudo systemctl restart ewbot@<instanz>`. Ein Tippfehler in der YAML-Datei wird beim
Start gemeldet (`check` zeigt ihn ebenfalls).

---

## 10. Backtest-Ergebnis (Stand 11.11.2026)

120 Tage echte Crypto.com-Kurse (13.07. bis 10.11.2026), vier Märkte, 20 USD Start, Gebühren 0,075 % je
Seite, Schlupf 0,03 %. Berichte liegen in `docs/backtests/`.

| Bot | Trades | Trefferquote | Profit-Faktor | Ergebnis | Max. Rückgang |
|---|---|---|---|---|---|
| ewbot-15m | 12 | 66,7 % | 3,04 | +9,0 % | 5,2 % |
| ewbot-30m | 7 | 42,9 % | 0,63 | -2,1 % | 5,5 % |

Einordnung: 12 bzw. 7 Trades in vier Monaten sind zu wenig, um einen Vorteil zu belegen. Ein Parameter-Test
(Umkehrschwelle 1,5 / 2,0 / 2,5 × ATR, Signalalter 3 / 6 / 10 Kerzen) zeigte: Lockerere Einstellungen bringen
mehr Trades, aber Verluste; die Standardwerte (2,0 × ATR, 3 Kerzen) waren auf 15 Minuten in allen Varianten
positiv, auf 30 Minuten meist negativ. Empfehlung: zuerst den 15-Minuten-Bot im Papierhandel laufen lassen,
den 30-Minuten-Bot nur beobachten.

---

## 11. Offene Punkte und Annahmen

- **Kontowährung USD.** Die Märkte heißen `BTC/USD` usw. Crypto.com führt Paare teils gegen USD, teils
  gegen USDT/USDC. `check` zeigt, ob alle Märkte gefunden werden. Liegt Ihr Guthaben z. B. in USDT, müssen
  `quote: USDT` und die Märkte (`BTC/USDT`, ...) angepasst werden.
- **Euro.** Die „20 Euro“ werden als ca. 20 USD Guthaben angenommen; der Bot rechnet in der Kontowährung.
- **Mindestgrößen.** Bei sehr kleinen Konten können Orders unter dem Börsenminimum liegen und werden dann
  ausgelassen. Ob 20 USD für alle vier Märkte reichen, zeigt erst der Betrieb.
- **Stop-Loss an der Börse.** Der Bot überwacht Stops selbst (nach jeder abgeschlossenen Kerze) und
  versucht zusätzlich eine Stop-Order an der Börse zu hinterlegen. Gelingt das nicht (je nach Markt), wird
  ein Stop erst nach Kerzenschluss ausgeführt – bei schnellen Bewegungen kann der Verlust größer als geplant sein.
- **Zwei Bots, ein Konto:** siehe Abschnitt 2. Die Bots stimmen sich nicht ab.
- **Elliott-Zählung ist mehrdeutig.** Der Bot wählt die Zählung mit der besten Fibonacci-Punktzahl; ein
  erfahrener Analyst könnte anders zählen.
- **Keine Leerverkäufe** auf Spot. Perpetual-Futures (`BTC/USD:USD`, `allow_short: true`) sind technisch
  vorbereitet, aber nicht getestet und nicht empfohlen.
- **Gebührenstufe prüfen.** Der Bot rechnet mit 0,075 % je Seite (Crypto.com Exchange, Einstiegsstufe laut
  Drittquellen). Die eigene Stufe steht im Exchange unter „Fees“. Ist sie höher, `fee_pct` anpassen; bei
  0,5 % je Seite ist die Strategie nicht tragfähig.
- **Backtest-Grenzen:** Innerhalb einer Kerze wird angenommen, dass bei gleichzeitigem Stop und Ziel der
  Stop zuerst getroffen wurde (vorsichtig). Echte Ausführungen können abweichen.

---

## 12. Risikohinweise

- Der Handel mit Kryptowährungen ist hochriskant. Kurse können innerhalb von Minuten stark fallen.
- **Totalverlust ist möglich.** Das gesamte eingesetzte Kapital kann verloren gehen.
- Vergangene Ergebnisse (Backtest, Papierhandel) sagen nichts Sicheres über die Zukunft.
- Technische Fehler (Server-Ausfall, Internet, Börsenstörung, Programmfehler) können zu Verlusten führen.
- API-Keys **niemals** mit Auszahlungsrechten anlegen und immer per IP-Whitelist auf den Server beschränken.
  Die Datei `.env` niemals weitergeben oder in Git hochladen.
- Gewinne aus Kryptowährungen können steuerpflichtig sein (in Deutschland u. a. § 23 EStG,
  Haltefrist 1 Jahr). Der Bot erzeugt viele kurzfristige Trades – `trades.csv` und die Börsen-Exporte aufbewahren.
- Diese Software ist keine Anlageberatung. Nutzung auf eigenes Risiko.
