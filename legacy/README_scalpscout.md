# ScalpScout – MT4-Scalping-Assistent (M1)

**Kernaussage:** ScalpScout beobachtet im Ein-Minuten-Chart, ob der Kurs plötzlich kräftig und mit auffallend viel Handelsaktivität in eine Richtung ausbricht. Wenn ja, zeigt er dir einen fertigen Vorschlag (Einstieg, Stop-Loss, Take-Profit, Positionsgröße) und wartet auf deinen Klick. Auf Wunsch handelt er auch selbst oder meldet nur per Alarm und Handy-Nachricht. Eingebaute Schutzregeln begrenzen das Risiko, ersetzen aber nie dein eigenes Urteil. Gewinne sind nicht zugesagt.

Der EA ist symbolneutral (EURUSD, GBPUSD, XAUUSD, DAX/US30 und andere, auch mit Broker-Suffix). Alle Abstände werden aus der Schwankung (ATR) und den Punktwerten des jeweiligen Symbols berechnet.

## Dateien

| Datei | Zweck |
|---|---|
| `MQL4/Experts/ScalpScout.mq4` | der Expert Advisor mit der Ausbruchs-Strategie (UTF-8 mit BOM, damit Umlaute in MetaEditor stimmen) |
| `MQL4/Experts/ScalpScoutTrend.mq4` | zweiter, eigenständiger EA mit der Trend-Pullback-Strategie (AVWAP), siehe Abschnitt „Zweiter EA: ScalpScout Trend“ |
| `MQL4/Experts/ScalpScoutAsia.mq4` | dritter, eigenständiger EA: Opening-Range-Breakout auf USDJPY zur Tokio- und London-Eröffnung inkl. Folge-Scalps, siehe Abschnitt „Dritter EA: ScalpScout Asia“ |
| `README.md` | diese Anleitung |
| `.gitignore` | ignoriert `*.ex4` und `*.log` |

## So arbeitet er

1. Einmal pro neuer M1-Kerze wird die **zuletzt geschlossene Kerze** geprüft.
2. **Long**, wenn alles gleichzeitig stimmt:
   - Kerzenkörper größer als `ImpulsFaktor` × ATR(14),
   - Tick-Volumen größer als `VolumenFaktor` × Durchschnitt der 20 Kerzen davor,
   - Schluss über dem Hoch der vorherigen `BreakoutKerzen` Kerzen (Ausbruch),
   - Trendfilter (abschaltbar): Schluss über EMA(50).
   **Short** ist das Spiegelbild.
3. SL = `SL_ATR` × ATR, TP = `TP_ATR` × ATR (mindestens der vom Broker verlangte Mindestabstand).
4. Lot = Risiko in Geld ÷ Verlust pro Lot bei SL, auf die Lot-Schrittweite abgerundet und durch `MaxLot` gedeckelt. Ist das Lot kleiner als das Broker-Minimum, wird **nicht** gehandelt (das Risiko wird nie überschritten); der Grund steht im Info-Bereich.
5. Schutzfilter (Spread, Handelszeit, Tagesverlust, Positionslimit, Pause nach Verlustserie) gelten in allen Modi.

## Installation in MT4

1. In MT4: **Datei → Datenordner öffnen**.
2. `ScalpScout.mq4` nach `MQL4/Experts/` kopieren.
3. MetaEditor öffnen (**F4**), Datei öffnen und mit **F7** kompilieren. Es darf kein Fehler erscheinen (Datei `ScalpScout.ex4` entsteht).
4. In MT4 im Navigator mit Rechtsklick **Aktualisieren**.
5. Oben in der Symbolleiste **„Algo-Trading“ (AutoTrading)** einschalten (Knopf muss grün sein).
6. Einen **M1-Chart** des gewünschten Symbols öffnen und den EA aus dem Navigator auf den Chart ziehen.
7. Im Reiter **Allgemein** den Haken **„Live-Handel erlauben“** setzen, im Reiter **Eingaben** die Werte prüfen, **OK**.
8. Oben rechts im Chart muss neben dem EA-Namen ein lachendes Gesicht stehen. Links oben erscheint der Info-Bereich.

Tipp: Pro Symbol nur einen Chart mit dem EA und eine eigene `MagicNumber` je Chart verwenden, wenn mehrere Charts laufen. Für Push-Nachrichten unter **Extras → Optionen → Benachrichtigungen** die MetaQuotes-ID aus der MT4-App eintragen und `PushAktiv` einschalten.

## Bedienung

**Info-Bereich (links oben, immer sichtbar, auf dunklem Hintergrund):** Modus, Kosten aktuell/maximal (Spread + Kommission), ATR, Serverzeit mit Handelsfenster, Tagesergebnis, Status des Verlustlimits, Blockadegrund (falls der Handel gerade gesperrt ist), Telegram-Status (aus / verbunden / Fehler mit Code), letzter Hinweis (z. B. „Lot zu klein“).

**Signal-Fenster (nur Modus Manuelle Freigabe):** Bei einem Signal erscheint ein Fenster mit Richtung, Einstieg, SL, TP, Lot, Spread, CRV und Restzeit. Dazu Alarm, Ton und optional Push.

| Knopf | Wirkung |
|---|---|
| **[+] Ausführen** (grün) | Holt aktuelle Preise, setzt SL/TP neu relativ zum aktuellen Preis, prüft alle Filter erneut und sendet die Order (bei Requote bis zu `OrderVersuche` Versuche). |
| **[–] Verwerfen** (rot) | Schließt das Fenster, es wird nichts gehandelt. |
| **ALLES SCHLIESSEN** | Fragt per Bestätigungsfenster nach und schließt dann alle Positionen mit eigener `MagicNumber` auf diesem Symbol. Danach sind neue Trades gesperrt, bis der EA neu gestartet wird (Chart: EA entfernen und neu aufziehen oder Eingaben ändern). |

Das Signal verfällt nach `SignalGueltigSek` Sekunden oder wenn sich der Preis mehr als `PreisAbweichungATR` × ATR vom Signalpreis entfernt hat.

**Modi:**
- `MANUELLE_FREIGABE` (Standard): Vorschlag mit Knöpfen, du entscheidest.
- `VOLLAUTOMATIK`: Der EA eröffnet direkt. Alle Filter gelten.
- `NUR_SIGNALE`: Nur Alarm/Push, kein Trade.

