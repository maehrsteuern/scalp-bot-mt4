# Szenario-Backtest: eingefrorene EW-Strategie über 2021 bis heute

Alle Zahlen kommen aus dem Code (`python -m ewbot.scenarios`). Datenstand: letzte Kerze 09.11.2026. Die Strategie ist **eingefroren**: `StrategyParams()` mit Standardwerten, keine neue Einstellung, keine neuen Parameter.

## Kernaussage

- **Nie gesehener Zeitraum 2021 bis 05.03.2025:** 107 Trades, Ø **-0.22 R netto** (brutto +0.10 R), Trefferquote 50 %, Summe -23.1 R, 95 %-Bereich für Ø R [-0.47 ; +0.03].
- Einstellperiode (b): 34 Trades, Ø -0.10 R netto. Späteres Out-of-Sample (c): 12 Trades, Ø -0.46 R netto.
- Alles zusammen 2021 bis heute: 153 Trades, Ø -0.21 R netto, brutto +0.13 R, Summe -32.0 R, 95 %-Bereich [-0.41 ; -0.00].
- **Gebühren-Schwelle:** Der Durchschnitt wird erst bei Maker-Gebühr ≤ 0.095 % (Taker doppelt so hoch: 0.190 %) nicht mehr negativ; bei gleich hohen Gebühren für Kauf und Verkauf liegt die Schwelle bei 0.125 %.
- **Zufallstest (Monte Carlo):** mittlerer größter Verlust (Max. Drawdown) 36.9 R / 24.7 %, im schlechten Fall (95 %) 44.4 R / 28.7 %. Wahrscheinlichkeit, nach einem Jahr im Minus zu sein: 82 %.
- **Marktphase:** Am besten lief es in Monaten mit BTC-Trend *steigend* (Ø +0.04 R, 24 Trades), am schlechtesten bei *fallend* (Ø -0.33 R, 74 Trades).
- **Urteil in einem Satz:** Der nie gesehene Zeitraum **bestätigt** BACKTEST.md: nach Gebühren kein Gewinn.

## 1. Daten

| Coin | 30m-Kerzen | von | bis | Lücken (Anzahl) | fehlende Kerzen | längste Lücke | 4h-Kerzen | 4h-Lücken |
|---|---|---|---|---|---|---|---|---|
| BTC_USD | 101116 | 01.01.2021 | 09.11.2026 | 10 | 1518 | 1440 Kerzen (30.0 Tage) | 12643 | 2 |
| ETH_USD | 93880 | 01.07.2021 | 09.11.2026 | 5 | 66 | 48 Kerzen (1.0 Tage) | 11737 | 1 |
| SOL_USD | 90970 | 30.08.2021 | 09.11.2026 | 6 | 67 | 48 Kerzen (1.0 Tage) | 11374 | 1 |

Quelle: öffentliche Crypto.com-API, nur geschlossene Kerzen, Download mit `python -m ewbot.history --extend`. Frühester Kerzenbeginn, den die API liefert: BTC ab 01.01.2021, ETH ab 01.07.2021, SOL ab 30.08.2021. ETH und SOL gibt es in der API erst ab diesem Datum (nach meinem Kenntnisstand wegen des späteren Börsenstarts der Paare, nicht verifiziert). Große Lücken (über 7 Tage) bei BTC: 31.05.2021 bis 01.07.2021 (30 Tage) – dort liefert die API gar keine Kerzen. In der Tabelle zählt eine solche Lücke als eine Lücke.

Die ersten 600 Kerzen je Coin sind Anlaufzeit. Erste Auswertung: BTC ab 13.01.2021, ETH ab 13.07.2021, SOL ab 12.09.2021.
Trades, deren Laufzeit oder 30m-Fenster (400 Kerzen vor dem Signal) eine Datenlücke berührt: 10 von 153. Ohne diese Trades: Ø -0.20 R netto (143 Trades) statt -0.21 R.

## 2. Drei Zeiträume

Ein Trade zählt zu dem Zeitraum, in dem das Signal entstand. Grenzen wie in BACKTEST.md (Einstellperiode = die ersten 60 % des damaligen Tests). Die Strategie lief hier **in einem Durchgang ab 2021**; Trades ab 2025 können deshalb leicht von BACKTEST.md abweichen (anderer Startzustand, eine Position je Coin).

