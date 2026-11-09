# Backtest: Elliott-Wellen-Strategie (BTC, ETH, SOL)

Alle Zahlen kommen aus dem Code (`python -m ewbot.backtest`). Erzeugt am 09.11.2026 00:08 UTC.

## Daten

| Coin | 30m-Kerzen | von | bis | 4h-Kerzen (ab) | Kursänderung im Testzeitraum |
|---|---|---|---|---|---|
| BTC_USD | 29999 | 22.02.2025 | 08.11.2026 | 11735 (01.07.2021) | -17 % |
| ETH_USD | 29999 | 22.02.2025 | 08.11.2026 | 11735 (01.07.2021) | -6 % |
| SOL_USD | 29999 | 22.02.2025 | 08.11.2026 | 11372 (30.08.2021) | -42 % |

Quelle: öffentliche Crypto.com-API (nur geschlossene Kerzen). Die ersten 600 Kerzen sind Anlaufzeit. Ausgewertet wird 06.03.2025 bis 08.11.2026. Der Download war auf 30 000 Kerzen je Coin begrenzt (ca. 20 Monate 30m); mehr wäre vermutlich möglich, wurde aber nicht geholt.

**Aufteilung:** erste 60 % (bis 08.03.2026) = *In-Sample* (hier wurde getestet und eingestellt), letzte 40 % = *Out-of-Sample* (blind, erst nach Festlegung der Parameter angeschaut). Ein Trade zählt zu dem Teil, in dem das Signal entstand.

## Annahmen der Simulation (vorsichtig)

- Kauf-Limit füllt, wenn das Tief der Kerze den Einstieg berührt (Fülpreis = Einstieg, keine Preisverbesserung). Maker-Gebühr **0,25 %** (Annahme).
- Stop (synthetisch, auf dem 30m-Tief): Berührt eine Kerze Stop und Ziel, gilt **der Stop zuerst**. Taker-Gebühr **0,50 %** (Annahme) plus **0,10 %** Slippage.
- In der Einstiegskerze werden Ziele nicht gewertet (Reihenfolge Hoch/Tief unbekannt). T1 verkauft 50 %, danach Stop auf Einstand; berührt die T1-Kerze auch den Einstand, wird der Rest dort gestoppt.
- Order verfällt nach 48 h oder wird gelöscht, wenn T1 vor dem Fill erreicht wird. Eine Position je Coin.
- R = Abstand Einstieg bis Stop. Alle Gebühren sind in R umgerechnet (Ø R netto = nach Gebühren).

## Parameter (Standardwerte)

```
deg_atr = 8.0
rally_min_pct = 0.2
lookback_4h = 1080
fib_ratios = (0.5, 0.618, 0.786)
abc_ratios = (0.618, 1.0, 1.272, 1.618)
zone_atr = 1.0
min_confluence = 1
confirm_pb_atr = None
k30 = 2.5
window_30m = 400
thrust_atr = 6.0
w1_min_atr = 3.5
entry_retr = 0.618
stop_buf_atr = 0.5
t1_r = 1.1
t2_proj = 1.618
min_rr_t2 = 1.5
max_stop_pct = 0.08
min_stop_pct = 0.004
expiry_h = 48
```

Eingestellt wurde nur im In-Sample, mit 16 Varianten in zwei kleinen Rastern (`--tune 1`, `--tune 2`; Ergebnisse in `data/hist/tune_is_stage*.json`). Regel: beste Ø R netto mit mindestens 20 Trades. Die Variante `min_confluence=2` hatte im In-Sample nur 6 Trades (Ø +0,58 R) und wurde deshalb **nicht** gewählt – sie wird unten nur als Zusatz gezeigt.

### EW-Strategie je Coin

| Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Profit-Faktor | Summe R | Max. DD (R) | 95 %-Bereich Ø R |
|---|---|---|---|---|---|---|---|---|---|
| BTC In-Sample | 29 | 12 | 42 % | -0.23 | +0.18 | 0.63 | -2.8 | 4.6 | [-0.87 ; +0.42] |
| BTC Out-of-Sample | 9 | 1 | 0 % | -1.67 | -1.08 | 0.00 | -1.7 | 1.7 | [-1.67 ; -1.67] |
| ETH In-Sample | 39 | 13 | 54 % | -0.31 | -0.04 | 0.51 | -4.1 | 7.1 | [-0.89 ; +0.29] |
| ETH Out-of-Sample | 15 | 6 | 17 % | -0.74 | -0.13 | 0.20 | -4.4 | 4.4 | [-1.55 ; +0.25] |
| SOL In-Sample | 31 | 9 | 67 % | +0.39 | +0.66 | 1.87 | +3.5 | 2.6 | [-0.56 ; +1.21] |
| SOL Out-of-Sample | 20 | 5 | 60 % | +0.12 | +0.55 | 1.36 | +0.6 | 1.6 | [-0.73 ; +0.86] |
| **Gesamt In-Sample** | 99 | 34 | 53 % | -0.10 | +0.22 | 0.83 | -3.3 | 12.3 | [-0.52 ; +0.30] |
| **Gesamt Out-of-Sample** | 44 | 12 | 33 % | -0.46 | +0.08 | 0.37 | -5.5 | 6.4 | [-1.13 ; +0.24] |