Im **Strategietester** wird `MANUELLE_FREIGABE` automatisch wie `VOLLAUTOMATIK` behandelt (steht im Journal), sonst könnte kein Backtest laufen.

## Inputs

„Punkte“ sind die kleinste Preisstufe des Symbols (`Point`). Bei 5-stelligen Forex-Kursen sind 10 Punkte = 1 Pip.

| Input | Standard | Bedeutung |
|---|---|---|
| `Modus` | MANUELLE_FREIGABE | Betriebsart (siehe oben) |
| `PushAktiv` | false | Push-Nachricht an MT4-Mobile bei Signal |
| `SignalGueltigSek` | 45 | Gültigkeit eines Signals in Sekunden |
| `PreisAbweichungATR` | 0.3 | Signal verfällt, wenn Preis weiter als x × ATR weg ist |
| `Slippage` | 3 | Erlaubte Abweichung in Pips; bei 3/5-stelligen Kursen automatisch ×10 in Punkte (bei Indizes/Gold prüfen) |
| `OrderVersuche` | 3 | Maximale Versuche bei Requote / Preisänderung |
| `ATR_Periode` | 14 | ATR-Periode auf M1 |
| `ImpulsFaktor` | 1.8 | Körper der Kerze > x × ATR |
| `VolumenFaktor` | 1.5 | Tick-Volumen > x × Durchschnitt |
| `VolumenKerzen` | 20 | Kerzen für das Durchschnittsvolumen (ohne Signalkerze) |
| `BreakoutKerzen` | 10 | Ausbruch über Hoch/Tief der letzten N Kerzen |
| `TrendFilterAktiv` | true | Trendfilter an/aus |
| `EMA_Periode` | 50 | EMA-Periode des Trendfilters |
| `SL_ATR` | 1.0 | Stop-Loss in Vielfachen der ATR |
| `TP_ATR` | 1.5 | Take-Profit in Vielfachen der ATR |
| `BE_Aktiv` | true | Break-even an/aus |
| `BE_ATR` | 0.8 | Break-even ab Gewinn von x × ATR |
| `BE_PufferPunkte` | 0 | Puffer über/unter dem Einstieg beim Break-even |
| `TrailingAktiv` | false | Trailing-Stop an/aus |
| `TrailingStartATR` | 1.0 | Trailing beginnt ab Gewinn von x × ATR |
| `TrailingATR` | 0.7 | Abstand des Trailing-Stops in × ATR |
| `TrailingSchrittATR` | 0.1 | SL wird nur nachgezogen, wenn er sich um mind. x × ATR verbessert |
| `RisikoProzent` | 1.0 | Risiko pro Trade in % vom Equity |
| `MaxLot` | 0.01 | Harter Lot-Deckel für den Live-Start |
| `MaxSpreadPunkte` | 0 | Max. Kosten (Spread + Kommission) in Punkten; 0 = automatisch |
| `SpreadAnteilTP` | 0.25 | Automatik: Kosten (Spread + Kommission) müssen kleiner sein als dieser Anteil der TP-Distanz |
| `KommissionProLot` | 0.0 | Kommission pro Lot, Hin- und Rückweg zusammen, in Kontowährung (ECN-Konten); 0 = keine |
| `HandelStart` | 08:00 | Beginn Handelsfenster (Serverzeit, HH:MM) |
| `HandelEnde` | 20:00 | Ende Handelsfenster (Serverzeit); Fenster über Mitternacht ist möglich |
| `TagesVerlustProzent` | 3.0 | Verlustlimit je Tag vom Tagesbeginn-Equity; danach keine neuen Trades bis zum nächsten Tag (0 = aus) |
| `MaxOffenePositionen` | 1 | Max. offene Positionen pro Symbol |
| `PauseNachVerlusten` | 3 | Pause nach N Verlusten in Folge (0 = aus) |
| `PauseMinuten` | 30 | Länge der Pause |
| `MagicNumber` | 26101801 | Kennung der EA-Trades |
| `TelegramAktiv` | false | Telegram-Fernbedienung ein/aus (im Strategietester immer aus) |
| `TelegramToken` | leer | Bot-Token von @BotFather (nie weitergeben) |
| `TelegramChatID` | leer | Deine Chat-ID; nur dieser Chat darf den EA steuern |
| `TelegramAbfrageSek` | 2 | Abfrageintervall in Sekunden |
| `TelegramMeldeSchliessung` | true | Nachricht, sobald eine Position geschlossen wurde (mit Ergebnis und Grund TP/SL/manuell, falls erkennbar) |

## ECN-Symbole (.ecn)

Bei ECN-Konten ist der Spread sehr klein, dafür kommt eine **Kommission pro Lot** dazu. Sie gehört zu den Handelskosten, deshalb rechnet der EA sie mit:

- Kosten = Spread + Kommission (beides in Punkten). Diese Kosten werden gegen die erlaubte Obergrenze geprüft; der Grund steht im Info-Bereich („Kosten zu hoch (Spread X + Komm. Y > Z Pkt)“).
- Die Kommission fließt in die Lotberechnung ein: Verlust pro Lot = SL-Verlust + Kommission. So bleibt das Risiko in Prozent des Equity eingehalten.

**Kommission eintragen:** In MT4 in der Marktübersicht (Strg+M) das Symbol mit Rechtsklick → **Spezifikation** öffnen und die Kommission ablesen. Bei `KommissionProLot` den Betrag für **Hin- und Rückweg zusammen** in Kontowährung eintragen. Nennt der Broker nur „pro Seite“, den Wert verdoppeln. Im Zweifel beim Broker nachfragen; einen geschätzten Wert nicht übernehmen.

**Empfohlenes Symbol:** `EURUSD.ecn` im M1-Chart. Dort ist der Spread klein und die Kosten sind gut planbar.

**Krypto (z. B. BTCUSD) ist ungeeignet:** Der Spread ist dort größer als die typische Bewegung in einer Minute. Der Kostenfilter würde fast jedes Signal sperren, und was durchkommt, hat kaum Chance, die Kosten zu verdienen.

## Freigabe per Handy (Telegram)