| Zeitraum / Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) | 95 %-Bereich Ø R | Portfolio-Rendite* | Portfolio-DD* |
|---|---|---|---|---|---|---|---|---|---|---|
| a: BTC | 81 | 37 | 46 % | -0.38 | +0.02 | -14.2 | 15.7 | [-0.82 ; +0.02] | | |
| a: ETH | 84 | 33 | 58 % | -0.06 | +0.26 | -2.0 | 9.0 | [-0.54 ; +0.41] | | |
| a: SOL | 110 | 37 | 49 % | -0.19 | +0.05 | -6.9 | 10.8 | [-0.57 ; +0.23] | | |
| **a: Gesamt** | 275 | 107 | 50 % | -0.22 | +0.10 | -23.1 | 27.1 | [-0.47 ; +0.03] | -11.0 % | 14.9 % |
| b: BTC | 29 | 12 | 42 % | -0.23 | +0.18 | -2.8 | 4.6 | [-0.87 ; +0.42] | | |
| b: ETH | 39 | 13 | 54 % | -0.31 | -0.04 | -4.1 | 7.1 | [-0.89 ; +0.29] | | |
| b: SOL | 31 | 9 | 67 % | +0.39 | +0.66 | +3.5 | 2.6 | [-0.56 ; +1.21] | | |
| **b: Gesamt** | 99 | 34 | 53 % | -0.10 | +0.22 | -3.3 | 12.3 | [-0.52 ; +0.30] | -3.3 % | 8.9 % |
| c: BTC | 9 | 1 | 0 % | -1.67 | -1.08 | -1.7 | 1.7 | [-1.67 ; -1.67] | | |
| c: ETH | 15 | 6 | 17 % | -0.74 | -0.13 | -4.4 | 4.4 | [-1.55 ; +0.25] | | |
| c: SOL | 20 | 5 | 60 % | +0.11 | +0.54 | +0.5 | 1.6 | [-0.74 ; +0.85] | | |
| **c: Gesamt** | 44 | 12 | 33 % | -0.46 | +0.07 | -5.6 | 6.4 | [-1.13 ; +0.23] | -3.4 % | 4.1 % |

*Portfolio: 0,75 % Risiko je Trade, mit Zinseszins, Gesamt-Exposure max. 90 % (Funktion `portfolio` aus `backtest.py`).

- (a) 2021 bis 05.03.2025 – nie gesehen (echtes Out-of-Sample)
- (b) 06.03.2025 bis 08.03.2026 – Einstellperiode (In-Sample)
- (c) 08.03.2026 bis heute – späteres Out-of-Sample

Zum Vergleich die Zahlen in BACKTEST.md (nur Daten ab 2025): In-Sample 34 Trades, Ø -0.10 R netto (brutto +0.22), Out-of-Sample 12 Trades, Ø -0.46 R netto (brutto +0.08). Hier: (b) 34 Trades, Ø -0.10 (brutto +0.22); (c) 12 Trades, Ø -0.46 (brutto +0.07).

## 3. Benannte Marktphasen (Szenarien)

Jede Phase wurde an den **BTC-30m-Kursen geprüft**: Start und Ende sind das echte Hoch bzw. Tief (30m-Kerze) in der Nähe des ungefähren Datums (Toleranz ±14 Tage, bei kurzen Crash-Fenstern ±3 bis ±5 Tage). Die BTC-Bewegung ist von Extrem zu Extrem gerechnet. Phasen mit eingerückten Namen liegen **innerhalb** einer größeren Phase (Trades werden dann doppelt gezählt, nur die Hauptphasen sind getrennt). Die Bezeichnungen sind bewusst neutral. Ursachen stehen nur dort, wo sie allgemein bekannt sind – *nach meinem Kenntnisstand*.

### 3.1 Geprüfte Fenster

