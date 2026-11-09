# crypto-ew-bot – Elliott-Wave Swing-Bot für Crypto.com

## Was macht das?

Der Bot sucht auf dem 30-Minuten-Chart nach Elliott-Wave-Setups (ein Regelwerk, Kursmuster in Wellen zu deuten) für
**BTC, ETH und SOL** (nur USD-Paare, Spot, nur Kaufen = "Long", kein Hebel, keine Derivate). Der 4-Stunden-Chart dient als
Trendfilter. Pro Coin gibt es höchstens **eine** Position.

Ablauf pro Trade:

1. **Limit-Kauf** zum Einstiegspreis. Wird er bis zum Ablauf nicht ausgeführt (oder erreicht der Kurs vorher Ziel 1), wird er gelöscht.
2. Nach dem Kauf liegen zwei Limit-Verkäufe bereit: **50 % bei Ziel 1**, der **Rest bei Ziel 2**.
3. Der **Stop-Loss** ist "synthetisch": Der Bot prüft den Kurs selbst und verkauft zum Marktpreis, wenn der Stop erreicht ist.
4. Wird Ziel 1 erreicht, rutscht der Stop auf den Einstiegspreis (Break-even = kein Verlust mehr möglich, außer durch Kurslücken).

Positionsgröße = Risiko in USD ÷ (Einstieg − Stop). Standard: 0,75 % vom Kapital pro Trade, höchstens 90 % des Kapitals
investiert, Tagesverlust-Limit 2 % (danach bis zum nächsten UTC-Tag keine neuen Einstiege).

## Ehrliche Grenzen (bitte lesen)

- **Keine Gewinn-Garantie.** Elliott-Wellen sind Deutung. Lies `BACKTEST.md` (falls vorhanden): Wenn der Vorteil dort schwach
  oder negativ aussieht, ist er das auch.
- **Der Stop liegt nicht bei der Börse.** Er wird vom Bot geprüft (Kerzen im Paper-Schritt, Kurs jede Minute im Dauerlauf).
  Läuft der Bot nicht oder fällt das Internet aus, gibt es **keinen Stop**. Darum: VPS mit Neustart (siehe `VPS_SETUP.md`).
- Bei Kurslücken oder schnellen Märkten wird zum Marktpreis verkauft – der Verlust kann größer sein als geplant.
- Gebühren und Slippage (Preisabweichung) sind **Annahmen** (0,25 % Limit / 0,50 % Market). Prüfe deine echten Gebühren.
- Im Paper-Modus werden Kerzen von 30 Minuten simuliert. Was innerhalb einer Kerze passiert, ist unbekannt. Der Bot nimmt
  den **schlechteren** Fall an (Berührt eine Kerze Stop und Ziel, zählt der Stop).
- Steuern: Verkäufe sind in Deutschland ggf. nach § 23 EStG relevant. Der Bot führt dafür ein Journal (`state/journal_*.csv`),
  ersetzt aber keine Steuerberatung.
- Das ist keine Anlageberatung.