**Kernaussage:** Statt am PC auf den Knopf zu klicken, bekommst du das Signal als Telegram-Nachricht mit den Knöpfen **JA** und **NEIN**. Ein Druck auf JA wirkt genau wie der Klick auf „[+] Ausführen“ am PC: Der EA rechnet neu und prüft alle Filter, bevor er handelt. Der PC mit MT4 muss dafür laufen.

**Einrichtung, Schritt für Schritt:**

1. Telegram-App installieren, darin **@BotFather** öffnen, `/newbot` senden, einen Namen vergeben und den **Token** kopieren (sieht aus wie `123456789:ABC...`).
2. Den neuen Bot in Telegram suchen, öffnen und **Start** drücken (oder ihm eine Nachricht schicken). Ohne diesen Schritt darf der Bot dir nicht schreiben.
3. **Chat-ID herausfinden:** Im Browser `https://api.telegram.org/bot<TOKEN>/getUpdates` öffnen (`<TOKEN>` durch deinen Token ersetzen) und bei `"chat":{"id":` die Zahl ablesen. Alternativ den Bot **@userinfobot** nach deiner ID fragen. Diese Adresse nur im eigenen Browser öffnen, den Link nicht teilen.
4. In MT4 **Extras → Optionen → Expert Advisors**: „WebRequest für folgende URLs erlauben“ anhaken und `https://api.telegram.org` hinzufügen. Ohne diesen Schritt meldet der EA Fehler 4060.
5. EA-Eigenschaften → **Eingaben**: `TelegramAktiv` = true, `TelegramToken` und `TelegramChatID` eintragen.
6. **Test:** In Telegram `/status` an den Bot schicken. Er antwortet mit Modus, Kosten, Tagesergebnis, offenen Positionen und dem Grund einer eventuellen Sperre. Beim Start schickt der EA außerdem eine Begrüßung.

**Was du bekommst und steuern kannst:**

| Aktion | Wirkung |
|---|---|
| Signal im Modus `MANUELLE_FREIGABE` | Nachricht mit Symbol, Kauf/Verkauf, Einstieg, SL, TP, Lot, Kosten, CRV und den Knöpfen JA / NEIN (zusätzlich zum Chart-Fenster) |
| Signal im Modus `NUR_SIGNALE` | Nachricht ohne Knöpfe |
| Modus `VOLLAUTOMATIK` | Nur eine Info-Nachricht nach der Ausführung |
| **JA** | Order wird wie bei „[+] Ausführen“ eröffnet; die Nachricht zeigt „ausgeführt: #Ticket @Preis“ oder den Grund, warum nicht |
| **NEIN** | Signal wird verworfen, die Nachricht zeigt „verworfen“ |
| Signal abgelaufen oder am PC erledigt | Nachricht wird entsprechend geändert, die Knöpfe verschwinden |
| `/status` | Statusbericht |
| `/stop` | Neue Signale pausieren (Info-Bereich zeigt „Pausiert per Telegram“) |
| `/start` | Pause aufheben |
| Position geschlossen | „Position #x geschlossen: +/-Betrag (TP/SL/manuell)“ (abschaltbar mit `TelegramMeldeSchliessung`) |

**Sicherheit:**

- Den **Token niemals** in Dateien, Screenshots, Chats oder ins Repo schreiben. Er gehört nur in die EA-Eingaben. Ist er doch rausgegangen: bei @BotFather `/revoke` senden und einen neuen Token eintragen.
- Der EA reagiert nur auf die eingetragene `TelegramChatID`; Nachrichten und Knopfdrücke aus anderen Chats werden ignoriert (Vermerk im Journal).
- Pro Bot nur **einen** EA/Chart betreiben. Mehrere EAs mit demselben Bot nehmen sich gegenseitig die Updates weg.
- Der PC mit MT4 muss laufen und online sein.
- Ein Signal gilt nur `SignalGueltigSek` (Standard 45 Sekunden). Bei schlechtem Netz kommt die Nachricht oder dein Druck evtl. zu spät: Dann verfällt das Signal und es passiert nichts.
- Hat der Bot einen Webhook gesetzt, liefert Telegram keine Updates per Abfrage (Fehler 409 im Info-Bereich).

## Backtest (Strategietester)

1. **Ansicht → Strategietester** (Strg+R).
2. Expert Advisor: `ScalpScout`, Symbol wählen, Zeitraum **M1**.
3. Modell: **„Jeder Tick“** (für Scalping nötig; Kontrollpunkte/Eröffnungskurse sind zu grob).
4. Zeitraum und „Spread“ setzen. Für realistische Ergebnisse den **typischen Live-Spread des Brokers fest eintragen** (nicht „Aktuell“ mit Nachtspreads). Wenn möglich, Tick-Daten hoher Qualität verwenden.
5. Eingaben prüfen. Im Tester wird der Freigabe-Modus automatisch zur Vollautomatik. Hinweis: Tick-Volumen im Tester entsteht aus erzeugten Ticks und ist nur eine Näherung der Live-Aktivität.
6. Mit „Visualisierung“ kannst du Einstiege auf dem Chart nachvollziehen.
7. Ergebnisse nie als Prognose lesen. Erst auf Demokonto vorwärts testen (siehe Fahrplan).

## Zweiter EA: ScalpScout Trend

**Kernaussage:** ScalpScout Trend wartet im Ein-Minuten-Chart auf einen klaren Trend und steigt erst ein, wenn der Kurs zurückgekommen ist und wieder in Trendrichtung dreht. Als Maßstab für „zurückgekommen“ dient ein durchschnittlicher Kurs, der an einem Wendepunkt des Trends beginnt und das Handelsvolumen berücksichtigt (Anchored VWAP, kurz AVWAP). Er rechnet vorab nach, ob Chance und Risiko nach Kosten zusammenpassen, und handelt sonst nicht.

Der EA ist eine **eigene Datei** (`ScalpScoutTrend.mq4`) und läuft unabhängig von `ScalpScout`. Er hat eigene Magic Number (26101802), eigene Objekte im Chart (Präfix `SST_`) und eigene globale Variablen für den Tagesstart. Beide EAs können deshalb parallel laufen, am besten auf verschiedenen Charts/Symbolen. Alles andere ist aus `ScalpScout` übernommen: Freigabe-Modi (Panel [+]/[–], Telegram JA/NEIN, `NUR_SIGNALE`, `VOLLAUTOMATIK`), Lot aus Risiko % inkl. Kommission, `MaxLot`, Break-even/Trailing, Schutzfilter (Handelszeit, Tageslimit, Verlustserie, max. Positionen, Kill-Switch, Telegram-Pause).