| Phase | ungefähr (Vorgabe) | geprüft: Start | geprüft: Ende | Verschiebung Start / Ende | BTC-Bewegung | Ursache (nach meinem Kenntnisstand) |
|---|---|---|---|---|---|---|
| Bullenmarkt Q1 2021 | 01.01.2021 – 14.04.2021 | 01.01.2021 | 14.04.2021 | +0.0 / +0.5 Tage | +124.1 % | – |
| Crash Mai 2021 | 12.05.2021 – 23.05.2021 | 10.05.2021 | 19.05.2021 | -1.8 / -3.5 Tage | -50.8 % | Kritik am Energieverbrauch von Bitcoin (Tesla-Zahlungsstopp) und Chinas Vorgehen gegen Mining |
| Sommer-Boden / Erholung 2021 | 20.07.2021 – 10.11.2021 | 20.07.2021 | 10.11.2021 | +0.4 / +0.6 Tage | +137.1 % | – |
| Bärenmarkt 2022 (gesamt) | 10.11.2021 – 21.11.2022 | 10.11.2021 | 21.11.2022 | +0.6 / +0.9 Tage | -77.6 % | Zinserhöhungen und mehrere Pleiten im Kryptomarkt |
| Terra/Luna-Zusammenbruch | 07.05.2022 – 13.05.2022 | 04.05.2022 | 12.05.2022 | -2.2 / -0.7 Tage | -36.8 % | Zusammenbruch des Stablecoins TerraUSD und des Luna-Tokens |
| Celsius / 3AC | 10.06.2022 – 18.06.2022 | 06.06.2022 | 18.06.2022 | -3.4 / +0.9 Tage | -44.6 % | Auszahlungsstopp bei Celsius, Probleme bei Three Arrows Capital |
| FTX-Zusammenbruch | 06.11.2022 – 10.11.2022 | 05.11.2022 | 09.11.2022 | -0.9 / -0.0 Tage | -27.3 % | Pleite der Börse FTX |
| Seitwärts / Erholung 2023 | 21.11.2022 – 12.10.2023 | 21.11.2022 | 28.09.2023 | +0.9 / -13.9 Tage | +70.2 % | – |
| SVB-Bankenkrise | 10.03.2023 – 14.03.2023 | 10.03.2023 | 14.03.2023 | +0.4 / +0.5 Tage | +35.7 % | Zusammenbruch der Silicon Valley Bank |
| ETF-Rally | 12.10.2023 – 14.03.2024 | 28.09.2023 | 14.03.2024 | -13.9 / +0.3 Tage | +180.4 % | Erwartung und Zulassung von Bitcoin-Spot-ETFs in den USA |
| Seitwärts März–Okt 2024 | 14.03.2024 – 04.11.2024 | 14.03.2024 | 23.10.2024 | +0.3 / -11.2 Tage | -11.7 % | – |
| Crash 05.08.2024 | 29.07.2024 – 05.08.2024 | 29.07.2024 | 05.08.2024 | +0.5 / +0.2 Tage | -30.1 % | Börsenturbulenzen in Japan (Zinserhöhung, Yen-Carry-Trades) |
| Wahl-Rally Nov–Dez 2024 | 04.11.2024 – 17.12.2024 | 23.10.2024 | 17.12.2024 | -11.2 / +0.6 Tage | +66.3 % | US-Präsidentschaftswahl |
| Rückgang Jan–Apr 2025 | 20.01.2025 – 07.04.2025 | 20.01.2025 | 07.04.2025 | +0.3 / +0.3 Tage | -32.0 % | Zollstreit der USA |
| Rally bis Hoch Okt 2025 | 07.04.2025 – 06.10.2025 | 07.04.2025 | 06.10.2025 | +0.3 / +0.8 Tage | +69.8 % | – |
| Liquidations-Crash 10.10.2025 | 06.10.2025 – 10.10.2025 | 06.10.2025 | 10.10.2025 | +0.8 / +0.9 Tage | -18.7 % | Zolldrohungen der USA gegen China, sehr hohe Zwangsverkäufe bei Hebel-Positionen |
| Bärenphase Okt 2025–Jul 2026 (gesamt) | 06.10.2025 – 01.07.2026 | 06.10.2025 | 01.07.2026 | +0.8 / +0.0 Tage | -54.3 % | – |
| Abwärts bis Tief Feb 2026 | 06.10.2025 – 06.02.2026 | 06.10.2025 | 06.02.2026 | +0.8 / +0.0 Tage | -52.6 % | – |
| Seitwärts Feb–Jul 2026 | 06.02.2026 – 01.07.2026 | 06.02.2026 | 01.07.2026 | +0.0 / +0.0 Tage | -3.6 % | – |
| Rally Jul–Sep 2026 | 01.07.2026 – 15.09.2026 | 01.07.2026 | 21.09.2026 | +0.0 / +6.8 Tage | +51.4 % | – |
| Korrektur Sep–Nov 2026 | 15.09.2026 – 09.11.2026 | 21.09.2026 | 08.11.2026 | +6.8 / -0.0 Tage | -14.5 % | – |

Verschiebungen von mehr als 7 Tagen bedeuten: das genannte Datum war nicht das echte Extrem; es gilt das geprüfte Datum.

### 3.2 Ergebnis je Phase (alle Coins)

P&L = Portfolio-Rendite in % des Kapitals bei 0,75 % Risiko je Trade. Buy-and-Hold = einfach halten über dasselbe Fenster (n/a = Coin dort noch nicht an der Börse).