Portfolio-Rechnung (0,75 % Risiko je Trade, Gesamtrisiko-Exposure max. 90 %, mit Zinseszins):

- In-Sample: Rendite -3.3 %, max. Drawdown 8.9 %
- Out-of-Sample: Rendite -3.4 %, max. Drawdown 4.1 %

Out-of-Sample Signale nach Ausgang: {'missed': 30, 'filled': 11, 'expired': 2, 'open': 1}. 'missed' = T1 wurde erreicht, ohne dass der Einstieg gefüllt wurde; 'expired' = 48 h abgelaufen.

## Vergleich mit Zufalls-Einstiegen (gleiche Ausstiege)

Gleiche Geometrie wie die EW-Signale (Median aus dem In-Sample: Stop 2.05 % vom Einstieg, T1 1.10 R, T2 2.12 R, Limit 0.82 % unter dem Kurs), 48 h Verfall, gleiche Gebühren. Einstiege: alle 12 h (periodisch) bzw. zufällig (ca. 1 pro Tag, 5 Zufallsläufe zusammen).

| Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Profit-Faktor | Summe R | Max. DD (R) | 95 %-Bereich Ø R |
|---|---|---|---|---|---|---|---|---|---|
| EW-Strategie In-Sample | 99 | 34 | 53 % | -0.10 | +0.22 | 0.83 | -3.3 | 12.3 | [-0.52 ; +0.30] |
| EW-Strategie Out-of-Sample | 44 | 12 | 33 % | -0.46 | +0.08 | 0.37 | -5.5 | 6.4 | [-1.13 ; +0.24] |
| Periodisch (12 h) In-Sample | 1137 | 727 | 48 % | -0.34 | -0.02 | 0.53 | -250.5 | 252.2 | [-0.43 ; -0.26] |
| Periodisch (12 h) Out-of-Sample | 533 | 352 | 49 % | -0.33 | -0.01 | 0.54 | -116.5 | 128.9 | [-0.45 ; -0.21] |
| Zufall (5 Läufe) In-Sample | 3189 | 2071 | 46 % | -0.40 | -0.08 | 0.47 | -825.4 | 830.8 | [-0.45 ; -0.35] |
| Zufall (5 Läufe) Out-of-Sample | 1828 | 1155 | 50 % | -0.32 | -0.00 | 0.55 | -372.5 | 387.9 | [-0.39 ; -0.25] |

Lesehilfe: *Ø R brutto* ohne Gebühren zeigt, ob der Einstieg überhaupt etwas bringt. Zufalls-Einstiege liegen brutto bei ca. 0 R (kein Vorteil, wie erwartet).

## Gebühren-Szenario und Zusatzvariante

| Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Profit-Faktor | Summe R | Max. DD (R) | 95 %-Bereich Ø R |
|---|---|---|---|---|---|---|---|---|---|
| EW mit Maker 0,10 % / Taker 0,20 % (Szenario) In-Sample | 99 | 34 | 59 % | +0.09 | +0.22 | 1.19 | +3.2 | 9.6 | [-0.31 ; +0.48] |
| EW mit Maker 0,10 % / Taker 0,20 % (Szenario) Out-of-Sample | 44 | 12 | 58 % | -0.14 | +0.08 | 0.76 | -1.6 | 4.1 | [-0.75 ; +0.51] |
| EW `min_confluence=2` (Zusatz, nicht gewählt) In-Sample | 24 | 6 | 83 % | +0.58 | +0.79 | 3.99 | +3.5 | 1.2 | [-0.29 ; +1.24] |
| EW `min_confluence=2` (Zusatz, nicht gewählt) Out-of-Sample | 1 | 0 | 0 % | +0.00 | +0.00 | 0.00 | +0.0 | 0.0 | - |

Gebühren kosten im Schnitt 0.54 R je Trade (Out-of-Sample), weil der Stop nur ca. 2.0 % entfernt ist und Kauf plus Verkauf zusammen oft 0,5–0,75 % kosten.

## Urteil

- Out-of-Sample **negativ nach Gebühren**. Ø R netto -0.46, Ø R brutto +0.08, Profit-Faktor 0.37. Nur 12 Trades Out-of-Sample: das ist zu wenig für ein sicheres Urteil.
- In-Sample war das Ergebnis Ø R netto -0.10 (brutto +0.22) – also schon beim Einstellen kein Gewinn nach Gebühren.
- Gegen Zufall: Out-of-Sample brutto EW +0.08 R vs. Zufall -0.00 R. Kein klarer Vorteil des EW-Filters gegenüber Zufall.
- **Fazit: Mit den angenommenen Gebühren (0,25 % / 0,50 %) ist keine tragfähige Kante nachgewiesen.** Die Strategie sollte nur im Papier-Modus laufen, bis deutlich mehr Trades vorliegen oder die Gebühren sinken. Kein Echtgeld auf Basis dieses Backtests.
- Warum so wenige Trades: Es braucht eine große 4h-Rally, einen scharfen Abverkauf in eine Fibonacci-Zone und eine bestätigte Erholung. Nur 27 % der Signale werden gefüllt (Out-of-Sample), bei den übrigen läuft der Kurs vorher zu T1 weg oder die 48 h laufen ab.