**Regeln (nur auf der geschlossenen Kerze, einmal pro neuer M1-Kerze):**

1. **Trend:** Swing-Hoch/-Tief = Kerze, deren Hoch bzw. Tief höher bzw. tiefer ist als bei den `SwingStaerke` Kerzen links und rechts (nur bestätigte). Aufwärts, wenn die letzten zwei Swing-Tiefs steigen (bei `TrendNurTiefs = false` zusätzlich die Hochs); abwärts, wenn die letzten zwei Swing-Hochs fallen (bzw. zusätzlich die Tiefs). Sonst oder bei Widerspruch: seitwärts, kein Signal („Kein Trend“).
2. **AVWAP:** Anker ist der Beginn der Trendbewegung, also das älteste Swing-Tief der ununterbrochenen Kette steigender Tiefs (abwärts: das älteste Swing-Hoch der Kette fallender Hochs). AVWAP = Summe(typischer Preis (H+L+C)/3 × Tick-Volumen) ÷ Summe(Tick-Volumen) vom Anker bis zur letzten geschlossenen Kerze. Er wird als goldene Linie (die letzten max. 200 Kerzen) gezeichnet.
3. **Farbwechsel:** Long: Kerze 2 rot, Kerze 1 grün, Schluss von Kerze 1 über dem AVWAP. Short spiegelbildlich. Mit `VWAP_Pflicht` muss das Tief der Formation (Kerzen 1–2) den AVWAP bis auf `VWAP_NaeheATR` × ATR erreicht haben.
4. **Doppellunte:** Zwei der Kerzen 1–3 haben fast gleiche Tiefs (Abstand höchstens `DoppelLunteToleranzATR` × ATR) und jeweils eine untere Lunte, die länger als der Körper ist; Kerze 1 schließt grün. Short mit Hochen, oberen Lunten und roter Kerze 1. AVWAP-Nähe wie bei 3, gemessen am tiefsten Tief der Kerzen 1–3.
5. **Stop-Loss:** Long: tiefstes Tief der Formation minus `SL_PufferATR` × ATR. Short: höchstes Hoch plus Puffer plus Spread (Short-SL wird am Ask ausgelöst).
6. **Ziel:** Long: nächstes Swing-Hoch über dem aktuellen Ask, minus `TP_PufferATR` × ATR. Short: nächstes Swing-Tief unter dem Bid, plus Puffer. Gibt es keins, kein Signal („Kein Ziel oberhalb/unterhalb“).
7. **MinCRV:** CRV nach Kosten = (TP-Abstand − Kosten) ÷ (SL-Abstand + Kosten), Kosten = Spread + Kommission. Unter `MinCRV` kein Signal („CRV x.x < MinCRV“). Außerdem müssen SL und TP den Mindestabstand (StopLevel) des Brokers einhalten.
8. **Bruch-Sperre:** Aufwärtstrend: Wurde das letzte Swing-Hoch danach überschritten und ist seitdem noch kein neues Swing-Tief bestätigt, kein Long („Hoch gebrochen – warte auf höheres Tief“). Abwärts spiegelbildlich.
9. **M5-Filter:** Long nur, wenn der letzte geschlossene M5-Schluss über der M5-EMA liegt, Short umgekehrt.
10. **News-Pausen:** In den Fenstern von `NewsPausen` (Serverzeit) kommen keine neuen Signale und keine Ausführungen.

**Ausführung:** SL und TP sind feste Preise aus der Struktur (keine ATR-Vielfachen). Beim Klick auf [+], bei Telegram JA und in der Vollautomatik prüft der EA mit dem aktuellen Kurs neu: SL/TP auf der richtigen Seite mit Mindestabstand, CRV nach Kosten weiter ≥ `MinCRV`. Sonst steht im Info-Bereich „Nicht ausgeführt: CRV nach Kursänderung zu klein“. Das Lot kommt wie gewohnt aus dem Risiko bezogen auf den SL-Abstand inkl. Kommission. Ein fester `MaxSpreadPunkte` > 0 gilt weiterhin, sonst ersetzt die CRV-Prüfung den Kostenfilter. Im Signal-Fenster stehen Signaltyp und CRV nach Kosten; solange ein Signal wartet, zeigen rote/grüne Linien SL und TP.

**Hinweis:** Diese Regeln sind eine mechanische Annäherung an ein Scalping-Video. Ermessensentscheidungen eines Traders (welches Hoch „zählt“, wann ein Rücksetzer „sauber“ aussieht) lassen sich nicht 1:1 abbilden. Deshalb zuerst im Strategietester prüfen, dann auf Demo.

**Empfohlene Symbole:** Index-CFD auf den S&P 500 (z. B. US500/SPX500, Name beim Broker nachsehen) oder `EURUSD.ecn`. Welche Kosten (Spread, Kommission) im Verhältnis zu den Zielen anfallen, entscheidet über das CRV und damit darüber, wie oft überhaupt gehandelt wird.

**Installation:** identisch zu `ScalpScout` (Datei nach `MQL4/Experts/`, mit F7 kompilieren, Navigator aktualisieren, AutoTrading an, EA auf einen M1-Chart ziehen, „Live-Handel erlauben“). Die Info-Box zeigt zusätzlich „Strategie: Trend-Pullback | Trend | AVWAP | Ziel“ und den Grund der letzten Prüfung.

**Telegram:** Alle Nachrichten dieses EAs beginnen mit `[Trend]`. **Beide EAs nie mit demselben Telegram-Bot gleichzeitig betreiben**, sonst stehlen sie sich gegenseitig die Updates (JA/NEIN-Knöpfe kommen beim falschen EA an oder gehen verloren). Dafür bei @BotFather mit `/newbot` einen zweiten Bot anlegen und dessen Token in `ScalpScoutTrend` eintragen.

