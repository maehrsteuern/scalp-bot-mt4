# Handover – ewbot (Elliott-Wave-Bot für Crypto.com) – Stand 11.11.2026

## Status
- Repo `maehrsteuern/scalp-bot-mt4`, Branch `claude/elliott-wave-trading-bot-36grv4`. Alles committet und gepusht. Nie auf main.
- Alte MT4-EAs liegen unverändert in `legacy/` (Scalping brachte keinen Gewinn, daher Neubau).
- Python-Paket `ewbot/`: swings (ATR-ZigZag), fib, elliott (Impuls 1-5 / Zigzag A-B-C mit Fib-Score), strategy (Welle-3-, Welle-5-, Welle-C-Einstiege, 1h+4h als Richtungsfilter + Fib-Konfluenz), risk, broker (Paper + ccxt Crypto.com), data, state, notify (Telegram), bot (Loop), backtest, CLI (`python -m ewbot run|backtest|fetch|status|check`).
- 92 Tests grün (`python3 -m pytest -q`). Audit auf Look-ahead und Live-Sicherheit durchgeführt, 7 Befunde behoben.
- Deploy: `deploy/install_oracle.sh`, `deploy/ewbot@.service` (systemd-Template, Instanzen `ewbot-15m`, `ewbot-30m`), `deploy/update.sh`. README (deutsch) mit Schritt-für-Schritt-Anleitung.
- Beide Konfigurationen stehen auf `mode: paper`, 20 USD Papierkapital, Telegram aus.

## Entscheidungen (von Loris)
- Python-Bot auf Crypto.com Exchange via ccxt (nicht MT4), PAXG als Gold.
- Paper zuerst, dann Live. 5 % Risiko, BTC/ETH/SOL/PAXG, Tagesverlustgrenze 15 %.
- Exchange ist per `exchange.id` austauschbar (Bybit/Kraken/Binance = Konfig + kurzer Test).

## Backtest 120 Tage (echte Kurse, Berichte in docs/backtests/)
- 15m: 12 Trades, +9,0 %, PF 3,04, Max-DD 5,2 %. 30m: 7 Trades, -2,1 %, PF 0,63.
- Zu wenig Trades für einen Beleg. Parameter-Sweep: lockerere Schwellen = mehr Trades, aber Verlust. Standard (2,0 × ATR, 3 Kerzen) bleibt.
- Realität Spot + 20 USD: Position ist auf freies Guthaben gedeckelt, effektives Risiko je Trade 0,1-1 %, nicht 5 %. Mehr Risiko ginge nur über Perps (vorbereitet, ungetestet, nicht empfohlen).

## Offen / Nächste Schritte
1. Auf dem Oracle-VPS installieren (README Abschnitt 4), 15m-Bot im Paper-Modus 1-2 Wochen laufen lassen, Log und `status` prüfen.
2. Gebührenstufe im Crypto.com Exchange prüfen; falls > 0,075 % je Seite `fee_pct` anpassen.
3. Crypto.com-API-Key (Trade, kein Withdrawal, IP-Whitelist VPS) und Telegram in `/opt/ewbot/.env` eintragen.
4. Erst dann **einen** Bot auf `mode: live` schalten.
5. Technisch offen: Perps/Shorts ungetestet; Stop-Order an der Börse ist Best-effort; beide Bots stimmen sich auf einem Konto nicht ab.

## Umgebung / Hinweise für die nächste Session
- Sandbox: api.crypto.com erreichbar, aber ccxt braucht `session.trust_env = True` (ist im Code gesetzt).
- Kursdaten (CSV, 120 Tage, 4 Märkte, 15m/30m/1h/4h) liegen nur im Scratchpad der alten Session; neu laden mit `python -m ewbot fetch -c config/ewbot-15m.yaml --days 120 --out data/`.
- Opus-Agenten hatten einmal ein 5-Stunden-Limit; Fix-Agent danach fortgesetzt.

## Start-Prompt nächste Session
„Lies docs/HANDOVER.md im Repo maehrsteuern/scalp-bot-mt4 (Branch claude/elliott-wave-trading-bot-36grv4). Der ewbot läuft seit X Tagen im Paper-Modus auf dem Oracle-VPS. Hier der Auszug aus `python -m ewbot status` und dem Log: … Bewerte die Signale, schlage Parameteränderungen vor und bereite den Live-Start des 15m-Bots vor.“