| Phase | BTC-Bew. | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) | P&L % Kapital | Halten BTC | Halten ETH | Halten SOL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Bullenmarkt Q1 2021 | +124 % | 4 | 3 | 67 % | +0.32 | +0.52 | +0.9 | 1.4 | +0.7 % | +123 % | n/a | n/a |
| Crash Mai 2021 | -51 % | 2 | 1 | 0 % | -1.18 | -1.02 | -1.2 | 1.2 | -0.9 % | -44 % | n/a | n/a |
| Sommer-Boden / Erholung 2021 | +137 % | 18 | 7 | 71 % | +0.51 | +0.65 | +3.6 | 1.3 | +2.7 % | +130 % | +177 % | n/a |
| Bärenmarkt 2022 (gesamt) | -78 % | 116 | 46 | 46 % | -0.40 | -0.06 | -18.5 | 18.9 | -12.7 % | -77 % | -77 % | -95 % |
|   Terra/Luna-Zusammenbruch | -37 % | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +0.0 % | -31 % | -37 % | -53 % |
|   Celsius / 3AC | -45 % | 4 | 2 | 0 % | -1.08 | -0.28 | -2.2 | 2.2 | -1.5 % | -44 % | -53 % | -37 % |
|   FTX-Zusammenbruch | -27 % | 4 | 4 | 50 % | -0.70 | -0.28 | -2.8 | 2.8 | -1.8 % | -26 % | -34 % | -60 % |
| Seitwärts / Erholung 2023 | +70 % | 53 | 22 | 55 % | -0.08 | +0.32 | -1.7 | 7.4 | +1.5 % | +67 % | +45 % | +65 % |
|   SVB-Bankenkrise | +36 % | 1 | 1 | 100 % | +1.29 | +1.45 | +1.3 | 0.0 | +1.0 % | +31 % | +26 % | +35 % |
| ETF-Rally | +180 % | 4 | 1 | 100 % | +0.32 | +0.53 | +0.3 | 0.0 | +0.2 % | +178 % | +147 % | +775 % |
| Seitwärts März–Okt 2024 | -12 % | 52 | 18 | 44 % | -0.22 | +0.04 | -4.0 | 8.6 | -3.1 % | -11 % | -38 % | -1 % |
|   Crash 05.08.2024 | -30 % | 6 | 3 | 0 % | -1.21 | -1.02 | -3.6 | 3.6 | -2.7 % | -28 % | -35 % | -41 % |
| Wahl-Rally Nov–Dez 2024 | +66 % | 3 | 1 | 0 % | -1.44 | -1.05 | -1.4 | 1.4 | -1.1 % | +65 % | +61 % | +34 % |
| Rückgang Jan–Apr 2025 | -32 % | 20 | 4 | 75 % | +0.11 | +0.34 | +0.5 | 1.4 | +0.3 % | -27 % | -56 % | -61 % |
| Rally bis Hoch Okt 2025 | +70 % | 13 | 2 | 100 % | +0.34 | +0.53 | +0.7 | 0.0 | +0.5 % | +69 % | +230 % | +144 % |
|   Liquidations-Crash 10.10.2025 | -19 % | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +0.0 % | -13 % | -23 % | -26 % |
| Bärenphase Okt 2025–Jul 2026 (gesamt) | -54 % | 116 | 42 | 45 % | -0.22 | +0.17 | -9.1 | 14.8 | -6.7 % | -53 % | -67 % | -69 % |
|   Abwärts bis Tief Feb 2026 | -53 % | 48 | 15 | 33 % | -0.30 | +0.08 | -4.5 | 10.2 | -4.0 % | -51 % | -62 % | -70 % |
|   Seitwärts Feb–Jul 2026 | -4 % | 68 | 27 | 52 % | -0.17 | +0.21 | -4.6 | 7.9 | -2.8 % | -7 % | -14 % | -6 % |
| Rally Jul–Sep 2026 | +51 % | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +0.0 % | +49 % | +78 % | +62 % |
| Korrektur Sep–Nov 2026 | -14 % | 4 | 1 | 100 % | +0.88 | +1.41 | +0.9 | 0.0 | +0.7 % | -14 % | -23 % | -27 % |

### 3.3 Ergebnis je Phase und Coin