**Inputs von ScalpScout Trend** (Gruppen Betrieb, Ausstieg, Risiko, Schutzfilter und Telegram wie oben, Standard `MagicNumber` = 26101802; entfallen sind die Ausbruchs-Inputs sowie `SL_ATR`, `TP_ATR`, `SpreadAnteilTP`; `MaxSpreadPunkte` = 0 bedeutet hier „unbegrenzt“):

| Input | Standard | Bedeutung |
|---|---|---|
| `ATR_Periode` | 14 | ATR-Periode auf M1 (für Puffer, Nähe, Toleranz) |
| `SwingStaerke` | 3 | Kerzen links/rechts für Swing-Hoch/-Tief |
| `SwingLookback` | 300 | Suchtiefe in Kerzen |
| `TrendNurTiefs` | true | Trend nur über die Tiefs (false: zusätzlich Hochs; abwärts spiegelbildlich) |
| `TrendM5Filter` | true | Long nur über, Short nur unter der M5-EMA |
| `M5_EMA_Periode` | 50 | EMA-Periode auf M5 |
| `VWAP_Pflicht` | true | Rücksetzer muss den AVWAP berührt haben |
| `VWAP_NaeheATR` | 0.3 | „Berührt“ = bis x × ATR an den AVWAP heran |
| `DoppelLunteAktiv` | true | Doppellunte als zweiten Signaltyp zulassen |
| `DoppelLunteToleranzATR` | 0.15 | Max. Abstand der beiden Tiefs/Hochs in × ATR |
| `SL_PufferATR` | 0.1 | Puffer hinter der Formation in × ATR |
| `TP_PufferATR` | 0.05 | Puffer vor dem Ziel in × ATR |
| `MinCRV` | 2.0 | Mindest-CRV nach Kosten |
| `BruchSperreAktiv` | true | Bruch-Sperre (Regel 8) |
| `NewsPausen` | leer | Serverzeit-Fenster „HH:MM-HH:MM“, mehrere mit Komma, z. B. `15:25-15:45` |

**Beide EAs im Strategietester vergleichen:** Zuerst `ScalpScout` testen, dann `ScalpScoutTrend`, mit demselben Symbol, Zeitraum, Modell „Jeder Tick“ und demselben festen Spread (und gleicher `KommissionProLot`), `RisikoProzent` und `MaxLot`. Danach Anzahl Trades, Trefferquote, durchschnittliches CRV, Profitfaktor und maximalen Rückgang gegenüberstellen. Nur mit Zahlen vergleichen, nie mit dem Eindruck einzelner Trades. Der Freigabe-Modus wird im Tester automatisch zur Vollautomatik; Telegram ist im Tester aus. Das Tick-Volumen im Tester ist eine Näherung, der AVWAP daher ebenfalls.

## Dritter EA: ScalpScout Asia

**Kernaussage:** ScalpScout Asia nutzt aus, dass sich der Dollar-Yen-Kurs (USDJPY) rund um die Börsen-Eröffnung in Tokio und in London besonders stark bewegt. Er misst, wie weit der Kurs sich vorher bewegt hat (die „Range“), und steigt ein, sobald der Kurs deutlich und mit auffallend viel Handelsaktivität darüber oder darunter ausbricht. Danach scalpt er in diese Ausbruchsrichtung mehrfach weiter, solange das jeweilige Zeitfenster (Tokio, später London) offen ist. Feste Schutzregeln begrenzen das Risiko, ersetzen aber nie dein eigenes Urteil. Gewinne sind nicht zugesagt.

Der EA ist eine **eigene Datei** (`ScalpScoutAsia.mq4`) und läuft unabhängig von `ScalpScout` und `ScalpScoutTrend`. Er hat eigene Magic Number (26101803), eigene Objekte im Chart (Präfix `SSA_`), eigene globale Variablen (`SSA_...`) für Tagesstart und Fern-Einstellungen und kennzeichnet seine Telegram-Nachrichten mit `[Asia]`. Alles andere ist aus `ScalpScout` übernommen: Freigabe-Modi (Panel [+]/[–], Telegram JA/NEIN, `NUR_SIGNALE`, `VOLLAUTOMATIK`), Lot aus Risiko % inkl. Kommission, `MaxLot`/`FernMaxLotObergrenze`, Break-even/Trailing, Schutzfilter (Handelszeit, Tageslimit, Verlustserie-Pause, max. offene Positionen, Kill-Switch, Telegram-Pause), Tagesbericht, `/diag`, `/heute`, `/status`, `/kauf`, `/verkauf` usw.

**Zwei Phasen pro Serverzeit-Tag** (alle Zeiten in Serverzeit, Standardwerte):

| | Phase 1 „Tokio“ | Phase 2 „London“ |
|---|---|---|
| Range | `RangeStart` 03:00 bis `RangeEnde` 04:00 | `RangeStart` 03:00 (gleicher Beginn) bis `LondonStart` 10:00, also die ganze Asien-Session |
| Range gültig, wenn Breite | 0.8 bis 3.0 × ATR(H1) | 1.0 bis 5.0 × ATR(H1) (`LondonRangeMinATR`/`LondonRangeMaxATR`) |
| Einstiegsfenster | `HandelStart` 04:00 bis `HandelEnde` 07:00 | `LondonStart` 10:00 bis `LondonEnde` 12:00 |

Die London-Phase lässt sich mit `LondonAktiv = false` abschalten. Um `SchlussZeit` (13:00) werden alle eigenen Positionen geschlossen.

**Regeln (nur auf der geschlossenen Kerze, einmal pro neuer M1-Kerze, je Phase):**