**Grenzen:** nur ca. 20 Monate Daten, ein Marktzyklus; 3 Coins stark korreliert (die Trades sind nicht unabhängig); 16 Varianten getestet (Mehrfachtest-Effekt); Gebühren sind Annahmen; 30m-Kerzen kennen die Reihenfolge von Hoch und Tief nicht (daher die vorsichtigen Regeln); die manuelle Methode enthält Ermessen, das ein Skript nicht abbildet.

## Vergleich mit den manuellen Signalen vom 08.11.2026

`find_signals` auf den zwischengespeicherten Daten `data/*_30m.json` (Stand 08.11.2026 ca. 23:00 UTC) mit den Standardwerten und mit der Variante `zone_atr=2.0` (wie großzügig der manuelle BTC-Einstieg war):

| Coin | manuell (Einstieg / Stop / T1 / T2) | Bot Standard | Bot `zone_atr=2.0` |
|---|---|---|---|
| BTC | 73900 / 72400 / 75600 / 76900 | kein Signal | 73857.01 / 72527.28 / 75319.71 / 76107.42 |
| ETH | 2090 / 1990 / 2200 / 2280 | 2087.55 / 2054.78 / 2137.22 / 2217.60 | 2087.55 / 2054.78 / 2137.22 / 2217.60 |
| SOL | 85.6 / 83.4 / 88.8 / 91.4 | 85.70 / 84.69 / 86.97 / 89.02 | 85.70 / 84.69 / 86.97 / 89.02 |

- BTC: 4h-Rally 57,737 -> 87,428; Rueckgang bisher 44 % der Rally. Level: rally 50.0% 72,582, rally 61.8% 69,079, rally 78.6% 64,091
- ETH: 4h-Rally 1,505 -> 2,808; Rueckgang bisher 53 % der Rally. Level: rally 50.0% 2,156, rally 61.8% 2,002, rally 78.6% 1,783, C=0.618A 2,329, C=1A 2,175, C=1.272A 2,066, C=1.618A 1,926
- SOL: 4h-Rally 60.10 -> 124.95; Rueckgang bisher 60 % der Rally. Level: rally 50.0% 92.53, rally 61.8% 84.87, rally 78.6% 73.98

Unterschiede und Gründe:
- Die **4h-Rally und die Fibonacci-Level stimmen genau** mit der manuellen Rechnung überein (z. B. BTC 57 737 -> 87 428, 50 % = 72 582; SOL 61,8 % = 84,87).
- **ETH und SOL** werden mit den Standardwerten reproduziert. Einstiege liegen nah an den manuellen (ETH 2 087,55 statt 2 090; SOL 85,70 statt 85,60), weil beide bei 61,8 % der Welle 1 liegen (Welle-1-Hoch ETH 2 137,22 exakt wie manuell).
- **Stops und Ziele sind anders**: Der Bot setzt den Stop knapp unter Welle-Tief bzw. das Level darunter (minus 0,5 ATR), also eng (ca. 1–1,5 %). Die manuellen Stops waren weiter (2–5 %). Dafür liegt T1 beim Bot am Welle-1-Hoch (mindestens 1,1 R) und T2 bei 1,618 x Welle 1; manuell waren die Ziele etwas höher.
- **BTC**: Das Tief 73 326 liegt 743 USD über dem 50-%-Level (mehr als 1 ATR(4h)). Mit Standard `zone_atr=1.0` gibt es kein Signal; mit `zone_atr=2.0` entsteht fast der manuelle Einstieg (73 857 statt 73 900). Die manuelle Methode war hier großzügiger.
- **ETH, C-Projektion**: Der Bot findet die A-B-C-Punkte automatisch (4h-Zickzack). Sein Treffer ist C=1,272 x A bei 2 066 statt der manuellen C-Marke 2 055. Das Signal hängt an dieser einen Zone.
- Der Bot arbeitet nur mit **geschlossenen Kerzen** und wartet bis die Erholung (Welle 1) groß genug ist; die manuellen Signale waren Vorab-Limits.
- Bei den Standardwerten wird die Zone nur gewertet, wenn der Abverkauf davor scharf war (6 ATR) und die Erholung mindestens 3,5 ATR beträgt. Die ATR stammt aus der ruhigen Zeit vor dem Abverkauf, sonst würde der Crash die Schwellen selbst hochtreiben.