| Phase | Coin | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) | Halten |
|---|---|---|---|---|---|---|---|---|---|
| Bullenmarkt Q1 2021 | BTC | 4 | 3 | 67 % | +0.32 | +0.52 | +0.9 | 1.4 | +123 % |
| Bullenmarkt Q1 2021 | ETH | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | n/a |
| Bullenmarkt Q1 2021 | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | n/a |
| Crash Mai 2021 | BTC | 2 | 1 | 0 % | -1.18 | -1.02 | -1.2 | 1.2 | -44 % |
| Crash Mai 2021 | ETH | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | n/a |
| Crash Mai 2021 | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | n/a |
| Sommer-Boden / Erholung 2021 | BTC | 8 | 2 | 50 % | -0.06 | +0.13 | -0.1 | 1.3 | +130 % |
| Sommer-Boden / Erholung 2021 | ETH | 3 | 2 | 100 % | +1.50 | +1.58 | +3.0 | 0.0 | +177 % |
| Sommer-Boden / Erholung 2021 | SOL | 7 | 3 | 67 % | +0.24 | +0.38 | +0.7 | 1.1 | n/a |
| Bärenmarkt 2022 (gesamt) | BTC | 39 | 18 | 39 % | -0.59 | -0.08 | -10.7 | 12.0 | -77 % |
| Bärenmarkt 2022 (gesamt) | ETH | 36 | 13 | 62 % | -0.08 | +0.20 | -1.0 | 3.2 | -77 % |
| Bärenmarkt 2022 (gesamt) | SOL | 41 | 15 | 40 % | -0.46 | -0.25 | -6.9 | 8.4 | -95 % |
|   Terra/Luna-Zusammenbruch | BTC | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -31 % |
|   Terra/Luna-Zusammenbruch | ETH | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -37 % |
|   Terra/Luna-Zusammenbruch | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -53 % |
|   Celsius / 3AC | BTC | 2 | 2 | 0 % | -1.08 | -0.28 | -2.2 | 2.2 | -44 % |
|   Celsius / 3AC | ETH | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -53 % |
|   Celsius / 3AC | SOL | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -37 % |
|   FTX-Zusammenbruch | BTC | 2 | 2 | 50 % | -1.01 | -0.32 | -2.0 | 2.2 | -26 % |
|   FTX-Zusammenbruch | ETH | 2 | 2 | 50 % | -0.38 | -0.24 | -0.8 | 1.1 | -34 % |
|   FTX-Zusammenbruch | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -60 % |
| Seitwärts / Erholung 2023 | BTC | 10 | 6 | 67 % | +0.27 | +0.67 | +1.6 | 1.7 | +67 % |
| Seitwärts / Erholung 2023 | ETH | 13 | 4 | 25 % | -1.47 | -0.70 | -5.9 | 5.9 | +45 % |
| Seitwärts / Erholung 2023 | SOL | 30 | 12 | 58 % | +0.21 | +0.49 | +2.6 | 4.0 | +65 % |
|   SVB-Bankenkrise | BTC | 1 | 1 | 100 % | +1.29 | +1.45 | +1.3 | 0.0 | +31 % |
|   SVB-Bankenkrise | ETH | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +26 % |
|   SVB-Bankenkrise | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +35 % |
| ETF-Rally | BTC | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +178 % |
| ETF-Rally | ETH | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +147 % |
| ETF-Rally | SOL | 4 | 1 | 100 % | +0.32 | +0.53 | +0.3 | 0.0 | +775 % |
| Seitwärts März–Okt 2024 | BTC | 13 | 4 | 50 % | -0.51 | -0.25 | -2.0 | 2.6 | -11 % |
| Seitwärts März–Okt 2024 | ETH | 20 | 10 | 50 % | +0.05 | +0.32 | +0.5 | 4.1 | -38 % |
| Seitwärts März–Okt 2024 | SOL | 19 | 4 | 25 % | -0.63 | -0.35 | -2.5 | 2.5 | -1 % |
|   Crash 05.08.2024 | BTC | 2 | 1 | 0 % | -1.27 | -1.03 | -1.3 | 1.3 | -28 % |
|   Crash 05.08.2024 | ETH | 2 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -35 % |
|   Crash 05.08.2024 | SOL | 2 | 2 | 0 % | -1.18 | -1.02 | -2.4 | 2.4 | -41 % |
| Wahl-Rally Nov–Dez 2024 | BTC | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +65 % |
| Wahl-Rally Nov–Dez 2024 | ETH | 3 | 1 | 0 % | -1.44 | -1.05 | -1.4 | 1.4 | +61 % |
| Wahl-Rally Nov–Dez 2024 | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +34 % |
| Rückgang Jan–Apr 2025 | BTC | 9 | 1 | 0 % | -1.38 | -1.04 | -1.4 | 1.4 | -27 % |
| Rückgang Jan–Apr 2025 | ETH | 7 | 2 | 100 % | +0.76 | +0.93 | +1.5 | 0.0 | -56 % |
| Rückgang Jan–Apr 2025 | SOL | 4 | 1 | 100 % | +0.31 | +0.53 | +0.3 | 0.0 | -61 % |
| Rally bis Hoch Okt 2025 | BTC | 3 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +69 % |
| Rally bis Hoch Okt 2025 | ETH | 9 | 2 | 100 % | +0.34 | +0.53 | +0.7 | 0.0 | +230 % |
| Rally bis Hoch Okt 2025 | SOL | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +144 % |
|   Liquidations-Crash 10.10.2025 | BTC | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -13 % |
|   Liquidations-Crash 10.10.2025 | ETH | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -23 % |
|   Liquidations-Crash 10.10.2025 | SOL | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -26 % |
| Bärenphase Okt 2025–Jul 2026 (gesamt) | BTC | 28 | 12 | 42 % | -0.26 | +0.17 | -3.1 | 5.0 | -53 % |
| Bärenphase Okt 2025–Jul 2026 (gesamt) | ETH | 41 | 17 | 35 % | -0.54 | -0.14 | -9.2 | 11.1 | -67 % |
| Bärenphase Okt 2025–Jul 2026 (gesamt) | SOL | 47 | 13 | 62 % | +0.25 | +0.56 | +3.2 | 2.6 | -69 % |
|   Abwärts bis Tief Feb 2026 | BTC | 9 | 5 | 20 % | -0.28 | +0.26 | -1.4 | 3.3 | -51 % |
|   Abwärts bis Tief Feb 2026 | ETH | 18 | 7 | 29 % | -0.74 | -0.44 | -5.2 | 7.1 | -62 % |
|   Abwärts bis Tief Feb 2026 | SOL | 21 | 3 | 67 % | +0.71 | +1.00 | +2.1 | 1.4 | -70 % |
|   Seitwärts Feb–Jul 2026 | BTC | 19 | 7 | 57 % | -0.24 | +0.11 | -1.7 | 3.2 | -7 % |
|   Seitwärts Feb–Jul 2026 | ETH | 23 | 10 | 40 % | -0.40 | +0.08 | -4.0 | 5.5 | -14 % |
|   Seitwärts Feb–Jul 2026 | SOL | 26 | 10 | 60 % | +0.11 | +0.42 | +1.1 | 1.8 | -6 % |
| Rally Jul–Sep 2026 | BTC | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +49 % |
| Rally Jul–Sep 2026 | ETH | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +78 % |
| Rally Jul–Sep 2026 | SOL | 1 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | +62 % |
| Korrektur Sep–Nov 2026 | BTC | 0 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -14 % |
| Korrektur Sep–Nov 2026 | ETH | 3 | 0 | 0 % | +0.00 | +0.00 | +0.0 | 0.0 | -23 % |
| Korrektur Sep–Nov 2026 | SOL | 1 | 1 | 100 % | +0.88 | +1.41 | +0.9 | 0.0 | -27 % |