1. **Range:** höchstes Hoch und tiefstes Tief der M1-Kerzen, deren Öffnungszeit im Range-Fenster des heutigen Tages liegt. Der EA liest sie aus der M1-Historie und funktioniert deshalb auch, wenn er erst nach dem Range-Ende angehängt wird. Gültig nur, wenn die Breite zwischen Min und Max × ATR(H1, letzte geschlossene Stunde) liegt. Die Range wird im Chart als zwei Linien gezeichnet (Tokio gold, London blau, ungültig grau).
2. **Ausbruch (ORB, erster Trade der Phase):** Long, wenn eine Kerze nach dem Range-Ende (a) bullisch ist, (b) mit `AusbruchPufferPips` über dem Range-Hoch schließt, (c) Tick-Volumen größer als `VolumenFaktor` × Durchschnitt der `VolumenKerzen` Kerzen davor hat und (d) über der EMA(50, H1) schließt (abschaltbar mit `TrendFilterAktiv`). Short ist das Spiegelbild. Das Signal gilt nur im Einstiegsfenster.
3. **Phasen-Richtung:** Beim ersten gültigen Ausbruch steht die Richtung der Phase für den Rest des Tages fest, auch wenn dieses Signal abgelehnt, verworfen oder blockiert wurde. Gegenrichtung gibt es in dieser Phase nicht mehr.
4. **Folge-Scalps** (`FolgeTradesAktiv`): Danach prüft der EA jede neue Kerze nur noch in Phasen-Richtung. Long, wenn die Kerze bullisch ist, über dem Hoch der letzten `FolgeAusbruchKerzen` (5) Kerzen schließt, das Volumen größer als `FolgeVolumenFaktor` × Durchschnitt ist und der Kurs noch auf der Ausbruchsseite der Range-Mitte liegt (über der Mitte bei Long, unter der Mitte bei Short). Der Trendfilter gilt hier nicht.
5. **Stop-Loss/Take-Profit:** Beim Ausbruch liegt der SL in der Range-Mitte, höchstens `SL_MaxATR` (0.75) × ATR(H1) vom Einstieg entfernt. Beim Folge-Scalp ist der SL `FolgeSL_ATR` (1.0) × ATR(M1). Immer gilt: mindestens StopLevel + Spread des Brokers, TP = `TP_CRV` (1.5) × SL-Abstand.
6. **Grenzen:** höchstens `MaxTradesProPhase` (10) Trades je Phase und Tag (Ausbruch und Folge-Scalps zusammen), `MaxOffenePositionen` (1) gleichzeitig, `CooldownMinuten` (2) Pause nach der letzten Eröffnung oder Schließung. Die Trades je Phase werden am **Order-Kommentar** gezählt (`SSA Tokio ORB`, `SSA Tokio Folge`, `SSA London ORB`, `SSA London Folge`; Offene Orders plus Historie des heutigen Tages), damit die Zahl auch nach einem Neustart stimmt. Hand-Trades (`SSA Hand`) zählen nicht mit.
7. **Spread-Automatik** (`MaxSpreadPunkte = 0`): Kosten (Spread + Kommission) müssen kleiner sein als `SpreadAnteilTP` × TP-Distanz des jeweiligen Trades.
8. **Zeitausstieg:** Ab `SchlussZeit` schließt der EA einmal pro Tag alle eigenen Positionen auf diesem Symbol (mit Hinweis und Telegram-Nachricht „Zeitausstieg“), neue Einstiege sind danach blockiert. Leer = aus. Wird die Zeit per `/schluss` auf einen schon vergangenen Zeitpunkt gelegt, wirkt sie erst am nächsten Tag.
9. Schutzfilter (Handelszeit = Tokio- **oder** London-Fenster, Tagesverlust-Limit, Pause nach Verlustserie, Kill-Switch, Telegram-Pause) gelten unverändert in allen Modi.

**Pips:** 1 Pip = 10 Punkte bei 3-/5-stelligen Kursen (USDJPY: 3 Stellen). `AusbruchPufferPips` und die Pip-Anzeigen rechnen darüber.

**Im Chart (links oben):** zusätzlich zu den bekannten Zeilen je eine Zeile für die Tokio- und die London-Range (Hoch, Tief, Breite in Pips und × ATR(H1), `ok`/`x` für gültig), die aktive Phase mit Zustand (z. B. „wartet auf Range“, „Range läuft“, „bereit für Ausbruch“, „Einstiegsfenster vorbei“), eine Zeile „Richtung/Trades“ (Phasen-Richtung, Trades x / max je Phase, Cooldown) und die Auswertung der letzten Kerze (Ausbruch oder Folge-Scalp, Schluss, Volumen, Trend bzw. Range-Mitte). Im Chart stehen bewusst `ok`/`x` statt Häkchen, weil MT4 die Häkchen-Zeichen dort als „?“ zeigt; Telegram nutzt ✓/✗.

**Ehrlicher Hinweis zu den Kosten:** Mehr Trades bedeuten mehr Spread (und Kommission). Bei kleinen Zielen wie hier frisst das schnell einen großen Teil des Gewinns; die Spread-Automatik sperrt zu teure Momente, kann aber nicht verhindern, dass viele kleine Verluste zusammenkommen. Auf einem kleinen Konto stoppt das Tagesverlust-Limit (`TagesVerlustProzent`, Standard 3 %) den EA schon nach wenigen Verlusten bis zum nächsten Serverzeit-Tag. Erst im Strategietester und auf Demo prüfen, ob die Folge-Scalps über Kosten hinweg etwas bringen. Sie lassen sich jederzeit mit `/folge aus` abschalten.

**Inputs von ScalpScout Asia** (Gruppen Betrieb, Ausstieg, Risiko, Schutzfilter und Telegram wie oben; entfallen sind `ImpulsFaktor`, `BreakoutKerzen`, `EMA_Periode`, `SL_ATR`, `TP_ATR`; `ATR_Periode` gilt nur noch für M1-Folge-SL, Break-even, Trailing und die Preisabweichung des Signals):