## Installation

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install requests pyyaml pytest
cp config.example.yaml config.yaml      # bei Bedarf anpassen
python -m pytest -q                      # Tests
```

## Benutzung

| Befehl | Was passiert |
|---|---|
| `python -m ewbot scan` | Holt öffentliche Kurse (kein Key nötig), sucht Signale, schreibt `out/signals.json` und `out/index.html` (Handy-Seite mit Levels, Kerzen, Rechner). |
| `python -m ewbot paper-step --state state/paper.json` | Ein Schritt im Übungskonto: verarbeitet alle seit dem letzten Schritt geschlossenen 30-Minuten-Kerzen, schreibt Zustand + Seite, druckt eine kurze JSON-Zusammenfassung. Zweimal mit denselben Kerzen ausgeführt ändert er nichts. Gedacht für einen Lauf alle 4 Stunden. |
| `python -m ewbot paper-step --seed-manual signals/manual_2026-11-08.json` | Startet das Übungskonto mit den drei manuellen Signalen vom 08.11.2026 (gültig bis 10.11.2026 22:50 UTC). Wirkt nur beim ersten Start bzw. für noch nicht bekannte Signale. |
| `python -m ewbot run --mode paper` | Dauerlauf im Übungskonto (jede Minute Kurs-Check). |
| `python -m ewbot run --mode live --confirm-live` | Dauerlauf mit **echtem Geld** (nur mit allen Schutzschaltern, siehe unten). |
| `python -m ewbot status` | Zeigt Eigenkapital, Positionen, Kill-Schalter. `--mode live` für das Live-Konto, `--clear-halt` hebt die Sperre auf. |
| `python -m ewbot kill` / `kill --flatten` | Not-Aus (siehe unten). |

Alle Einstellungen stehen in `config.yaml` (Vorlage: `config.example.yaml`): Kapital, Risiko %, Gesamt-Limit, Tagesverlust-Limit,
Coins, Gebühren-Annahmen, Pfade.

## Live-Betrieb: die drei Schutzschalter

Echtes Geld wird nur bewegt, wenn **alle drei** stimmen:

1. `live_enabled: true` in `config.yaml`
2. `CDC_API_KEY` und `CDC_API_SECRET` sind gesetzt (Datei `.env` oder Umgebung)
3. Start mit `--confirm-live`

Fehlt eins davon, startet der Bot nicht und sagt dir, was fehlt. Beim Start erscheint eine deutliche Warnung.
Empfehlung: **mindestens 2–4 Wochen Paper-Betrieb**, dann live mit einem kleinen Betrag (`max_capital_usd` klein setzen).

Der Bot hebt nie Geld ab, überweist nichts, nutzt kein Margin/Derivate und handelt nur BTC_USD, ETH_USD, SOL_USD.
Er verkauft **nur Mengen, die er selbst gekauft hat** (steht im Zustand). Bei unklarem Zustand oder API-Fehlern eröffnet er
keine neuen Trades, kümmert sich aber weiter um die Stops.

### API-Key bei Crypto.com erstellen (nur Handel, keine Auszahlung)

1. Bei der **Crypto.com Exchange** (nicht der App) anmelden, 2-Faktor-Anmeldung aktivieren.
2. Einstellungen → **API-Schlüssel** → neuen Schlüssel erstellen.
3. Berechtigungen: **nur "Can Trade"** (Handeln). **"Can Withdraw" (Auszahlung) NICHT aktivieren.**
4. **IP-Whitelist** einschalten und nur die feste IP deines VPS eintragen. Dann ist der Key nur von dort nutzbar.
5. Key und Secret in `.env` speichern (`chmod 600 .env`), niemals in Git, Chat oder E-Mail:
   ```
   CDC_API_KEY=...
   CDC_API_SECRET=...
   ```
6. Guthaben (USD, bzw. USD-Stablecoin je nach Konto) auf der Exchange bereitstellen. Die Menüs ändern sich – im Zweifel in der Crypto.com-Hilfe nachsehen.

## Kill-Schalter (Not-Aus)

- `python -m ewbot kill` legt `state/KILL` an: keine neuen Trades, offene Einstiegs-Orders werden storniert. Positionen bleiben
  (Stops und Ziele laufen weiter).
- `python -m ewbot kill --flatten`: zusätzlich werden die Positionen des Bots zum Marktpreis verkauft.
- `python -m ewbot kill --clear` nimmt den Schalter wieder weg.
- `kill` schreibt **nur die Datei** `state/KILL`. Ausgeführt wird sie vom laufenden Bot (innerhalb einer Minute) bzw. vom
  nächsten `paper-step`. So kommen sich Befehl und laufender Bot nie in die Quere. Läuft der Bot nicht, passiert nichts.
- Pro Zustandsdatei darf nur **ein** Prozess laufen (`run` oder `paper-step`); eine Sperrdatei `<zustand>.lock` verhindert Doppelstarts.
  `status --clear-halt` geht deshalb nur bei gestopptem Bot.
- Zusätzlich kannst du jederzeit in der Crypto.com-Oberfläche alle Orders löschen und den API-Key sperren.

## Dateien

- `ewbot/engine.py` – Ablauf jedes Trades (Zustände: wartet auf Einstieg → offen → offen mit Break-even-Stop → wird geschlossen → geschlossen / storniert)
- `ewbot/risk.py` – Positionsgröße und Limits · `ewbot/journal.py` – CSV-Journal für die Steuer
- `ewbot/report.py` – Handy-Seite · `ewbot/__main__.py` – Befehle · `config.example.yaml` – Einstellungen
- `deploy/` – systemd-Dienst und Installationsskript · `VPS_SETUP.md` – Anleitung für den Server