### 3.4 Beste und schlechteste Phasen (nach Summe R, mindestens 3 Trades)

| Rang | Phase | Trades | Summe R | Ø R netto |
|---|---|---|---|---|
| beste 1 | Sommer-Boden / Erholung 2021 | 7 | +3.6 | +0.51 |
| beste 2 | Bullenmarkt Q1 2021 | 3 | +0.9 | +0.32 |
| beste 3 | Rückgang Jan–Apr 2025 | 4 | +0.5 | +0.11 |
| schlechteste 1 | Bärenmarkt 2022 (gesamt) | 46 | -18.5 | -0.40 |
| schlechteste 2 | Bärenphase Okt 2025–Jul 2026 (gesamt) | 42 | -9.1 | -0.22 |
| schlechteste 3 | Seitwärts Feb–Jul 2026 | 27 | -4.6 | -0.17 |

## 4. Marktregime nach Monaten

Jeder Monat wird nach der BTC-Veränderung vom ersten Open bis zum letzten Close eingestuft: **steigend** über +10 %, **fallend** unter −10 %, sonst **seitwärts**. Ein Trade zählt zum Monat seines Signals. Der laufende Monat ist unvollständig.

| Jahr | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021 | +15 % ↑ | +36 % ↑ | +30 % ↑ | -2 % → | -35 % ↓ |  | +18 % ↑ | +14 % ↑ | -7 % → | +40 % ↑ | -7 % → | -17 % ↓ |
| 2022 | -17 % ↓ | +12 % ↑ | +5 % → | -17 % ↓ | -16 % ↓ | -37 % ↓ | +17 % ↑ | -14 % ↓ | -3 % → | +5 % → | -16 % ↓ | -4 % → |
| 2023 | +40 % ↑ | +0 % → | +23 % ↑ | +3 % → | -7 % → | +12 % ↑ | -4 % → | -11 % ↓ | +4 % → | +29 % ↑ | +9 % → | +12 % ↑ |
| 2024 | +1 % → | +44 % ↑ | +16 % ↑ | -15 % ↓ | +11 % ↑ | -7 % → | +3 % → | -9 % → | +7 % → | +11 % ↑ | +37 % ↑ | -3 % → |
| 2025 | +10 % → | -18 % ↓ | -2 % → | +14 % ↑ | +11 % ↑ | +2 % → | +8 % → | -6 % → | +5 % → | -4 % → | -18 % ↓ | -3 % → |
| 2026 | -10 % ↓ | -15 % ↓ | +2 % → | +12 % ↑ | -4 % → | -20 % ↓ | +7 % → | +25 % ↑ | +6 % → | -7 % → | -3 % → |  |

(↑ steigend, → seitwärts, ↓ fallend; Zahl = BTC-Monatsveränderung)

| Regime (BTC-Monat) | Monate | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | 95 %-Bereich Ø R |
|---|---|---|---|---|---|---|---|---|
| steigend | 22 | 77 | 24 | 62 % | +0.04 | +0.33 | +0.9 | [-0.47 ; +0.58] |
| seitwärts | 33 | 176 | 55 | 49 % | -0.16 | +0.19 | -8.7 | [-0.49 ; +0.18] |
| fallend | 15 | 165 | 74 | 46 % | -0.33 | +0.02 | -24.1 | [-0.59 ; -0.08] |

Monate = Monate ab der ersten Auswertung. Die Strategie kauft Rücksetzer nach einer großen Rally; deshalb gibt es kaum Signale, wenn der Markt lange in einer Richtung läuft.

## 5. Stresstests (alle Trades 2021 bis heute)