| Input | Standard | Bedeutung |
|---|---|---|
| `RangeStart` / `RangeEnde` | 03:00 / 04:00 | Tokio-Range (Serverzeit); `RangeStart` ist auch der Beginn der London-Range; Beginn muss vor Ende liegen |
| `ATR_H1_Periode` | 14 | ATR-Periode auf H1 (letzte geschlossene Stunde) |
| `RangeMinATR` / `RangeMaxATR` | 0.8 / 3.0 | Tokio-Range gültig bei Breite von x bis y × ATR(H1) |
| `AusbruchPufferPips` | 1.0 | Schluss muss so viele Pips jenseits der Range-Grenze liegen |
| `VolumenFaktor` / `VolumenKerzen` | 1.3 / 20 | Ausbruchs-Volumen > x × Durchschnitt der letzten N Kerzen |
| `TrendFilterAktiv` / `EMA_H1_Periode` | true / 50 | Long nur über, Short nur unter der EMA(H1) (nur beim Ausbruch) |
| `LondonAktiv` | true | London-Phase ein/aus |
| `LondonStart` / `LondonEnde` | 10:00 / 12:00 | London-Einstiegsfenster; die London-Range endet bei `LondonStart` |
| `LondonRangeMinATR` / `LondonRangeMaxATR` | 1.0 / 5.0 | London-Range gültig bei Breite von x bis y × ATR(H1) |
| `FolgeTradesAktiv` | true | Folge-Scalps nach dem Ausbruch |
| `FolgeAusbruchKerzen` | 5 | Folge-Signal: Schluss über/unter Hoch/Tief der letzten N Kerzen |
| `FolgeVolumenFaktor` | 1.1 | Folge-Signal: Volumen > x × Durchschnitt |
| `FolgeSL_ATR` | 1.0 | Folge-SL = x × ATR(M1) |
| `SL_MaxATR` | 0.75 | Ausbruchs-SL: Range-Mitte, höchstens x × ATR(H1) Abstand |
| `TP_CRV` | 1.5 | TP-Abstand = x × SL-Abstand (beide Trade-Arten) |
| `SchlussZeit` | 13:00 | Zeitausstieg (Serverzeit), leer = aus |
| `HandelStart` / `HandelEnde` | 04:00 / 07:00 | **Tokio**-Einstiegsfenster (steuert zugleich die Schutzfilter-Handelszeit zusammen mit London) |
| `MaxTradesProPhase` | 10 | Trades je Phase und Tag (Ausbruch + Folge) |
| `MaxOffenePositionen` | 1 | gleichzeitig offene Positionen |
| `CooldownMinuten` | 2 | Pause nach letzter Eröffnung/Schließung (0 = aus) |
| `ATR_Periode` | 14 | ATR(M1) für Folge-SL, Break-even, Trailing, Preisabweichung |
| `MagicNumber` | 26101803 | eigene Magic Number |

Standard-`Modus` ist `MANUELLE_FREIGABE`, `TelegramAktiv` ist aus. Bei `MANUELLE_FREIGABE` fragt der EA bei jedem Folge-Signal einzeln nach (Panel oder Telegram JA/NEIN); für aktives Scalpen ist `VOLLAUTOMATIK` nötig, die du nur nach ausführlichen Tests nutzen solltest.

**Telegram-Befehle speziell für Asia** (wie die anderen Einstellungen in GlobalVariables gemerkt, in `/status`, `/hilfe`, der „abweichend“-Liste und `/reset` enthalten):

| Befehl | Wirkung |
|---|---|
| `/range HH:MM-HH:MM` | Tokio-Range (Beginn vor Ende, Ende vor Schlusszeit); der Beginn gilt auch für London |
| `/zeit HH:MM-HH:MM` | **Tokio**-Einstiegsfenster |
| `/london HH:MM-HH:MM` | London-Einstiegsfenster (die London-Range endet bei dessen Beginn) |
| `/london aus` · `/london an` | London-Phase aus/ein |
| `/puffer X` | Ausbruchspuffer in Pips (0–10, eine Nachkommastelle) |
| `/volumen X` | Volumen-Faktor für den Ausbruch (0.8–4.0) |
| `/folge an\|aus` | Folge-Scalps ein/aus |
| `/maxtrades N` | Trades je Phase (1–50) |
| `/cooldown N` | Cooldown in Minuten (0–30) |
| `/schluss HH:MM\|aus` | Zeitausstieg |

`/diag` zeigt je Phase Range (Hoch/Tief/Breite/gültig), Zustand, Phasen-Richtung, Trades x/max, Cooldown und für die letzte Kerze, ob sie als Ausbruch oder Folge-Scalp geprüft wurde und woran es gescheitert ist (plus Zähler seit Start). `/koerper` und `/ausbruch` gibt es hier nicht.

**Einrichtung:**

1. `ScalpScoutAsia.mq4` nach `MQL4/Experts/` kopieren, mit F7 kompilieren (wie bei den anderen EAs).
2. **USDJPY-M1-Chart** öffnen. **Symbolnamen beim Broker prüfen** (z. B. `USDJPY.ecn`); der EA arbeitet mit dem Symbol des Charts. Der M1-Verlauf muss mindestens bis zum Range-Beginn des Tages reichen (Chart nach oben scrollen, damit MT4 Historie lädt).
3. **Eigenen Telegram-Bot** anlegen (@BotFather, `/newbot`) und dessen Token eintragen. **Pro EA ein Bot**, sonst stehlen sich die EAs gegenseitig die Updates (HTTP 409, JA/NEIN-Knöpfe kommen beim falschen EA an). Nachrichten beginnen mit `[Asia]`.
4. Beim ersten Start `MANUELLE_FREIGABE` oder `NUR_SIGNALE` lassen.

**Sommer-/Winterzeit:** Tokio kennt keine Sommerzeit. Verschiebt der Broker-Server Ende Oktober/Anfang November (bzw. im Frühjahr) seine Zeit um eine Stunde, verschieben sich Tokio und London relativ zur Serverzeit. Dann die Zeiten anpassen, ohne die Inputs zu ändern: `/range` (Tokio-Range, Beginn gilt auch für London), `/zeit` (Tokio-Einstieg), `/london` (London-Fenster) und `/schluss`. Wenn die Zeiten später gelegt werden, zuerst `/schluss`, dann `/london`, dann `/range` anpassen, weil jede Änderung die Reihenfolge Range < Einstieg < Schluss prüft.

**Testweg:** (1) Strategietester, Modell „Jeder Tick“, mindestens 3 Monate, mit festem realistischem Spread und passender `KommissionProLot`; Tick-Volumen ist im Tester nur eine Näherung und Telegram ist dort aus. Zusätzlich einmal mit `FolgeTradesAktiv = false` testen, um den Beitrag der Folge-Scalps zu sehen. (2) Danach mindestens eine Woche `NUR_SIGNALE` bzw. Demo (Handelszeiten, Broker-Serverzeit und Range-Linien im Chart kontrollieren). (3) Erst dann live mit Freigabe (`MANUELLE_FREIGABE`), kleinem `MaxLot` und aktivem Tageslimit.

## Risiko-Hinweise