### 5.1 Gebührenstufen (Slippage 0,10 % wie Basis)

| Maker / Taker | Trades | Ø R netto | Summe R | Ø R netto nur Zeitraum (a) | Summe R (a) |
|---|---|---|---|---|---|
| 0,25 % / 0,50 % (Annahme, Basis) | 153 | -0.21 | -32.0 | -0.22 | -23.1 |
| 0,10 % / 0,20 % | 153 | -0.01 | -1.1 | -0.02 | -2.5 |
| 0,075 % / 0,075 % | 153 | +0.05 | +7.8 | +0.03 | +3.3 |
| 0 % / 0 % (brutto) | 153 | +0.13 | +19.6 | +0.10 | +11.1 |

**Break-even (alle Trades):** Ø R netto wird 0 bei Maker 0.095 % / Taker 0.190 % (Taker = 2 × Maker) bzw. bei gleichen Gebühren von 0.125 %.
Nur Zeitraum (a): Maker 0.081 % / Taker 0.163 %.

### 5.2 Slippage beim Stop (Gebühren wie Basis)

| Slippage | Trades | Ø R netto | Summe R |
|---|---|---|---|
| 0.1 % | 153 | -0.21 | -32.0 |
| 0.3 % | 153 | -0.27 | -41.7 |

### 5.3 Monte Carlo (10 000 Mischungen der Netto-R-Folge)

Die 153 Netto-R-Werte aller Trades werden 10000 Mal zufällig neu gemischt (Seed fest). Das zeigt, wie groß Verlustserien allein durch die Reihenfolge werden können. Trades pro Jahr (aus den Daten): 26.3; 1 Jahr = 26 Trades. Prozentwerte: 0,75 % Risiko je Trade, mit Zinseszins, ohne Exposure-Grenze, alle Coins als eine Folge (die Coins sind aber korreliert – in Wirklichkeit liegen Verluste öfter gleichzeitig).

| Kennzahl | Median | schlechter Fall (95 %) | tatsächliche Reihenfolge |
|---|---|---|---|
| Max. Drawdown in R | 36.9 | 44.4 | 33.8 |
| Max. Drawdown in % des Kapitals | 24.7 % | 28.7 % | – |
| Längste Verlustserie (Trades) | 6 | 10 (Maximum 18) | 8 |
| Ergebnis nach 1 Jahr (26 Trades), Summe R | -5.5 | 5 %: -15.3 / 95 %: +4.3 | – |

Wahrscheinlichkeit, dass die Summe nach 1 Jahr Trades negativ ist: **82 %** (Ø R je Trade in den Daten: -0.21). Das ist nur so gut wie die Annahme, dass die Zukunft wie die Vergangenheit aussieht.

### 5.4 Vergleich mit Zufalls-Einstiegen (gleiche Ausstiege)

Geometrie wie in BACKTEST.md aus den EW-Signalen der Einstellperiode (b): Stop 2.05 % vom Einstieg, T1 1.10 R, T2 2.12 R, Limit 0.82 % unter dem Kurs. Periodisch = alle 12 h, Zufall = ca. 1 Einstieg pro Tag (5 Läufe zusammen). Gleiche Gebühren und Slippage.

| Zeitraum | Gruppe | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) |
|---|---|---|---|---|---|---|---|
| 2021 bis heute | EW-Strategie | 153 | 50 % | -0.21 | +0.13 | -32.0 | 33.8 |
| 2021 bis heute | Periodisch | 4119 | 47 % | -0.37 | -0.05 | -1527.4 | 1527.4 |
| 2021 bis heute | Zufall | 11143 | 48 % | -0.36 | -0.04 | -4030.9 | 4030.9 |
| (a) | EW-Strategie | 107 | 50 % | -0.22 | +0.10 | -23.1 | 27.1 |
| (a) | Periodisch | 3035 | 47 % | -0.38 | -0.06 | -1152.6 | 1152.6 |
| (a) | Zufall | 8061 | 48 % | -0.36 | -0.04 | -2891.7 | 2894.7 |
| (b) | EW-Strategie | 34 | 53 % | -0.10 | +0.22 | -3.3 | 12.3 |
| (b) | Periodisch | 728 | 48 % | -0.35 | -0.03 | -251.9 | 254.7 |
| (b) | Zufall | 1981 | 48 % | -0.38 | -0.06 | -748.7 | 751.4 |
| (c) | EW-Strategie | 12 | 33 % | -0.46 | +0.07 | -5.6 | 6.4 |
| (c) | Periodisch | 356 | 49 % | -0.35 | -0.02 | -122.9 | 129.4 |
| (c) | Zufall | 1101 | 48 % | -0.35 | -0.03 | -390.4 | 415.0 |

## 6. Urteil

**Bestätigt oder widerspricht der nie gesehene Zeitraum BACKTEST.md?** Der nie gesehene Zeitraum **bestätigt** BACKTEST.md: nach Gebühren kein Gewinn. BACKTEST.md sagte: nach Gebühren keine tragfähige Kante, vor Gebühren höchstens ein kleiner Vorteil. Zeitraum (a) (107 Trades): Ø -0.22 R netto, +0.10 R brutto; Zufalls-Einstiege brutto im selben Zeitraum: -0.04 R.

Gegen Zufall (Zeitraum a, brutto): EW +0.10 R, Zufalls-Einstiege -0.04 R. Das ist ein kleiner Vorteil vor Gebühren; er ist aber kleiner als die Gebühren (siehe unten) und bei der Tradezahl nicht gesichert.

**Wann funktioniert die Strategie, wann nicht?**

- BTC-Monat *steigend*: 24 Trades, Ø +0.04 R netto, brutto +0.33 R (positiv). Der 95 %-Bereich schließt 0 ein – nicht von Null unterscheidbar.
- BTC-Monat *seitwärts*: 55 Trades, Ø -0.16 R netto, brutto +0.19 R (negativ). Der 95 %-Bereich schließt 0 ein – nicht von Null unterscheidbar.
- BTC-Monat *fallend*: 74 Trades, Ø -0.33 R netto, brutto +0.02 R (negativ). Der 95 %-Bereich liegt komplett unter 0 – das ist ein klares Minus.
- Beste Phase: Sommer-Boden / Erholung 2021 (+3.6 R aus 7 Trades). Schlechteste Phase: Bärenmarkt 2022 (gesamt) (-18.5 R aus 46 Trades).

**Gebühren:** Mit Maker 0,25 % / Taker 0,50 % ist der Durchschnitt -0.21 R. Er wird erst bei Maker ≤ 0.095 % (Taker doppelt) nicht mehr negativ. Brutto (ohne Gebühren) liegt er bei +0.13 R.

**Empfehlung:** Weiter nur Papier-Modus. Echtgeld erst, wenn eine Gebührenstufe unter der Break-even-Schwelle sicher verfügbar ist **und** weitere Trades außerhalb der Stichprobe das Bild bestätigen. Dieser Test hat nichts neu eingestellt, daher ist (a) ein fairer Blindtest – aber nur ein Marktzyklus.

## 7. Grenzen

- **Korrelation der Coins:** BTC, ETH und SOL fallen und steigen meist gemeinsam. Die Trades sind nicht unabhängig; die Zahl der echten, unabhängigen Chancen ist kleiner als die Tradezahl. Der Monte-Carlo-Test mischt alle Coins als eine Folge und unterschätzt gleichzeitige Verluste.
- **30m-Unschärfe innerhalb der Kerze:** Die Simulation kennt die Reihenfolge von Hoch und Tief in einer Kerze nicht. Sie nimmt vorsichtig immer den Stop zuerst und wertet in der Einstiegskerze keine Ziele. Das drückt das Ergebnis eher nach unten; echte Fills (Warteschlange, Teilfüllung) können anders sein.
- **Datenlücken:** Siehe Abschnitt 1. Bei BTC fehlt der ganze Juni 2021 (Börse liefert nichts); dazu einige kleine Lücken bis zu einem Tag. 10 Trades berühren eine Lücke (Ergebnis ohne sie: Ø -0.20 R). Der Kurssprung über die Juni-Lücke kann das 30m-Fenster der Strategie im Juli 2021 verfälschen.
- **Weniger Daten vor Mitte 2021:** Von Januar bis Juni 2021 läuft nur BTC; ETH startet erst am 01.07.2021, SOL am 30.08.2021. Der Zeitraum (a) hat deshalb je Coin unterschiedlich viele Trades (BTC 37, ETH 33, SOL 37).
- **SOL-Börsenstart / Überlebens-Verzerrung:** SOL-Kurse gibt es erst ab 30.08.2021; frühere Phasen enthalten SOL nicht (in den Tabellen „n/a“). Außerdem sind BTC, ETH und SOL die Coins, die bis heute überlebt haben und groß wurden; gescheiterte Coins fehlen (Überlebens-Verzerrung). Das macht Ergebnisse eher zu gut als zu schlecht.
- **Einstellung:** Die Standardwerte wurden 2025/2026 im Zeitraum (b) ausgewählt (16 Varianten). Zeitraum (a) war dabei nicht sichtbar, ist aber ein einziger Marktzyklus mit nur wenigen Trends. Phasen-Auswertung mit wenigen Trades ist anfällig für Zufall (nicht mit Statistik absicherbar).
- **Gebühren, Slippage und Börse:** Gebühren sind Annahmen, die Slippage ist pauschal; Kurse stammen von Crypto.com (USD-Paare, in der Frühzeit eventuell dünner Handel).
- **Ursachen der Phasen:** Nur dort genannt, wo sie allgemein bekannt sind, und nach meinem Kenntnisstand (nicht aus den Daten abgeleitet). Für 2026 nenne ich keine Ursachen.