- **CFD- und Forex-Handel mit Hebel kann zum Verlust des gesamten eingesetzten Kapitals führen.** Handle nur mit Geld, dessen Verlust du verkraftest.
- **Der Spread frisst Scalping-Gewinne.** Bei kleinen Zielen ist der Spread ein großer Teil des möglichen Gewinns; dazu kommen Kommission (siehe `KommissionProLot`), Slippage und Requotes. Deshalb sperrt der EA bei zu hohem Spread. Der Backtest ist zu optimistisch, wenn er mit zu niedrigem Spread rechnet.
- **Kontobedingungen des Brokers prüfen:** Manche Broker verbieten oder begrenzen Scalping, Expert Advisors, Mindesthaltedauer von Positionen oder Handel kurz vor/nach News. Das muss vor dem Live-Einsatz mit den AGB geklärt sein.
- **Keine Gewinnzusage.** Vergangene Ergebnisse sagen nichts über künftige aus. Das hier ist ein technisches Werkzeug, keine Anlageberatung.
- Der EA braucht einen laufenden Rechner/VPS, Internet und eingeschaltetes Algo-Trading. Bei Verbindungsabbruch laufen offene Positionen nur mit ihrem SL/TP weiter.
- Der Tagesverlust wird am Equity gemessen und schließt offene Gewinne/Verluste ein. Einzahlungen und Auszahlungen am selben Tag verfälschen die Zahl.

## Annahmen und offene Punkte

- Broker, bei denen SL/TP nicht schon beim Öffnen mitgegeben werden dürfen (manche ECN/STP-Konten, Fehler 130), werden noch nicht unterstützt (Öffnen, danach per OrderModify setzen).
- Slippage ist als Pips-Input mit Faktor 10 bei 3/5 Digits gelöst; bei Indizes und Gold ggf. anpassen.
- Der Spread-Grenzwert gilt auch im Modus `NUR_SIGNALE`; ebenso alle anderen Filter.
- Nach „ALLES SCHLIESSEN“ ist der Handel bis zum EA-Neustart gesperrt.
- Verlustserie: Wird aus der Konto-Historie gelesen; die Historie muss in MT4 (Reiter „Kontohistorie“, Zeitraum „Gesamte Historie“) verfügbar sein.
- Telegram nutzt `WebRequest` und blockiert kurz (bis 5 s Zeitlimit je Anfrage). Abfragen laufen nur im Timer, Sendungen nur bei Ereignissen (Signal, Knopfdruck, Schließung). Nach einem Netzfehler pausiert Telegram 10 Sekunden. Im Strategietester ist Telegram aus.
- Emoji in den Nachrichten sind im Quelltext direkt eingetragen (Datei ist UTF-8 mit BOM). Falls MetaEditor sie nicht korrekt lädt, erscheinen im Telegram nur Platzhalter; die Funktion bleibt davon unberührt.
- Der Code wurde ohne Compiler geschrieben und von Hand geprüft. Bitte einmal in MetaEditor kompilieren und Warnungen/Fehler zurückmelden.

## Fahrplan nächste Schritte

1. In MetaEditor kompilieren (F7), Fehler/Warnungen beheben.
2. Backtest mit „Jeder Tick“ auf EURUSD und XAUUSD, mit realistischem Spread; Parameter nicht überoptimieren.
3. **Demokonto**, Modus `NUR_SIGNALE`, mindestens 2 Wochen: Passen Signale zum Marktgefühl? Wie oft blockiert der Spreadfilter?
4. Demokonto mit `MANUELLE_FREIGABE`, Push aktivieren, Journal auswerten (Trefferquote, CRV, Spread-Kosten).
5. Broker-Bedingungen zu Scalping/EAs schriftlich klären.
6. Live-Start mit `MaxLot` 0.01, niedrigem Risiko und aktivem Tageslimit; erst nach stabilen Ergebnissen langsam steigern.
7. Später: Newsfilter, Handelsfenster je Markt (DAX vs. US30), Teil-Schließung, Statistik-Export.

## Fernsteuerung per Telegram (ab ScalpScout 1.20 / ScalpScout Trend 1.10 / ScalpScout Asia 1.00)

Alle drei EAs lassen sich komplett vom Handy steuern. Befehle nimmt der Bot nur aus der eingetragenen Chat-ID an. Per Telegram geänderte Werte bleiben nach einem Neustart erhalten, bis `/reset` sie löscht (Vollautomatik wird bewusst nie gespeichert).

| Bereich | Befehle |
|---|---|
| Überblick | `/hilfe` · `/status` · `/diag` · `/positionen` · `/heute` · `/bericht` |
| Betrieb | `/modus manuell\|signale\|auto` (auto mit Knopf-Bestätigung) · `/stop` · `/start` · `/schliessen` |
| Einstellungen | `/risiko X` (0.1–25 %) · `/maxlot X` (bis `FernMaxLotObergrenze`) · `/limit X\|aus` · `/zeit HH:MM-HH:MM` · `/be an\|aus` · `/trailing an\|aus` · `/bericht HH:MM\|aus` |
| Nur ScalpScout | `/koerper X` · `/volumen X` · `/ausbruch N` |
| Nur ScalpScout Asia | `/range HH:MM-HH:MM` · `/london HH:MM-HH:MM\|aus\|an` · `/puffer X` · `/volumen X` · `/folge an\|aus` · `/maxtrades N` · `/cooldown N` · `/schluss HH:MM\|aus` (bei Asia steuert `/zeit` das Tokio-Einstiegsfenster) |
| Nur ScalpScout Trend | `/crv X` · `/news HH:MM-HH:MM,…\|aus` · `/vwap an\|aus` · `/lunte an\|aus` · `/m5 an\|aus` |
| Einzelne Position | `/zu TICKET` (mit Bestätigung) · `/sl TICKET PREIS\|be` · `/tp TICKET PREIS` |
| Hand-Trades | `/kauf [LOT]` · `/verkauf [LOT]` (Vorschau + Bestätigung, Zeitfenster/News werden ignoriert) |
| Zurücksetzen | `/reset` |

Hinweise: Läuft ein EA auf mehreren Charts, Telegram nur auf einem Chart aktivieren – die Befehle wirken nur dort. Jeder EA braucht einen eigenen Telegram-Bot. Der Tagesbericht kommt einmal pro Serverzeit-Tag (Input `TagesberichtZeit`, Default 23:05).
