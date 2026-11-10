//+------------------------------------------------------------------+
//|                                              ScalpScoutTrend.mq4 |
//|  Zweiter EA: Trend-Pullback mit Anchored VWAP (AVWAP) auf M1.    |
//|  Zeigt Signale zur manuellen Freigabe oder handelt automatisch.  |
//|  Keine Gewinnzusage - Handel auf eigenes Risiko.                 |
//+------------------------------------------------------------------+
#property copyright   "maehrsteuern"
#property version     "1.10"
#property description "ScalpScout Trend - M1-Scalping-Assistent: Trend-Pullback (AVWAP), manuelle Freigabe, Vollautomatik, Telegram-Fernsteuerung"
#property strict

//--- Betriebsart (muss vor den Inputs definiert sein)
enum ENUM_MODUS
{
   MANUELLE_FREIGABE = 0,  // Manuelle Freigabe (Knopf im Chart)
   VOLLAUTOMATIK     = 1,  // Vollautomatik (handelt selbst)
   NUR_SIGNALE       = 2   // Nur Signale (Alert/Push, kein Trade)
};

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
//--- Betrieb
input ENUM_MODUS Modus             = MANUELLE_FREIGABE; // Betriebsart
input bool   PushAktiv             = false;   // Push-Nachricht an MT4-Mobile senden
input int    SignalGueltigSek      = 45;      // Signal gültig für (Sekunden)
input double PreisAbweichungATR    = 0.3;     // Signal verfällt, wenn Preis weiter weg ist als x * ATR
input int    Slippage              = 3;       // Max. Abweichung in Pips (bei 3/5-stelligen Kursen automatisch x10 Punkte)
input int    OrderVersuche         = 3;       // Max. Versuche bei Requote/Preisänderung

//--- Strategie Trend-Pullback (AVWAP)
input int    ATR_Periode           = 14;      // ATR-Periode (M1)
input int    SwingStaerke          = 3;       // Swing-Hoch/Tief: Kerzen links und rechts
input int    SwingLookback         = 300;     // Swing-Suche über die letzten N Kerzen
input bool   TrendNurTiefs         = true;    // Trend nur über Swing-Tiefs (false: zusätzlich Hochs)
input bool   TrendM5Filter         = true;    // M5-Filter: Long nur über, Short nur unter der M5-EMA
input int    M5_EMA_Periode        = 50;      // EMA-Periode auf M5
input bool   VWAP_Pflicht          = true;    // Rücksetzer muss den Anchored VWAP berührt haben
input double VWAP_NaeheATR         = 0.3;     // "Berührt" = bis x * ATR an den AVWAP heran
input bool   DoppelLunteAktiv      = true;    // Doppellunte als zweiten Signaltyp zulassen
input double DoppelLunteToleranzATR= 0.15;    // Doppellunte: Tiefs/Hochs höchstens x * ATR auseinander
input double SL_PufferATR          = 0.1;     // Puffer hinter der Formation (x * ATR)
input double TP_PufferATR          = 0.05;    // Puffer vor dem Ziel (x * ATR)
input double MinCRV                = 2.0;     // Mindest-CRV nach Kosten
input bool   BruchSperreAktiv      = true;    // Sperre nach gebrochenem Swing-Hoch/Tief
input string NewsPausen            = "";      // News-Pausen Serverzeit "HH:MM-HH:MM,..." (z. B. 15:25-15:45)

//--- Ausstieg
input bool   BE_Aktiv              = true;    // Break-even aktivieren
input double BE_ATR                = 0.8;     // Break-even ab Gewinn von x * ATR
input int    BE_PufferPunkte       = 0;       // Break-even: Puffer über/unter Einstieg (Punkte)
input bool   TrailingAktiv         = false;   // Trailing-Stop aktivieren
input double TrailingStartATR      = 1.0;     // Trailing startet ab Gewinn von x * ATR
input double TrailingATR           = 0.7;     // Trailing-Abstand = x * ATR
input double TrailingSchrittATR    = 0.1;     // SL nur nachziehen, wenn Verbesserung mind. x * ATR

//--- Risiko
input double RisikoProzent         = 1.0;     // Risiko pro Trade in % vom Equity
input double MaxLot                = 0.01;    // Harter Lot-Deckel (Live-Start)
input double FernMaxLotObergrenze  = 0.05;    // Telegram /maxlot: höchster erlaubter Wert (Sicherheitsgrenze)

//--- Schutzfilter
input double MaxSpreadPunkte       = 0;       // Max. Kosten (Spread + Kommission) in Punkten (0 = unbegrenzt, MinCRV schützt)
input double KommissionProLot      = 0.0;     // Kommission pro Lot, Hin- und Rückweg zusammen, in Kontowährung (ECN)
input string HandelStart           = "08:00"; // Handelsfenster Beginn (Serverzeit, HH:MM)
input string HandelEnde            = "20:00"; // Handelsfenster Ende (Serverzeit, HH:MM)
input double TagesVerlustProzent   = 3.0;     // Tagesverlust-Limit in % vom Tagesbeginn-Equity (0 = aus)
input int    MaxOffenePositionen   = 1;       // Max. offene Positionen pro Symbol
input int    PauseNachVerlusten    = 3;       // Pause nach N Verlusten in Folge (0 = aus)
input int    PauseMinuten          = 30;      // Dauer der Pause (Minuten)
input int    MagicNumber           = 26101802;// Magic Number dieses EAs (anders als ScalpScout)

//--- Telegram-Fernbedienung (Freigabe per Handy)
input bool   TelegramAktiv         = false;   // Telegram-Fernbedienung einschalten
input string TelegramToken         = "";      // Bot-Token von @BotFather (nie weitergeben)
input string TelegramChatID        = "";      // deine Chat-ID (nur dieser Chat darf steuern)
input int    TelegramAbfrageSek    = 2;       // Abfrageintervall (Sekunden)
input bool   TelegramMeldeSchliessung = true; // Nachricht bei geschlossener Position mit Ergebnis
input string TagesberichtZeit      = "23:05"; // Tagesbericht per Telegram, Serverzeit HH:MM (leer = aus)

//+------------------------------------------------------------------+
//| Konstanten und Typen                                             |
//+------------------------------------------------------------------+
#define PRAEFIX          "SST_"
#define OBJ_KILL         "SST_btn_kill"
#define OBJ_PNL_PRAEFIX  "SST_pnl_"
#define OBJ_PNL_BG       "SST_pnl_bg"
#define OBJ_PNL_OK       "SST_pnl_btn_ok"
#define OBJ_PNL_NO       "SST_pnl_btn_no"
#define OBJ_INFO_BG      "SST_info_bg"
#define ORDER_KOMMENTAR  "ScalpScoutTrend"
#define INFO_ZEILEN      12
#define INFO_BREITE      540
#define INFO_MAXZEICHEN  88
#define PNL_ZEILEN       8
#define PNL_HOEHE        208
#define FERN_MAXPAUSEN   10    // höchstens so viele News-Pausen per /news
#define CFG_GUELTIG_SEK  60    // Gültigkeit einer Rückfrage mit Knöpfen (Sekunden)
#define HIST_MAX         16    // Plätze je Gründe-Zähler (/diag)
#define HAND_GUELTIG_SEK 30    // Gültigkeit der Rückfrage bei /kauf und /verkauf (Sekunden)

// Eigene Fehlercodes (unabhängig von Include-Dateien)
#define FEHLER_KEIN_FEHLER      0
#define FEHLER_PREIS_GEAENDERT  135
#define FEHLER_KEINE_KURSE      136
#define FEHLER_BROKER_BESCHAEFT 137
#define FEHLER_REQUOTE          138
#define FEHLER_KONTEXT_BELEGT   146
#define FEHLER_UNGUELTIGE_STOPS 130
#define FEHLER_NICHT_GENUG_GELD 134

struct Plan
{
   int    richtung;   // +1 Long, -1 Short
   double preis;      // Einstiegspreis (Ask/Bid)
   double sl;         // Stop-Loss (Kurs)
   double tp;         // Take-Profit (Kurs)
   double slDist;     // SL-Abstand (Preis)
   double tpDist;     // TP-Abstand (Preis)
   double lot;        // Lotgröße
   double spreadPkt;  // Spread in Punkten
   double kommPkt;    // Kommission in Punkten (0 = keine)
   double crv;        // Chance-Risiko-Verhältnis nach Kosten
   double atr;        // verwendeter ATR-Wert
   int    typ;        // Signaltyp: 1 = Farbwechsel, 2 = Doppellunte
};

struct SignalZustand
{
   bool     aktiv;    // wartet auf Freigabe
   datetime zeit;     // Erzeugungszeit (TimeLocal)
   Plan     plan;     // berechneter Plan
};

//+------------------------------------------------------------------+
//| Globale Variablen                                                |
//+------------------------------------------------------------------+
ENUM_MODUS    g_modus;               // wirksame Betriebsart
SignalZustand g_sig;                 // aktuelles Signal (Freigabe-Modus)
datetime      g_letzteKerze   = 0;   // Zeit der zuletzt ausgewerteten M1-Kerze
datetime      g_tag           = 0;   // Beginn des aktuellen Serverzeit-Tages
double        g_tagEquity     = 0.0; // Equity zu Tagesbeginn
bool          g_tagesLimit    = false; // Tagesverlust-Limit heute erreicht
bool          g_gestoppt      = false; // Kill-Switch wurde ausgelöst
int           g_startMin      = 0;   // Handelsfenster Beginn (Minuten ab 00:00)
int           g_endeMin       = 0;   // Handelsfenster Ende (Minuten ab 00:00)
int           g_histAnzahl    = -1;  // Cache: Anzahl Historieneinträge
int           g_verlustSerie  = 0;   // Verluste in Folge
datetime      g_letzterVerlust= 0;   // Schlusszeit des letzten Verlusts
string        g_hinweis       = "";  // letzter Hinweis (z. B. Lot zu klein)
datetime      g_hinweisZeit   = 0;
bool          g_ui            = true; // Oberfläche aktiv?
uint          g_uiLetzte      = 0;   // Zeitstempel letztes UI-Update
string        g_gvTag, g_gvEquity;   // Namen der globalen Variablen (Tagesstart)
int           g_orderTicket   = 0;   // Ticket der zuletzt eröffneten Order
double        g_orderPreis    = 0.0; // Einstiegspreis der zuletzt eröffneten Order

// Strategie Trend-Pullback (nur einmal pro neuer Kerze neu berechnet)
int           g_trend         = 0;   // +1 aufwärts, -1 abwärts, 0 seitwärts
double        g_avwap         = 0.0; // Anchored VWAP bis Shift 1 (0 = nicht verfügbar)
double        g_ziel          = 0.0; // nächstes Swing-Ziel in Trendrichtung (ohne Puffer)
int           g_ankerShift    = -1;  // Shift der Ankerkerze
int           g_anzKerzen     = 0;   // Anzahl ausgewerteter Kerzen (Shift 0..g_anzKerzen-1)
string        g_stratGrund    = "wartet auf die erste Kerze"; // Ergebnis der letzten Prüfung
double        g_swHP[];              // Swing-Hoch-Preise (neueste zuerst)
int           g_swHB[];              // Swing-Hoch-Shifts
int           g_swHN          = 0;
double        g_swLP[];              // Swing-Tief-Preise (neueste zuerst)
int           g_swLB[];              // Swing-Tief-Shifts
int           g_swLN          = 0;
double        g_avwapReihe[];        // AVWAP je Shift (gültig für Shift 1..g_ankerShift)
int           g_newsVon[];           // News-Pausen: Beginn (Minuten ab 00:00)
int           g_newsBis[];           // News-Pausen: Ende
int           g_newsAnz       = 0;

// Laufzeit-Einstellungen: Start = Inputs, danach ggf. gespeicherte Fern-Werte (per Telegram änderbar)
double        g_risiko        = 1.0;   // Risiko pro Trade in % vom Equity
double        g_maxLot        = 0.01;  // harter Lot-Deckel
double        g_limitProz     = 3.0;   // Tagesverlust-Limit in % (0 = aus)
double        g_minCRV        = 2.0;   // Mindest-CRV nach Kosten
bool          g_vwapPflicht   = true;  // Rücksetzer muss den AVWAP berührt haben
bool          g_doppelLunte   = true;  // Doppellunte als zweiten Signaltyp zulassen
bool          g_m5Filter      = true;  // M5-Filter
string        g_newsEingabe   = "";    // News-Pausen aus dem Input (normalisiert, zum Vergleichen)
bool          g_stopTg        = false; // Kill-Switch wurde per Telegram ausgelöst (/start hebt ihn auf)
bool          g_beAktiv       = true;  // Break-even aktiv
bool          g_trailAktiv    = false; // Trailing-Stop aktiv
int           g_berichtMin    = -1;    // Tagesbericht: Minuten ab 00:00 (Serverzeit), -1 = aus
datetime      g_berichtTag    = 0;     // Serverzeit-Tag, für den der Bericht schon gesendet wurde
datetime      g_cfgZeit[4];            // offene Rückfragen mit Knöpfen: [0] Vollautomatik, [1] Alle schließen, [2] einzelne Position, [3] Hand-Trade
long          g_cfgMsg[4];             // message_id der Rückfrage
string        g_cfgText[4];            // Text der Rückfrage (für die spätere Änderung)
int           g_cfgTicket[4];          // Ticket (Rückfrage [2])
int           g_cfgDir[4];             // Richtung (Rückfrage [3]): +1 Kauf, -1 Verkauf
double        g_cfgLot[4];             // gewünschtes Lot (Rückfrage [3]), 0 = aus Risiko

// Diagnose der letzten ausgewerteten M1-Kerze (/diag); -1 = nicht geprüft
datetime      g_dgZeit        = 0;     // Zeit der ausgewerteten Kerze (Shift 1)
double        g_dgAtr         = 0.0;
int           g_dgRichtung    = 0;     // Trend: +1/-1/0
double        g_dgTief[2];             // letzte zwei Swing-Tiefs (neuestes zuerst)
int           g_dgTiefN       = 0;
double        g_dgHoch[2];             // letzte zwei Swing-Hochs (neuestes zuerst)
int           g_dgHochN       = 0;
int           g_dgM5          = -1;    // M5-Filter: 1 ok, 0 nicht ok, 2 aus
double        g_dgM5Close     = 0.0;
double        g_dgM5Ema       = 0.0;
double        g_dgAvwap       = 0.0;
int           g_dgBerueh      = -1;    // AVWAP berührt: 1/0
int           g_dgFarb        = -1;    // Muster Farbwechsel: 1/0
int           g_dgLunte       = -1;    // Muster Doppellunte: 1/0, 2 = aus
int           g_dgBruch       = -1;    // Bruch-Sperre: 1 aktiv, 0 nicht aktiv, 2 abgeschaltet
double        g_dgZiel        = 0.0;
double        g_dgSL          = 0.0;
double        g_dgTP          = 0.0;
double        g_dgCRV         = 0.0;
bool          g_dgCrvGeprueft = false;
string        g_dgFilter      = "-";   // Ergebnis der Schutzfilter
string        g_dgEnde        = "";    // Endergebnis der Prüfung
int           g_dgKerzen      = 0;     // Zähler seit Start
int           g_dgSignale     = 0;
int           g_dgTrades      = 0;
string        g_vwKey[HIST_MAX];       // verworfene Signale: Gründe (Schlüssel, Text, Anzahl)
string        g_vwText[HIST_MAX];
int           g_vwAnz[HIST_MAX];
int           g_vwN           = 0;
int           g_vwGes         = 0;
string        g_ksKey[HIST_MAX];       // Kerzen ohne Signal: Gründe
string        g_ksText[HIST_MAX];
int           g_ksAnz[HIST_MAX];
int           g_ksN           = 0;
int           g_ksGes         = 0;

// Telegram
bool          g_tgAktiv       = false; // Telegram wirksam (Eingaben ok, kein Tester)
bool          g_tgGesperrt    = false; // WebRequest-URL nicht freigegeben (Fehler 4060)
bool          g_tgVerbunden   = false; // letzte Anfrage war erfolgreich
int           g_tgFehler      = 0;     // letzter Fehlercode (MT4-Fehler oder HTTP-Status)
bool          g_tgPause       = false; // per /stop pausiert
string        g_tgToken       = "";    // bereinigter Token
string        g_tgChat        = "";    // bereinigte Chat-ID
long          g_tgOffset      = 0;     // nächstes erwartetes update_id
datetime      g_tgLetzteAbfrage = 0;   // Zeitpunkt der letzten Abfrage (TimeLocal)
datetime      g_tgSperreBis   = 0;     // nach Netzfehler bis dahin keine Anfragen (TimeLocal)
int           g_sigId         = 0;     // ID des aktuellen Freigabe-Signals
long          g_sigMsgId      = 0;     // Telegram-message_id des aktuellen Signals (0 = keine)
string        g_tgKopf        = "";    // Kopfzeile der Signal-Nachricht (für spätere Änderungen)
int           g_tgOffen[];             // gemerkte offene eigene Tickets
int           g_tgVersuche[];          // Anzahl Suchversuche je Ticket (Historie)

//+------------------------------------------------------------------+
//| Hilfsfunktionen: Fehler, Zahlen, Zeit                            |
//+------------------------------------------------------------------+
string FehlerText(int err)
{
   switch(err)
   {
      case 0:   return "kein Fehler";
      case 2:   return "allgemeiner Fehler";
      case 3:   return "ungültige Parameter";
      case 4:   return "Handelsserver beschäftigt";
      case 6:   return "keine Verbindung zum Server";
      case 8:   return "zu häufige Anfragen";
      case 64:  return "Konto gesperrt";
      case 65:  return "ungültige Kontonummer";
      case 128: return "Handels-Timeout";
      case 129: return "ungültiger Preis";
      case 130: return "ungültige Stops (SL/TP zu nah oder falsch)";
      case 131: return "ungültiges Volumen";
      case 132: return "Markt geschlossen";
      case 133: return "Handel nicht erlaubt";
      case 134: return "nicht genug Geld/Margin";
      case 135: return "Preis hat sich geändert";
      case 136: return "keine Kurse";
      case 137: return "Broker beschäftigt";
      case 138: return "Requote";
      case 139: return "Order gesperrt";
      case 141: return "zu viele Anfragen";
      case 145: return "Änderung nicht erlaubt (zu nah am Markt)";
      case 146: return "Handelskontext beschäftigt";
      case 148: return "zu viele offene Orders";
      case 4060: return "Funktion nicht erlaubt (WebRequest-URL in den Optionen freigeben)";
      case 4108: return "ungültige Ticketnummer";
      case 4109: return "Handel im Terminal nicht erlaubt (AutoTrading/Algo-Trading aus)";
      case 4110: return "Kaufen nicht erlaubt";
      case 4111: return "Verkaufen nicht erlaubt";
   }
   return "unbekannter Fehler";
}

// Fehlercode ins Journal schreiben
void LogFehler(string kontext, int err)
{
   Print("ScalpScout Trend FEHLER bei ", kontext, ": Code ", err, " (", FehlerText(err), ")");
}

// Minuten seit 00:00 aus "HH:MM"; -1 bei ungültiger Eingabe
int ParseHHMM(string s)
{
   if(StringLen(s) == 4 && StringGetCharacter(s, 1) == ':')
      s = "0" + s;                        // "8:00" -> "08:00"
   if(StringLen(s) != 5 || StringGetCharacter(s, 2) != ':')
      return -1;
   int h = (int)StringToInteger(StringSubstr(s, 0, 2));
   int m = (int)StringToInteger(StringSubstr(s, 3, 2));
   if(h < 0 || h > 23 || m < 0 || m > 59)
      return -1;
   return h * 60 + m;
}

// Anzahl Nachkommastellen der Lot-Schrittweite
int LotStellen(double step)
{
   int d = 0;
   while(d < 8 && MathAbs(step * MathPow(10, d) - MathRound(step * MathPow(10, d))) > 1e-9)
      d++;
   return d;
}

// Lot auf Schrittweite abrunden
double LotAbrunden(double lot)
{
   double step = MarketInfo(Symbol(), MODE_LOTSTEP);
   if(step <= 0.0)
      step = 0.01;
   double l = MathFloor(lot / step + 1e-8) * step;
   return NormalizeDouble(l, LotStellen(step));
}

// Slippage in Punkten (bei 3-/5-stelligen Kursen Pips x 10)
int SlippagePunkte()
{
   int faktor = (Digits == 3 || Digits == 5) ? 10 : 1;
   return Slippage * faktor;
}

// Aktueller ATR (geschlossene M1-Kerze)
double AktuelleATR()
{
   return iATR(Symbol(), PERIOD_M1, ATR_Periode, 1);
}

// Maximal erlaubte Kosten (Spread + Kommission) in Punkten; 0 = unbegrenzt (dann entscheidet MinCRV)
double MaxSpreadAktuell(double atr)
{
   return MathMax(0.0, MaxSpreadPunkte);
}

string MaxKostenText(double maxSp)
{
   return (maxSp > 0.0) ? DoubleToString(maxSp, 1) + " Pkt" : "unbegrenzt (MinCRV)";
}

double SpreadPunkte()
{
   return (Ask - Bid) / Point;
}

// Kommission (Hin- und Rückweg) in Punkten; 0 bei keiner Kommission oder ungültigen Symboldaten
double KommissionPunkte()
{
   if(KommissionProLot <= 0.0)
      return 0.0;
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   if(tickSize <= 0.0 || tickValue <= 0.0 || Point <= 0.0)
      return 0.0;
   double geldProPunkt = tickValue / tickSize * Point;   // Geld pro Punkt und Lot
   if(geldProPunkt <= 0.0)
      return 0.0;
   return KommissionProLot / geldProPunkt;
}

// Text "Spread a" bzw. "Spread a + Komm. b" (Kommission nur wenn > 0)
string KostenText(double sp, double ko)
{
   return "Spread " + DoubleToString(sp, 1) + ((ko > 0.0) ? " + Komm. " + DoubleToString(ko, 1) : "");
}

// Text für Info-Zeilen kürzen
string Kuerzen(string s, int maxLen)
{
   if(StringLen(s) <= maxLen)
      return s;
   return StringSubstr(s, 0, maxLen - 3) + "...";
}

void HinweisSetzen(string text)
{
   g_hinweis     = text;
   g_hinweisZeit = TimeCurrent();
   Print("ScalpScout Trend Hinweis: ", text);
}

//+------------------------------------------------------------------+
//| Tages- und Verlustverwaltung                                     |
//+------------------------------------------------------------------+
void TagSpeichern()
{
   if(IsTesting())
      return;
   GlobalVariableSet(g_gvTag, (double)g_tag);
   GlobalVariableSet(g_gvEquity, g_tagEquity);
}

// Neuen Serverzeit-Tag erkennen und Tagesstart-Equity setzen
void TagPruefen()
{
   datetime heute = (datetime)((long)TimeCurrent() / 86400 * 86400);
   if(heute != g_tag)
   {
      g_tag        = heute;
      g_tagEquity  = AccountEquity();
      g_tagesLimit = false;
      TagSpeichern();
      Print("ScalpScout Trend: neuer Handelstag, Start-Equity ", DoubleToString(g_tagEquity, 2));
   }
   // Tageslimit einrasten (gilt bis zum nächsten Tag)
   if(!g_tagesLimit && g_limitProz > 0.0 && g_tagEquity > 0.0)
   {
      double verlustProz = (g_tagEquity - AccountEquity()) / g_tagEquity * 100.0;
      if(verlustProz >= g_limitProz)
      {
         g_tagesLimit = true;
         Print("ScalpScout Trend: Tagesverlust-Limit erreicht (", DoubleToString(verlustProz, 2),
               " %). Keine neuen Trades bis zum nächsten Tag.");
      }
   }
}

// Verluste in Folge aus der Kontohistorie ermitteln (nur bei neuer Historie)
void VerlustSerieAktualisieren()
{
   int n = OrdersHistoryTotal();
   if(n == g_histAnzahl)
      return;
   g_histAnzahl     = n;
   g_verlustSerie   = 0;
   g_letzterVerlust = 0;
   if(PauseNachVerlusten <= 0)
      return;

   datetime vorher = TimeCurrent() + 86400;
   for(int k = 0; k < PauseNachVerlusten; k++)
   {
      datetime bestZeit   = 0;
      double   bestProfit = 0.0;
      bool     gefunden   = false;
      for(int i = 0; i < n; i++)
      {
         if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
            continue;
         if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol())
            continue;
         if(OrderType() > OP_SELL)
            continue;
         datetime ct = OrderCloseTime();
         if(ct > 0 && ct < vorher && ct > bestZeit)
         {
            bestZeit   = ct;
            bestProfit = OrderProfit() + OrderSwap() + OrderCommission();
            gefunden   = true;
         }
      }
      if(!gefunden)
         break;
      if(bestProfit < 0.0)
      {
         g_verlustSerie++;
         if(g_verlustSerie == 1)
            g_letzterVerlust = bestZeit;
      }
      else
         break;
      vorher = bestZeit;
   }
}

int ZaehlePositionen()
{
   int z = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber && OrderType() <= OP_SELL)
         z++;
   }
   return z;
}

bool ZeitfensterOK()
{
   if(g_startMin == g_endeMin)
      return true;
   datetime t = TimeCurrent();
   int jetzt = TimeHour(t) * 60 + TimeMinute(t);
   if(g_startMin < g_endeMin)
      return (jetzt >= g_startMin && jetzt < g_endeMin);
   return (jetzt >= g_startMin || jetzt < g_endeMin);   // Fenster über Mitternacht
}

// NewsPausen "HH:MM-HH:MM,HH:MM-HH:MM" einlesen; false bei Formatfehler
bool NewsParsen(string s)
{
   g_newsAnz = 0;
   ArrayResize(g_newsVon, 0);
   ArrayResize(g_newsBis, 0);
   StringTrimLeft(s);
   StringTrimRight(s);
   if(s == "")
      return true;
   string teile[];
   int n = StringSplit(s, ',', teile);
   for(int i = 0; i < n; i++)
   {
      string z = teile[i];
      StringTrimLeft(z);
      StringTrimRight(z);
      if(z == "")
         continue;
      int p = StringFind(z, "-");
      if(p < 0)
         return false;
      string a = StringSubstr(z, 0, p);
      string b = StringSubstr(z, p + 1);
      StringTrimLeft(a);
      StringTrimRight(a);
      StringTrimLeft(b);
      StringTrimRight(b);
      int von = ParseHHMM(a);
      int bis = ParseHHMM(b);
      if(von < 0 || bis < 0)
         return false;
      if(von == bis)
         continue;
      ArrayResize(g_newsVon, g_newsAnz + 1);
      ArrayResize(g_newsBis, g_newsAnz + 1);
      g_newsVon[g_newsAnz] = von;
      g_newsBis[g_newsAnz] = bis;
      g_newsAnz++;
   }
   return true;
}

// true, wenn die Serverzeit in einer News-Pause liegt; 'fenster' = Text des Fensters
bool NewsPauseAktiv(string &fenster)
{
   fenster = "";
   if(g_newsAnz <= 0)
      return false;
   datetime zt = TimeCurrent();
   int jetzt = TimeHour(zt) * 60 + TimeMinute(zt);
   for(int i = 0; i < g_newsAnz; i++)
   {
      bool drin = (g_newsVon[i] < g_newsBis[i]) ? (jetzt >= g_newsVon[i] && jetzt < g_newsBis[i])
                                                : (jetzt >= g_newsVon[i] || jetzt < g_newsBis[i]);
      if(drin)
      {
         fenster = StringFormat("%02d:%02d-%02d:%02d", g_newsVon[i] / 60, g_newsVon[i] % 60,
                                g_newsBis[i] / 60, g_newsBis[i] % 60);
         return true;
      }
   }
   return false;
}

// Prüft alle Schutzfilter. true = Handel erlaubt, sonst Grund in 'grund'
bool HandelErlaubt(string &grund, double atr, bool zeitUndNews = true)
{
   grund = "";
   VerlustSerieAktualisieren();

   if(g_gestoppt)
   {
      grund = g_stopTg ? "Gestoppt (Kill-Switch per Telegram) - /start hebt auf" : "Gestoppt (Kill-Switch) - EA neu starten";
      return false;
   }
   if(g_tgPause)
   {
      grund = "Pausiert per Telegram (/start hebt auf)";
      return false;
   }
   if(g_modus != NUR_SIGNALE && !IsTesting() && (!IsTradeAllowed() || !IsExpertEnabled()))
   {
      grund = "Algo-Trading/AutoTrading ist aus";
      return false;
   }
   if(zeitUndNews && !ZeitfensterOK())
   {
      grund = "Außerhalb Handelszeit (" + FensterText() + ")";
      return false;
   }
   string newsFenster = "";
   if(zeitUndNews && NewsPauseAktiv(newsFenster))
   {
      grund = "News-Pause (" + newsFenster + ")";
      return false;
   }
   if(g_tagesLimit)
   {
      grund = "Tagesverlust-Limit erreicht";
      return false;
   }
   if(PauseNachVerlusten > 0 && g_verlustSerie >= PauseNachVerlusten && g_letzterVerlust > 0)
   {
      datetime ende = g_letzterVerlust + PauseMinuten * 60;
      if(TimeCurrent() < ende)
      {
         grund = "Pause nach " + IntegerToString(g_verlustSerie) + " Verlusten (noch "
                 + IntegerToString((int)((ende - TimeCurrent()) / 60) + 1) + " min)";
         return false;
      }
   }
   if(ZaehlePositionen() >= MaxOffenePositionen)
   {
      grund = "Max. offene Positionen erreicht";
      return false;
   }
   double maxSp  = MaxSpreadAktuell(atr);
   double sp     = SpreadPunkte();
   double ko     = KommissionPunkte();
   double kosten = sp + ko;
   if(MaxSpreadPunkte > 0.0 && kosten > maxSp)
   {
      grund = "Kosten zu hoch (" + KostenText(sp, ko) + " > " + DoubleToString(maxSp, 1) + " Pkt)";
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Fern-Einstellungen: Laufzeit-Werte, Speicherung, Diagnose        |
//+------------------------------------------------------------------+
// Alle per Telegram änderbaren Werte stehen in g_*-Variablen. Beim Start gelten die Inputs; danach werden
// (nur live) gespeicherte Fern-Werte geladen: globale Variablen "SST_<konto>_<magic>_<name>",
// News-Pausen in der Datei MQL4/Files/SST_<konto>_<magic>_news.txt. Fehlt ein Wert, gilt der Input.

// Zahl ohne überflüssige Nullen, aber mit mindestens einer Nachkommastelle ("2.00" -> "2.0")
string Zahl(double v, int stellen)
{
   string s = DoubleToString(v, stellen);
   if(StringFind(s, ".") < 0)
      return s;
   while(StringLen(s) > 2 && StringGetCharacter(s, StringLen(s) - 1) == '0' && StringGetCharacter(s, StringLen(s) - 2) != '.')
      s = StringSubstr(s, 0, StringLen(s) - 1);
   return s;
}

string ZeitText(int minuten)
{
   return StringFormat("%02d:%02d", minuten / 60, minuten % 60);
}

string FensterText()
{
   if(g_startMin == g_endeMin)
      return "ganztägig";
   return ZeitText(g_startMin) + "-" + ZeitText(g_endeMin);
}

string LimitText()
{
   return (g_limitProz > 0.0) ? Zahl(g_limitProz, 1) + " %" : "aus";
}

string AnAusText(bool b)
{
   return b ? "an" : "aus";
}

string LotText(double lot)
{
   return DoubleToString(lot, LotStellen(MarketInfo(Symbol(), MODE_LOTSTEP)));
}

// Aktive News-Pausen als "HH:MM-HH:MM,HH:MM-HH:MM" (leer = keine)
string NewsText()
{
   string s = "";
   for(int i = 0; i < g_newsAnz; i++)
      s += ((i > 0) ? "," : "") + ZeitText(g_newsVon[i]) + "-" + ZeitText(g_newsBis[i]);
   return s;
}

// Zahl mit Komma oder Punkt als Dezimaltrenner (optional mit % am Ende); false bei Unsinn
bool ZahlParsen(string s, double &wert)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   StringReplace(s, ",", ".");
   int n = StringLen(s);
   if(n > 0 && StringGetCharacter(s, n - 1) == 37)       // 37 = '%'
   {
      s = StringSubstr(s, 0, n - 1);
      StringTrimRight(s);
      n = StringLen(s);
   }
   if(n == 0 || n > 12)
      return false;
   int punkte  = 0;
   int ziffern = 0;
   for(int i = 0; i < n; i++)
   {
      int c = (int)StringGetCharacter(s, i);
      if(c == 46)
         punkte++;
      else if(c >= 48 && c <= 57)
         ziffern++;
      else
         return false;
   }
   if(punkte > 1 || ziffern == 0)
      return false;
   wert = StringToDouble(s);
   return true;
}

//--- Speicherung ----------------------------------------------------
string FernGv(string schluessel)
{
   return "SST_" + IntegerToString(AccountNumber()) + "_" + IntegerToString(MagicNumber) + "_" + schluessel;
}

string FernNewsDatei()
{
   return FernGv("news") + ".txt";
}

void FernSetzen(string schluessel, double wert)
{
   if(IsTesting())
      return;
   GlobalVariableSet(FernGv(schluessel), wert);
}

void FernGvLoeschen(string schluessel)
{
   string n = FernGv(schluessel);
   if(GlobalVariableCheck(n))
      GlobalVariableDel(n);
}

void FernNewsSpeichern(string s)
{
   if(IsTesting())
      return;
   int h = FileOpen(FernNewsDatei(), FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      LogFehler("FileOpen " + FernNewsDatei(), GetLastError());
      return;
   }
   FileWriteString(h, s);
   FileClose(h);
}

// Gespeicherte News-Pausen lesen; vorhanden = Datei existiert (auch leer = "keine Pausen")
string FernNewsLesen(bool &vorhanden)
{
   vorhanden = false;
   string name = FernNewsDatei();
   if(!FileIsExist(name))
      return "";
   int h = FileOpen(name, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      LogFehler("FileOpen " + name, GetLastError());
      return "";
   }
   string s = "";
   if(!FileIsEnding(h))
      s = FileReadString(h);
   FileClose(h);
   vorhanden = true;
   return s;
}

// Tagesbericht-Zeit aus dem Input in Minuten (-1 = aus)
int BerichtEingabeMin()
{
   string s = TagesberichtZeit;
   StringTrimLeft(s);
   StringTrimRight(s);
   if(s == "")
      return -1;
   return ParseHHMM(s);
}

string BerichtZeitText()
{
   return (g_berichtMin >= 0) ? ZeitText(g_berichtMin) : "aus";
}

// Nach Start, /bericht und /reset: heute nicht mehr nachträglich senden, wenn die Zeit schon vorbei ist
void BerichtNeuAnsetzen()
{
   datetime zt    = TimeCurrent();
   datetime heute = (datetime)((long)zt / 86400 * 86400);
   int      jetzt = TimeHour(zt) * 60 + TimeMinute(zt);
   g_berichtTag = (g_berichtMin >= 0 && jetzt >= g_berichtMin) ? heute : 0;
}

// Alle Laufzeit-Werte aus den Inputs setzen (Start und /reset)
void FernEingabenSetzen()
{
   g_beAktiv     = BE_Aktiv;
   g_trailAktiv  = TrailingAktiv;
   g_berichtMin  = BerichtEingabeMin();
   g_risiko      = RisikoProzent;
   g_maxLot      = MaxLot;
   g_limitProz   = TagesVerlustProzent;
   g_minCRV      = MinCRV;
   g_vwapPflicht = VWAP_Pflicht;
   g_doppelLunte = DoppelLunteAktiv;
   g_m5Filter    = TrendM5Filter;
   g_startMin    = ParseHHMM(HandelStart);
   g_endeMin     = ParseHHMM(HandelEnde);
   NewsParsen(NewsPausen);
   g_newsEingabe = NewsText();

   g_modus = Modus;
   if(IsTesting() && Modus == MANUELLE_FREIGABE)
   {
      g_modus = VOLLAUTOMATIK;
      Print("ScalpScout Trend: Strategietester erkannt - Modus MANUELLE_FREIGABE wird wie VOLLAUTOMATIK behandelt.");
   }
}

// Gespeicherte Fern-Werte laden (nur live); ungültige oder fehlende Werte werden ignoriert -> Input gilt
void FernLaden()
{
   if(IsTesting())
      return;
   double v = 0.0;
   string k = "";

   k = FernGv("risiko");
   if(GlobalVariableCheck(k))
   {
      v = GlobalVariableGet(k);
      if(v >= 0.1 - 1e-9 && v <= 25.0 + 1e-9)
         g_risiko = v;
   }
   k = FernGv("maxlot");
   if(GlobalVariableCheck(k))
   {
      v = GlobalVariableGet(k);
      double minLot = MarketInfo(Symbol(), MODE_MINLOT);
      if(minLot > 0.0 && v >= minLot - 1e-9 && v <= FernMaxLotObergrenze + 1e-9)
         g_maxLot = v;
   }
   k = FernGv("limit");
   if(GlobalVariableCheck(k))
   {
      v = GlobalVariableGet(k);
      if(v == 0.0 || (v >= 1.0 - 1e-9 && v <= 100.0 + 1e-9))
         g_limitProz = v;
   }
   if(GlobalVariableCheck(FernGv("von")) && GlobalVariableCheck(FernGv("bis")))
   {
      int von = (int)MathRound(GlobalVariableGet(FernGv("von")));
      int bis = (int)MathRound(GlobalVariableGet(FernGv("bis")));
      if(von >= 0 && von <= 1439 && bis >= 0 && bis <= 1439 && von != bis)
      {
         g_startMin = von;
         g_endeMin  = bis;
      }
   }
   k = FernGv("crv");
   if(GlobalVariableCheck(k))
   {
      v = GlobalVariableGet(k);
      if(v >= 1.0 - 1e-9 && v <= 5.0 + 1e-9)
         g_minCRV = v;
   }
   k = FernGv("vwap");
   if(GlobalVariableCheck(k))
      g_vwapPflicht = (GlobalVariableGet(k) != 0.0);
   k = FernGv("lunte");
   if(GlobalVariableCheck(k))
      g_doppelLunte = (GlobalVariableGet(k) != 0.0);
   k = FernGv("m5");
   if(GlobalVariableCheck(k))
      g_m5Filter = (GlobalVariableGet(k) != 0.0);
   k = FernGv("be");
   if(GlobalVariableCheck(k))
      g_beAktiv = (GlobalVariableGet(k) != 0.0);
   k = FernGv("trail");
   if(GlobalVariableCheck(k))
      g_trailAktiv = (GlobalVariableGet(k) != 0.0);
   k = FernGv("bericht");
   if(GlobalVariableCheck(k))
   {
      v = GlobalVariableGet(k);
      if(v < 0.0)
         g_berichtMin = -1;
      else if(v <= 1439.0)
         g_berichtMin = (int)MathRound(v);
   }
   k = FernGv("modus");
   if(GlobalVariableCheck(k))
   {
      // Vollautomatik wird nie aus dem Speicher wiederhergestellt (nur nach Bestätigung per Knopf)
      int m = (int)MathRound(GlobalVariableGet(k));
      if(m == (int)MANUELLE_FREIGABE)
         g_modus = MANUELLE_FREIGABE;
      else if(m == (int)NUR_SIGNALE)
         g_modus = NUR_SIGNALE;
   }
   bool vorhanden = false;
   string news = FernNewsLesen(vorhanden);
   if(vorhanden)
   {
      if(!NewsParsen(news) || g_newsAnz > FERN_MAXPAUSEN)
      {
         Print("ScalpScout Trend: gespeicherte News-Pausen ungültig - Input gilt.");
         NewsParsen(g_newsEingabe);
      }
   }
}

bool AbwRisiko() { return MathAbs(g_risiko - RisikoProzent) > 1e-9; }
bool AbwMaxLot() { return MathAbs(g_maxLot - MaxLot) > 1e-9; }
bool AbwLimit()  { return MathAbs(g_limitProz - TagesVerlustProzent) > 1e-9; }
bool AbwZeit()   { return (g_startMin != ParseHHMM(HandelStart) || g_endeMin != ParseHHMM(HandelEnde)); }
bool AbwCrv()    { return MathAbs(g_minCRV - MinCRV) > 1e-9; }
bool AbwNews()   { return NewsText() != g_newsEingabe; }
bool AbwVwap()   { return g_vwapPflicht != VWAP_Pflicht; }
bool AbwLunte()  { return g_doppelLunte != DoppelLunteAktiv; }
bool AbwM5()     { return g_m5Filter != TrendM5Filter; }
bool AbwBe()     { return g_beAktiv != BE_Aktiv; }
bool AbwTrail()  { return g_trailAktiv != TrailingAktiv; }
bool AbwBericht(){ return g_berichtMin != BerichtEingabeMin(); }
bool AbwModus()  { return (!IsTesting() && g_modus != Modus); }

string FernMark(bool abweichend)
{
   return abweichend ? " <i>(fern geändert)</i>" : "";
}

// Alle Werte, die vom Input abweichen, als Text (leer = alles wie in den Inputs)
string FernListe()
{
   string s = "";
   if(AbwModus())  s += "Modus " + ModusText() + ", ";
   if(AbwRisiko()) s += "Risiko " + Zahl(g_risiko, 2) + " %, ";
   if(AbwMaxLot()) s += "MaxLot " + LotText(g_maxLot) + ", ";
   if(AbwLimit())  s += "Tageslimit " + LimitText() + ", ";
   if(AbwZeit())   s += "Zeit " + FensterText() + ", ";
   if(AbwCrv())    s += "MinCRV " + Zahl(g_minCRV, 2) + ", ";
   if(AbwNews())   s += "News " + ((g_newsAnz > 0) ? NewsText() : "keine") + ", ";
   if(AbwVwap())   s += "VWAP-Pflicht " + AnAusText(g_vwapPflicht) + ", ";
   if(AbwLunte())  s += "Doppellunte " + AnAusText(g_doppelLunte) + ", ";
   if(AbwM5())     s += "M5-Filter " + AnAusText(g_m5Filter) + ", ";
   if(AbwBe())     s += "Break-even " + AnAusText(g_beAktiv) + ", ";
   if(AbwTrail())  s += "Trailing " + AnAusText(g_trailAktiv) + ", ";
   if(AbwBericht()) s += "Tagesbericht " + BerichtZeitText() + ", ";
   if(StringLen(s) >= 2)
      s = StringSubstr(s, 0, StringLen(s) - 2);
   return s;
}

// /reset: gespeicherte Werte löschen, Inputs gelten wieder
void FernZuruecksetzen()
{
   if(!IsTesting())
   {
      FernGvLoeschen("risiko");
      FernGvLoeschen("maxlot");
      FernGvLoeschen("limit");
      FernGvLoeschen("von");
      FernGvLoeschen("bis");
      FernGvLoeschen("crv");
      FernGvLoeschen("vwap");
      FernGvLoeschen("lunte");
      FernGvLoeschen("m5");
      FernGvLoeschen("modus");
      FernGvLoeschen("be");
      FernGvLoeschen("trail");
      FernGvLoeschen("bericht");
      if(FileIsExist(FernNewsDatei()))
         FileDelete(FernNewsDatei());
   }
   FernEingabenSetzen();
   for(int ci = 0; ci < 4; ci++)
      CfgBeenden(ci, "⌛ durch /reset verworfen");
   BerichtNeuAnsetzen();
   g_tagesLimit = false;
   TagPruefen();
}

//--- Zähler für Gründe (/diag) --------------------------------------
// Gründe werden ohne Zahlen und Klammerzusatz zusammengefasst ("Pause nach 3 Verlusten (noch 5 min)")
void HistZaehlen(string &keys[], string &texte[], int &anz[], int &n, int &gesamt, string grund)
{
   int p = StringFind(grund, " (");
   if(p > 0)
      grund = StringSubstr(grund, 0, p);
   p = StringFind(grund, ":");
   if(p > 0)
      grund = StringSubstr(grund, 0, p);
   string key = "";
   int len = StringLen(grund);
   for(int i = 0; i < len; i++)
   {
      int c = (int)StringGetCharacter(grund, i);
      if((c >= 48 && c <= 57) || c == 46)
         continue;
      key += StringSubstr(grund, i, 1);
   }
   gesamt++;
   for(int j = 0; j < n; j++)
   {
      if(keys[j] == key)
      {
         anz[j]++;
         return;
      }
   }
   if(n < HIST_MAX)
   {
      keys[n]  = key;
      texte[n] = grund;
      anz[n]   = 1;
      n++;
   }
}

// häufigster Grund; false wenn der Zähler leer ist
bool HistSpitze(string &texte[], int &anz[], int n, string &text, int &haeufig)
{
   int best = -1;
   for(int i = 0; i < n; i++)
      if(best < 0 || anz[i] > anz[best])
         best = i;
   if(best < 0)
      return false;
   text    = texte[best];
   haeufig = anz[best];
   return true;
}

void DiagVerworfen(string grund)
{
   if(!g_tgAktiv)
      return;
   HistZaehlen(g_vwKey, g_vwText, g_vwAnz, g_vwN, g_vwGes, grund);
}

//--- Diagnose der letzten Kerze -------------------------------------
void DiagReset()
{
   g_dgM5          = g_m5Filter ? -1 : 2;
   g_dgM5Close     = 0.0;
   g_dgM5Ema       = 0.0;
   g_dgBerueh      = -1;
   g_dgFarb        = -1;
   g_dgLunte       = -1;
   g_dgBruch       = BruchSperreAktiv ? -1 : 2;
   g_dgSL          = 0.0;
   g_dgTP          = 0.0;
   g_dgCRV         = 0.0;
   g_dgCrvGeprueft = false;
}

// Doppellunte (Paar von Lunten mit etwa gleichem Tief/Hoch) vorhanden? Wie in PullbackPruefen, nur zur Anzeige.
bool DiagLunteVorhanden(int r, double tol)
{
   for(int a = 1; a <= 2; a++)
      for(int b = a + 1; b <= 3; b++)
      {
         if(r > 0)
         {
            if(MathAbs(iLow(Symbol(), PERIOD_M1, a) - iLow(Symbol(), PERIOD_M1, b)) <= tol &&
               UntereLunte(a) > KerzenKoerper(a) && UntereLunte(b) > KerzenKoerper(b))
               return true;
         }
         else
         {
            if(MathAbs(iHigh(Symbol(), PERIOD_M1, a) - iHigh(Symbol(), PERIOD_M1, b)) <= tol &&
               ObereLunte(a) > KerzenKoerper(a) && ObereLunte(b) > KerzenKoerper(b))
               return true;
         }
      }
   return false;
}

// Muster und AVWAP-Berührung für /diag (reine Anzeige, verändert nichts an der Signal-Logik)
void DiagMuster(int r, double nahe, double tol)
{
   double o1 = iOpen(Symbol(), PERIOD_M1, 1);
   double c1 = iClose(Symbol(), PERIOD_M1, 1);
   double o2 = iOpen(Symbol(), PERIOD_M1, 2);
   double c2 = iClose(Symbol(), PERIOD_M1, 2);
   bool fw = false, dl = false, berFW = false, berDL = false;
   if(r > 0)
   {
      double l1 = iLow(Symbol(), PERIOD_M1, 1);
      double l2 = iLow(Symbol(), PERIOD_M1, 2);
      double l3 = iLow(Symbol(), PERIOD_M1, 3);
      fw    = (c2 < o2 && c1 > o1 && c1 > g_avwap);
      berFW = (MathMin(l1, l2) <= g_avwap + nahe);
      berDL = (MathMin(l1, MathMin(l2, l3)) <= g_avwap + nahe);
      if(g_doppelLunte && c1 > o1)
         dl = DiagLunteVorhanden(r, tol);
   }
   else
   {
      double h1 = iHigh(Symbol(), PERIOD_M1, 1);
      double h2 = iHigh(Symbol(), PERIOD_M1, 2);
      double h3 = iHigh(Symbol(), PERIOD_M1, 3);
      fw    = (c2 > o2 && c1 < o1 && c1 < g_avwap);
      berFW = (MathMax(h1, h2) >= g_avwap - nahe);
      berDL = (MathMax(h1, MathMax(h2, h3)) >= g_avwap - nahe);
      if(g_doppelLunte && c1 < o1)
         dl = DiagLunteVorhanden(r, tol);
   }
   g_dgFarb  = fw ? 1 : 0;
   g_dgLunte = g_doppelLunte ? (dl ? 1 : 0) : 2;
   if(fw || dl)
      g_dgBerueh = ((fw && berFW) || (dl && berDL)) ? 1 : 0;
   else
      g_dgBerueh = berDL ? 1 : 0;
}

// Nach jeder Auswertung: Ergebnis merken (Werte, die PullbackPruefen nicht selbst gemerkt hat)
void DiagSpeichern(int r, double atr)
{
   g_dgZeit     = iTime(Symbol(), PERIOD_M1, 1);
   g_dgAtr      = atr;
   g_dgRichtung = g_trend;
   g_dgAvwap    = g_avwap;
   g_dgZiel     = g_ziel;
   g_dgTiefN    = MathMin(2, g_swLN);
   for(int i = 0; i < g_dgTiefN; i++)
      g_dgTief[i] = g_swLP[i];
   g_dgHochN    = MathMin(2, g_swHN);
   for(int j = 0; j < g_dgHochN; j++)
      g_dgHoch[j] = g_swHP[j];
   g_dgEnde     = (r != 0) ? g_stratGrund : "kein Signal: " + g_stratGrund;
   g_dgFilter   = "-";
   if(g_tgAktiv)
   {
      string grund = "";
      bool   frei  = HandelErlaubt(grund, atr);
      g_dgFilter   = frei ? "alle ok (Zeit, News, Limit, Pause, Positionen, Kosten)" : grund;
   }
}

//+------------------------------------------------------------------+
//| Plan berechnen: Preise, SL/TP, Lot                               |
//+------------------------------------------------------------------+
// Kosten (Spread + Kommission) als Preisabstand
double KostenPreis()
{
   return (Ask - Bid) + KommissionPunkte() * Point;
}

// CRV nach Kosten = (TP-Distanz - Kosten) / (SL-Distanz + Kosten)
double CrvNachKosten(double slDist, double tpDist)
{
   double k      = KostenPreis();
   double nenner = slDist + k;
   if(nenner <= 0.0)
      return 0.0;
   return (tpDist - k) / nenner;
}

// slFix/tpFix: absolute SL-/TP-Preise aus der Marktstruktur. Mit dem aktuellen Preis wird neu geprüft
// (Seite, StopLevel, CRV nach Kosten) und das Lot aus dem Risiko berechnet.
bool BerechnePlan(int richtung, double atr, Plan &p, string &grund, double slFix, double tpFix, int typ)
{
   grund = "";
   RefreshRates();

   if(atr <= 0.0)
   {
      grund = "ATR nicht verfügbar";
      return false;
   }
   if(slFix <= 0.0 || tpFix <= 0.0)
   {
      grund = "SL/TP aus der Struktur fehlen";
      return false;
   }

   p.richtung  = richtung;
   p.atr       = atr;
   p.typ       = typ;
   p.preis     = (richtung > 0) ? Ask : Bid;
   p.spreadPkt = SpreadPunkte();
   p.kommPkt   = KommissionPunkte();

   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;

   p.sl = NormalizeDouble(slFix, Digits);
   p.tp = NormalizeDouble(tpFix, Digits);
   // SL/TP werden bei Long am Bid, bei Short am Ask gemessen (StopLevel)
   bool seiteOK = (richtung > 0) ? (p.sl <= Bid - stopLvl && p.tp >= Bid + stopLvl)
                                 : (p.sl >= Ask + stopLvl && p.tp <= Ask - stopLvl);
   if(!seiteOK)
   {
      grund = "SL/TP nach Kursänderung auf falscher Seite oder unter dem Mindestabstand";
      return false;
   }
   p.slDist = MathAbs(p.preis - p.sl);
   p.tpDist = MathAbs(p.preis - p.tp);
   if(p.slDist <= 0.0)
   {
      grund = "SL-Abstand ungültig";
      return false;
   }
   p.crv = CrvNachKosten(p.slDist, p.tpDist);
   if(p.crv < g_minCRV)
   {
      grund = "CRV nach Kursänderung zu klein (" + DoubleToString(p.crv, 2) + " < " + DoubleToString(g_minCRV, 2) + ")";
      return false;
   }

   // Lotgröße aus Risiko
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double minLot    = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLotBr  = MarketInfo(Symbol(), MODE_MAXLOT);
   if(tickSize <= 0.0 || tickValue <= 0.0 || minLot <= 0.0)
   {
      grund = "Symbol-Daten (TickValue/TickSize/MinLot) fehlen";
      return false;
   }
   double risikoGeld   = AccountEquity() * g_risiko / 100.0;
   double verlustProLot = p.slDist / tickSize * tickValue + KommissionProLot;   // SL-Verlust + Kommission
   if(verlustProLot <= 0.0)
   {
      grund = "Verlust pro Lot ungültig";
      return false;
   }
   double lotRoh = risikoGeld / verlustProLot;
   double lot    = LotAbrunden(lotRoh);

   if(lot < minLot - 1e-9)
   {
      grund = "Lot " + DoubleToString(lotRoh, 4) + " < MinLot " + DoubleToString(minLot, 2)
              + ": Risiko " + DoubleToString(g_risiko, 1) + " % zu klein, kein Trade";
      return false;
   }
   if(lot > g_maxLot)
      lot = LotAbrunden(g_maxLot);
   if(maxLotBr > 0.0 && lot > maxLotBr)
      lot = LotAbrunden(maxLotBr);
   if(lot < minLot - 1e-9)
   {
      grund = "MaxLot-Deckel (" + DoubleToString(g_maxLot, 2) + ") < MinLot " + DoubleToString(minLot, 2)
              + ", kein Trade";
      return false;
   }
   p.lot = lot;

   // Margin prüfen
   ResetLastError();
   double fm  = AccountFreeMarginCheck(Symbol(), (richtung > 0) ? OP_BUY : OP_SELL, p.lot);
   int    err = GetLastError();
   if(fm <= 0.0 || err == FEHLER_NICHT_GENUG_GELD)
   {
      if(err != 0)
         LogFehler("AccountFreeMarginCheck", err);
      grund = "Nicht genug freie Margin für " + DoubleToString(p.lot, 2) + " Lot";
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Order senden (mit Retry bei Requote)                             |
//+------------------------------------------------------------------+
bool OrderOeffnen(int richtung, double atr, string &grund, double slFix, double tpFix)
{
   int   cmd  = (richtung > 0) ? OP_BUY : OP_SELL;
   color clr  = (richtung > 0) ? clrLime : clrRed;
   int   slip = SlippagePunkte();
   int   max  = MathMax(1, OrderVersuche);

   for(int v = 1; v <= max; v++)
   {
      // Handelskontext abwarten (max. ca. 3 s)
      if(!IsTesting())
      {
         int warte = 0;
         while(IsTradeContextBusy() && warte < 60)
         {
            Sleep(50);
            warte++;
         }
      }

      // Bei jedem Versuch frische Preise, SL/TP relativ zum aktuellen Preis
      Plan p;
      if(!BerechnePlan(richtung, atr, p, grund, slFix, tpFix, 0))
         return false;

      ResetLastError();
      int ticket = OrderSend(Symbol(), cmd, p.lot, p.preis, slip, p.sl, p.tp,
                             ORDER_KOMMENTAR, MagicNumber, 0, clr);
      if(ticket > 0)
      {
         Print("ScalpScout Trend: Order eröffnet #", ticket, " ", (richtung > 0 ? "BUY " : "SELL "),
               DoubleToString(p.lot, 2), " ", Symbol(), " @", DoubleToString(p.preis, Digits),
               " SL ", DoubleToString(p.sl, Digits), " TP ", DoubleToString(p.tp, Digits),
               " (Versuch ", v, ")");
         g_orderTicket = ticket;
         g_dgTrades++;
         g_orderPreis  = p.preis;
         if(OrderSelect(ticket, SELECT_BY_TICKET))
            g_orderPreis = OrderOpenPrice();
         return true;
      }

      int err = GetLastError();
      LogFehler("OrderSend (Versuch " + IntegerToString(v) + "/" + IntegerToString(max) + ")", err);
      grund = "OrderSend: " + FehlerText(err) + " (" + IntegerToString(err) + ")";

      bool wiederholen = (err == FEHLER_REQUOTE || err == FEHLER_PREIS_GEAENDERT ||
                          err == FEHLER_KEINE_KURSE || err == FEHLER_BROKER_BESCHAEFT ||
                          err == FEHLER_KONTEXT_BELEGT);
      if(!wiederholen)
         return false;
      if(!IsTesting())
         Sleep(200);
   }
   return false;
}

//+------------------------------------------------------------------+
//| Positionen verwalten: Break-even und Trailing                    |
//+------------------------------------------------------------------+
void PositionenVerwalten()
{
   if(!g_beAktiv && !g_trailAktiv)
      return;
   double atr = AktuelleATR();
   if(atr <= 0.0)
      return;
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber)
         continue;
      int typ = OrderType();
      if(typ > OP_SELL)
         continue;

      double offen = OrderOpenPrice();
      double sl    = OrderStopLoss();
      double neu   = sl;
      bool   aendern = false;

      if(typ == OP_BUY)
      {
         double gewinn = Bid - offen;
         if(g_beAktiv && gewinn >= BE_ATR * atr)
         {
            double be = NormalizeDouble(offen + BE_PufferPunkte * Point, Digits);
            if(sl == 0.0 || be > sl + Point / 2.0)
               neu = be;
         }
         if(g_trailAktiv && gewinn >= TrailingStartATR * atr)
         {
            double t = NormalizeDouble(Bid - TrailingATR * atr, Digits);
            if(neu == 0.0 || t > neu + TrailingSchrittATR * atr)
               neu = t;
         }
         neu = NormalizeDouble(neu, Digits);
         aendern = (neu > 0.0 && (sl == 0.0 || neu > sl + Point / 2.0) && neu <= Bid - stopLvl);
      }
      else
      {
         double gewinn = offen - Ask;
         if(g_beAktiv && gewinn >= BE_ATR * atr)
         {
            double be = NormalizeDouble(offen - BE_PufferPunkte * Point, Digits);
            if(sl == 0.0 || be < sl - Point / 2.0)
               neu = be;
         }
         if(g_trailAktiv && gewinn >= TrailingStartATR * atr)
         {
            double t = NormalizeDouble(Ask + TrailingATR * atr, Digits);
            if(neu == 0.0 || t < neu - TrailingSchrittATR * atr)
               neu = t;
         }
         neu = NormalizeDouble(neu, Digits);
         aendern = (neu > 0.0 && (sl == 0.0 || neu < sl - Point / 2.0) && neu >= Ask + stopLvl);
      }

      if(aendern)
      {
         ResetLastError();
         if(!OrderModify(OrderTicket(), offen, neu, OrderTakeProfit(), 0, clrDodgerBlue))
         {
            int err = GetLastError();
            if(err != 1)   // 1 = keine Änderung, harmlos
               LogFehler("OrderModify #" + IntegerToString(OrderTicket()), err);
         }
         else
            Print("ScalpScout Trend: SL #", OrderTicket(), " nachgezogen auf ", DoubleToString(neu, Digits));
      }
   }
}

//+------------------------------------------------------------------+
//| Kill-Switch: alle eigenen Positionen auf diesem Symbol schließen |
//+------------------------------------------------------------------+
void AlleSchliessen(int &geschlossen, int &fehler)
{
   geschlossen = 0;
   fehler      = 0;
   int slip = SlippagePunkte();
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber || OrderType() > OP_SELL)
         continue;
      int    ticket = OrderTicket();
      int    typ    = OrderType();
      double lots   = OrderLots();
      bool   ok     = false;
      for(int v = 1; v <= 3 && !ok; v++)
      {
         RefreshRates();
         double preis = (typ == OP_BUY) ? Bid : Ask;
         ResetLastError();
         ok = OrderClose(ticket, lots, preis, slip, clrOrange);
         if(!ok)
         {
            LogFehler("OrderClose #" + IntegerToString(ticket) + " (Versuch " + IntegerToString(v) + ")",
                      GetLastError());
            if(!IsTesting())
               Sleep(200);
         }
         // für nächsten Versuch Order neu selektieren
         if(!ok && !OrderSelect(ticket, SELECT_BY_TICKET))
            break;
      }
      if(ok) geschlossen++; else fehler++;
   }
   g_gestoppt = true;
   g_stopTg   = false;     // Telegram setzt das Merkmal nach dem Aufruf selbst
   SignalVerwerfen("Kill-Switch", "🛑 verworfen (Kill-Switch)");
   PanelLoeschen();
   g_sig.aktiv = false;
   HinweisSetzen("Kill-Switch: " + IntegerToString(geschlossen) + " Position(en) geschlossen, "
                 + IntegerToString(fehler) + " Fehler. Neue Trades gesperrt.");
   Alert("ScalpScout Trend ", Symbol(), ": Kill-Switch - ", geschlossen, " geschlossen, ", fehler, " Fehler");
}

//+------------------------------------------------------------------+
//| Oberfläche: Objekt-Helfer                                        |
//+------------------------------------------------------------------+
void LabelSetzen(string name, int x, int y, string text, color clr, int groesse = 9)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, groesse);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void RechteckSetzen(string name, int x, int y, int b, int h, color bg, color rand)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, b);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, rand);
}

void KnopfSetzen(string name, int x, int y, int b, int h, string text, color bg, color fg)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, b);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

// Waagerechte Linie (SL/TP des Signals); liegt unter OBJ_PNL_PRAEFIX und wird mit dem Panel gelöscht
void HLineSetzen(string name, double preis, color clr)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, preis);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   }
   ObjectMove(0, name, 0, 0, preis);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
}

string TypText(int typ)
{
   if(typ == 1) return "Farbwechsel";
   if(typ == 2) return "Doppellunte";
   return "-";
}

string TrendText(int tr)
{
   if(tr > 0) return "AUF";
   if(tr < 0) return "AB";
   return "seitwärts";
}

string ModusText()
{
   switch(g_modus)
   {
      case MANUELLE_FREIGABE: return "Manuelle Freigabe";
      case VOLLAUTOMATIK:     return "Vollautomatik";
      case NUR_SIGNALE:       return "Nur Signale";
   }
   return "?";
}

//+------------------------------------------------------------------+
//| Info-Bereich oben links                                          |
//+------------------------------------------------------------------+
void InfoAufbauen()
{
   if(!g_ui)
      return;
   // Dunkler Hintergrund zuerst, damit Labels und Knopf darüber liegen
   RechteckSetzen(OBJ_INFO_BG, 4, 24, INFO_BREITE, INFO_ZEILEN * 15 + 40, C'20,20,20', clrGray);
   for(int i = 0; i < INFO_ZEILEN; i++)
      LabelSetzen(PRAEFIX + "info_" + IntegerToString(i), 10, 30 + i * 15, "", clrWhite);
   KnopfSetzen(OBJ_KILL, 10, 30 + INFO_ZEILEN * 15 + 6, 200, 22, "ALLES SCHLIESSEN", clrFireBrick, clrWhite);
}

void InfoZeile(int i, string text, color clr)
{
   LabelSetzen(PRAEFIX + "info_" + IntegerToString(i), 10, 30 + i * 15, Kuerzen(text, INFO_MAXZEICHEN), clr);
}

void UiAktualisieren()
{
   if(!g_ui)
      return;
   double atr    = AktuelleATR();
   double maxSp  = MaxSpreadAktuell(atr);
   double sp     = SpreadPunkte();
   double ko     = KommissionPunkte();
   double diff   = AccountEquity() - g_tagEquity;
   double proz   = (g_tagEquity > 0.0) ? diff / g_tagEquity * 100.0 : 0.0;
   string grund  = "";
   bool   frei   = HandelErlaubt(grund, atr);

   InfoZeile(0, "ScalpScout Trend | " + Symbol() + " | Magic " + IntegerToString(MagicNumber), clrWhite);
   InfoZeile(1, "Modus: " + ModusText() + (IsTesting() ? " (Tester)" : "") + ((FernListe() != "") ? " | Fern-Einstellungen aktiv" : ""), clrWhite);
   InfoZeile(2, "Kosten: " + KostenText(sp, ko) + " / max " + MaxKostenText(maxSp),
             (maxSp > 0.0 && sp + ko > maxSp) ? clrOrangeRed : clrLime);
   InfoZeile(3, "ATR(" + IntegerToString(ATR_Periode) + ", M1): " + DoubleToString(atr, Digits)
                + " (" + DoubleToString(atr / Point, 0) + " Pkt)", clrWhite);
   InfoZeile(4, "Serverzeit: " + TimeToString(TimeCurrent(), TIME_MINUTES)
                + " (Handel " + FensterText() + ")",
             ZeitfensterOK() ? clrLime : clrOrange);
   InfoZeile(5, "Tagesergebnis: " + DoubleToString(diff, 2) + " " + AccountCurrency()
                + " (" + DoubleToString(proz, 2) + " %)", (diff >= 0.0) ? clrLime : clrOrangeRed);
   InfoZeile(6, g_tagesLimit ? "Verlustlimit: ERREICHT (" + LimitText() + ")"
                             : "Verlustlimit: ok (max " + LimitText() + ")",
             g_tagesLimit ? clrOrangeRed : clrLime);
   InfoZeile(7, frei ? "Status: bereit" : "Blockiert: " + grund, frei ? clrLime : clrOrange);
   color tgFarbe = clrSilver;
   string tgText = TgInfoText(tgFarbe);
   InfoZeile(8, tgText, tgFarbe);
   string h = (g_hinweis == "") ? "Hinweis: -" :
              "Hinweis (" + TimeToString(g_hinweisZeit, TIME_MINUTES) + "): " + g_hinweis;
   InfoZeile(9, h, (g_hinweis == "") ? clrSilver : clrGold);
   InfoZeile(10, "Strategie: Trend-Pullback | Trend: " + TrendText(g_trend)
                 + " | AVWAP: " + ((g_avwap > 0.0) ? DoubleToString(g_avwap, Digits) : "-")
                 + " | Ziel: " + ((g_ziel > 0.0) ? DoubleToString(g_ziel, Digits) : "-"),
             (g_trend > 0) ? clrLime : ((g_trend < 0) ? clrOrangeRed : clrSilver));
   InfoZeile(11, "Pullback-Prüfung: " + g_stratGrund, clrSilver);
}

//+------------------------------------------------------------------+
//| Signal-Panel (Freigabe-Modus)                                    |
//+------------------------------------------------------------------+
void PanelLoeschen()
{
   ObjectsDeleteAll(0, OBJ_PNL_PRAEFIX);
   ChartRedraw(0);
}

string PanelZeileText(int i)
{
   Plan p = g_sig.plan;
   switch(i)
   {
      case 0: return "SIGNAL: " + (p.richtung > 0 ? "LONG (Kauf)" : "SHORT (Verkauf)") + "  " + Symbol();
      case 1: return "Einstieg ca.: " + DoubleToString(p.preis, Digits);
      case 2: return "Stop-Loss: " + DoubleToString(p.sl, Digits) + "  (" + DoubleToString(p.slDist / Point, 0) + " Pkt)";
      case 3: return "Take-Profit: " + DoubleToString(p.tp, Digits) + "  (" + DoubleToString(p.tpDist / Point, 0) + " Pkt)";
      case 4: return "Lot: " + DoubleToString(p.lot, LotStellen(MarketInfo(Symbol(), MODE_LOTSTEP)))
                     + "  | Risiko " + DoubleToString(g_risiko, 1) + " %";
      case 5: return "Kosten: " + KostenText(p.spreadPkt, p.kommPkt) + " Pkt";
      case 6: return "Typ: " + TypText(p.typ) + " | CRV nach Kosten 1:" + DoubleToString(p.crv, 2);
      case 7:
      {
         int rest = SignalGueltigSek - (int)(TimeLocal() - g_sig.zeit);
         if(rest < 0) rest = 0;
         return "Gültig noch: " + IntegerToString(rest) + " s";
      }
   }
   return "";
}

void PanelZeigen()
{
   if(!g_ui)
      return;
   PanelLoeschen();
   int x = 10;
   int y = 30 + INFO_ZEILEN * 15 + 40;
   color titel = (g_sig.plan.richtung > 0) ? clrLime : clrOrangeRed;
   RechteckSetzen(OBJ_PNL_BG, x, y, 340, PNL_HOEHE, C'22,28,40', clrDimGray);
   for(int i = 0; i < PNL_ZEILEN; i++)
      LabelSetzen(OBJ_PNL_PRAEFIX + "z" + IntegerToString(i), x + 10, y + 8 + i * 18,
                  PanelZeileText(i), (i == 0) ? titel : clrWhite, (i == 0) ? 10 : 9);
   HLineSetzen(OBJ_PNL_PRAEFIX + "hl_sl", g_sig.plan.sl, clrRed);
   HLineSetzen(OBJ_PNL_PRAEFIX + "hl_tp", g_sig.plan.tp, clrLime);
   KnopfSetzen(OBJ_PNL_OK, x + 10,  y + PNL_HOEHE - 38, 150, 28, "[+] Ausführen", clrForestGreen, clrWhite);
   KnopfSetzen(OBJ_PNL_NO, x + 180, y + PNL_HOEHE - 38, 150, 28, "[–] Verwerfen", clrFireBrick, clrWhite);
   ChartRedraw(0);
}

void PanelAktualisieren()
{
   if(!g_ui || !g_sig.aktiv)
      return;
   for(int i = 0; i < PNL_ZEILEN; i++)
      ObjectSetString(0, OBJ_PNL_PRAEFIX + "z" + IntegerToString(i), OBJPROP_TEXT, PanelZeileText(i));
}

// tgText: Statuszeile für die Telegram-Nachricht (leer = Nachricht nicht ändern)
void SignalVerwerfen(string grund, string tgText = "")
{
   bool war = g_sig.aktiv;
   if(war)
   {
      Print("ScalpScout Trend: Signal verworfen - ", grund);
      DiagVerworfen(grund);
   }
   g_sig.aktiv = false;
   PanelLoeschen();
   if(war && tgText != "" && g_sigMsgId > 0)
      TgNachrichtBearbeiten(g_sigMsgId, g_tgKopf + "\n" + tgText);
}

// Ablauf und Preisabstand des offenen Signals prüfen
void SignalPruefen()
{
   if(!g_sig.aktiv)
      return;
   if(TimeLocal() - g_sig.zeit > SignalGueltigSek)
   {
      SignalVerwerfen("abgelaufen", "⌛ abgelaufen");
      HinweisSetzen("Signal abgelaufen (" + IntegerToString(SignalGueltigSek) + " s)");
      return;
   }
   RefreshRates();
   double aktuell = (g_sig.plan.richtung > 0) ? Ask : Bid;
   if(MathAbs(aktuell - g_sig.plan.preis) > PreisAbweichungATR * g_sig.plan.atr)
   {
      SignalVerwerfen("Preis zu weit vom Signal entfernt", "⌛ verworfen: Preis zu weit vom Signal entfernt");
      HinweisSetzen("Signal verworfen: Preis zu weit weg");
      return;
   }
   PanelAktualisieren();
}

// Klick auf "Ausführen" bzw. Telegram "JA". true = Order eröffnet.
// ergebnis: bei Erfolg "#Ticket @Preis", sonst der Grund.
// perTelegram: true = der Aufrufer (Telegram) ändert die Nachricht selbst.
bool SignalAusfuehren(bool perTelegram, string &ergebnis)
{
   ergebnis = "";
   if(!g_sig.aktiv)
   {
      ergebnis = "kein aktives Signal";
      return false;
   }
   SignalPruefen();
   if(!g_sig.aktiv)
   {
      ergebnis = "Signal abgelaufen";
      return false;
   }

   int    richtung = g_sig.plan.richtung;
   double atr      = g_sig.plan.atr;
   double slF      = g_sig.plan.sl;
   double tpF      = g_sig.plan.tp;
   long   msgId    = g_sigMsgId;
   string kopf     = g_tgKopf;
   g_sig.aktiv = false;      // gegen Doppelklick
   PanelLoeschen();

   string grund = "";
   bool   ok    = false;
   if(!HandelErlaubt(grund, atr))
   {
      HinweisSetzen("Nicht ausgeführt: " + grund);
      ergebnis = grund;
      DiagVerworfen(grund);
   }
   else if(!OrderOeffnen(richtung, atr, grund, slF, tpF))
   {
      HinweisSetzen("Nicht ausgeführt: " + grund);
      ergebnis = grund;
      DiagVerworfen(grund);
   }
   else
   {
      HinweisSetzen("Order ausgeführt (" + (richtung > 0 ? "LONG" : "SHORT") + ")");
      ergebnis = "#" + IntegerToString(g_orderTicket) + " @" + DoubleToString(g_orderPreis, Digits);
      ok = true;
   }

   if(!perTelegram && msgId > 0)
      TgNachrichtBearbeiten(msgId, kopf + "\n" + (ok ? "✅ am PC ausgeführt: " + ergebnis
                                                   : "⚠️ am PC nicht ausgeführt: " + HtmlEscape(ergebnis)));
   return ok;
}

//+------------------------------------------------------------------+
//| Benachrichtigung                                                 |
//+------------------------------------------------------------------+
void Melden(string text)
{
   Print("ScalpScout Trend: ", text);
   if(IsTesting())
      return;
   Alert(text);
   PlaySound("alert.wav");
   if(PushAktiv)
   {
      if(!SendNotification(text))
         LogFehler("SendNotification", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Telegram-Fernbedienung (WebRequest, nur Timer und Ereignisse)    |
//+------------------------------------------------------------------+
// Telegram ist komplett aus bei !TelegramAktiv, leerem Token/Chat-ID oder im Tester.
// Fehler führen nie zum Absturz: Anfragen schlagen still fehl, der Handel läuft weiter.

bool TgBereit()
{
   return (g_tgAktiv && !g_tgGesperrt && TimeLocal() >= g_tgSperreBis);
}

// Text für JSON-Strings: \ " und Zeilenumbruch maskieren, Nicht-ASCII als \uXXXX (Emoji = Surrogatpaar)
string JsonEscape(string s)
{
   string z = "0123456789abcdef";
   string r = "";
   int n = StringLen(s);
   for(int i = 0; i < n; i++)
   {
      int c = (int)StringGetCharacter(s, i);
      if(c == 92)
         r += "\\\\";
      else if(c == 34)
         r += "\\\"";
      else if(c == 10)
         r += "\\n";
      else if(c == 13)
         r += "\\r";
      else if(c == 9)
         r += "\\t";
      else if(c < 32 || c > 126)
         r += "\\u" + StringSubstr(z, (c >> 12) & 15, 1) + StringSubstr(z, (c >> 8) & 15, 1)
                    + StringSubstr(z, (c >> 4) & 15, 1) + StringSubstr(z, c & 15, 1);
      else
         r += StringSubstr(s, i, 1);
   }
   return r;
}

// Sonderzeichen für Telegram parse_mode HTML maskieren
string HtmlEscape(string s)
{
   StringReplace(s, "&", "&amp;");
   StringReplace(s, "<", "&lt;");
   StringReplace(s, ">", "&gt;");
   return s;
}

int HexZiffer(int c)
{
   if(c >= 48 && c <= 57)  return c - 48;        // 0-9
   if(c >= 97 && c <= 102) return c - 97 + 10;   // a-f
   if(c >= 65 && c <= 70)  return c - 65 + 10;   // A-F
   return 0;
}

// Ganzzahl zu "key": ab Position 'von' lesen (einfaches JSON-Parsing ohne Include)
bool JsonZahl(string s, string key, int von, long &wert)
{
   string k = "\"" + key + "\":";
   int p = StringFind(s, k, von);
   if(p < 0)
      return false;
   p += StringLen(k);
   int n = StringLen(s);
   while(p < n && StringGetCharacter(s, p) == 32)
      p++;
   string z = "";
   while(p < n)
   {
      int c = (int)StringGetCharacter(s, p);
      if((c >= 48 && c <= 57) || (z == "" && c == 45))
      {
         z += StringSubstr(s, p, 1);
         p++;
      }
      else
         break;
   }
   if(z == "" || z == "-")
      return false;
   wert = StringToInteger(z);
   return true;
}

// Text zu "key":"..." ab Position 'von' lesen, Escapes (\" \\ \n \uXXXX) auflösen
bool JsonText(string s, string key, int von, string &wert)
{
   string k = "\"" + key + "\":\"";
   int p = StringFind(s, k, von);
   if(p < 0)
      return false;
   p += StringLen(k);
   int n = StringLen(s);
   string r = "";
   while(p < n)
   {
      int c = (int)StringGetCharacter(s, p);
      if(c == 34)
      {
         wert = r;
         return true;
      }
      if(c == 92 && p + 1 < n)
      {
         int e = (int)StringGetCharacter(s, p + 1);
         p += 2;
         if(e == 110)       r += "\n";          // \n
         else if(e == 114)  r += "\r";          // \r
         else if(e == 116)  r += "\t";          // \t
         else if(e == 117 && p + 4 <= n)        // \uXXXX
         {
            int v = 0;
            for(int h = 0; h < 4; h++)
               v = v * 16 + HexZiffer((int)StringGetCharacter(s, p + h));
            r += ShortToString((ushort)v);
            p += 4;
         }
         else
            r += StringSubstr(s, p - 1, 1);      // \" \\ \/
         continue;
      }
      r += StringSubstr(s, p, 1);
      p++;
   }
   return false;
}

// Eine Anfrage an die Bot-API (POST, JSON). true nur bei "ok":true.
bool TgAnfrage(string methode, string jsonBody, string &antwort)
{
   antwort = "";
   if(!g_tgAktiv || g_tgGesperrt)
      return false;

   string url  = "https://api.telegram.org/bot" + g_tgToken + "/" + methode;
   string kopf = "Content-Type: application/json\r\n";
   string kopfAntwort = "";
   char   daten[];
   char   ergebnis[];

   StringToCharArray(jsonBody, daten, 0, -1, CP_UTF8);
   int groesse = ArraySize(daten);
   if(groesse > 0 && daten[groesse - 1] == 0)
      ArrayResize(daten, groesse - 1);      // abschließende Null entfernen

   ResetLastError();
   int code = WebRequest("POST", url, kopf, 5000, daten, ergebnis, kopfAntwort);
   if(code == -1)
   {
      int err = GetLastError();
      g_tgVerbunden = false;
      g_tgFehler    = err;
      if(err == 4060)
      {
         g_tgGesperrt = true;
         Print("ScalpScout Trend Telegram FEHLER 4060: URL nicht erlaubt. In MT4 Extras > Optionen > Expert Advisors ",
               "'WebRequest für folgende URLs erlauben' https://api.telegram.org eintragen, dann EA neu starten.");
      }
      else
      {
         g_tgSperreBis = TimeLocal() + 10;   // kurze Pause bei Netzproblemen
         LogFehler("Telegram " + methode, err);
      }
      return false;
   }

   antwort = CharArrayToString(ergebnis, 0, WHOLE_ARRAY, CP_UTF8);
   if(code >= 500 || code == 0)
      g_tgSperreBis = TimeLocal() + 10;
   else if(code == 401 || code == 404 || code == 409 || code == 429)
      g_tgSperreBis = TimeLocal() + 30;   // Token falsch / Webhook aktiv / Limit: nicht ständig neu versuchen
   if(StringFind(antwort, "\"ok\":true") < 0)
   {
      g_tgVerbunden = false;
      g_tgFehler    = code;
      string beschr = "";
      JsonText(antwort, "description", 0, beschr);
      Print("ScalpScout Trend Telegram: ", methode, " abgelehnt (HTTP ", code, ") ", beschr);
      return false;
   }
   g_tgVerbunden = true;
   g_tgFehler    = 0;
   return true;
}

// Nachricht senden; Rückgabe message_id (0 = nicht gesendet). tastatur = reply_markup-JSON oder "".
long TgNachrichtSenden(string html, string tastatur)
{
   if(!TgBereit())
      return 0;
   string body = "{\"chat_id\":\"" + JsonEscape(g_tgChat) + "\",\"text\":\"" + JsonEscape("[Trend] " + html)
                 + "\",\"parse_mode\":\"HTML\"";
   if(tastatur != "")
      body += ",\"reply_markup\":" + tastatur;
   body += "}";
   string antwort = "";
   if(!TgAnfrage("sendMessage", body, antwort))
      return 0;
   long id = 0;
   int p = StringFind(antwort, "\"message_id\":");
   if(p >= 0)
      JsonZahl(antwort, "message_id", p, id);
   return id;
}

// Text einer gesendeten Nachricht ändern und die Knöpfe entfernen
bool TgNachrichtBearbeiten(long msgId, string html)
{
   if(msgId <= 0 || !TgBereit())
      return false;
   string body = "{\"chat_id\":\"" + JsonEscape(g_tgChat) + "\",\"message_id\":" + IntegerToString(msgId)
                 + ",\"text\":\"" + JsonEscape("[Trend] " + html) + "\",\"parse_mode\":\"HTML\""
                 + ",\"reply_markup\":{\"inline_keyboard\":[]}}";
   string antwort = "";
   return TgAnfrage("editMessageText", body, antwort);
}

void TgCallbackAntwort(string cbId, string text)
{
   if(!TgBereit())
      return;
   string body = "{\"callback_query_id\":\"" + JsonEscape(cbId) + "\",\"text\":\"" + JsonEscape(text) + "\"}";
   string antwort = "";
   TgAnfrage("answerCallbackQuery", body, antwort);
}

// Eindeutige Signal-ID (Serverzeit-Sekunden, immer größer als die vorige)
int TgNeueSignalId()
{
   int id = (int)TimeCurrent();
   if(id <= g_sigId)
      id = g_sigId + 1;
   return id;
}

string TgTastatur(int id)
{
   string sid = IntegerToString(id);
   return "{\"inline_keyboard\":[[{\"text\":\"" + JsonEscape("✅ JA") + "\",\"callback_data\":\"ja_" + sid + "\"},"
          + "{\"text\":\"" + JsonEscape("❌ NEIN") + "\",\"callback_data\":\"nein_" + sid + "\"}]]}";
}

string TgSignalKopf(Plan &p)
{
   return "<b>" + HtmlEscape(Symbol()) + "</b>  " + ((p.richtung > 0) ? "🟢 KAUF" : "🔴 VERKAUF");
}

string TgSignalText(Plan &p)
{
   int ls = LotStellen(MarketInfo(Symbol(), MODE_LOTSTEP));
   return TgSignalKopf(p) + "\n"
        + "Strategie: Trend-Pullback (" + TypText(p.typ) + ")\n"
        + "Einstieg: " + DoubleToString(p.preis, Digits) + "\n"
        + "SL: " + DoubleToString(p.sl, Digits) + " (" + DoubleToString(p.slDist / Point, 0) + " Pkt)\n"
        + "TP: " + DoubleToString(p.tp, Digits) + " (" + DoubleToString(p.tpDist / Point, 0) + " Pkt)\n"
        + "Lot: " + DoubleToString(p.lot, ls) + "\n"
        + "Kosten: " + KostenText(p.spreadPkt, p.kommPkt) + " Pkt\n"
        + "CRV nach Kosten 1:" + DoubleToString(p.crv, 2);
}

// Gewinn/Verlust aller offenen eigenen Positionen auf diesem Symbol
double OffenerGewinn()
{
   double summe = 0.0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber && OrderType() <= OP_SELL)
         summe += OrderProfit() + OrderSwap() + OrderCommission();
   }
   return summe;
}

// Text für die Info-Zeile "Telegram: ..."
string TgInfoText(color &clr)
{
   string t;
   if(!g_tgAktiv)
   {
      clr = clrSilver;
      return "Telegram: aus";
   }
   if(g_tgGesperrt)
   {
      clr = clrOrangeRed;
      return "Telegram: Fehler 4060 - Extras>Optionen>Experts: https://api.telegram.org erlauben";
   }
   if(g_tgFehler != 0)
   {
      clr = clrOrangeRed;
      t   = "Telegram: Fehler " + IntegerToString(g_tgFehler);
   }
   else
   {
      clr = g_tgVerbunden ? clrLime : clrSilver;
      t   = g_tgVerbunden ? "Telegram: verbunden" : "Telegram: wartet";
   }
   if(g_tgPause)
   {
      clr = clrOrange;
      t  += " | Pausiert per Telegram";
   }
   return t;
}

string TgStatusText()
{
   double atr   = AktuelleATR();
   double sp    = SpreadPunkte();
   double ko    = KommissionPunkte();
   double maxSp = MaxSpreadAktuell(atr);
   double diff  = AccountEquity() - g_tagEquity;
   double proz  = (g_tagEquity > 0.0) ? diff / g_tagEquity * 100.0 : 0.0;
   string grund = "";
   bool   frei  = HandelErlaubt(grund, atr);
   string status = frei ? "Status: bereit" : "Blockiert: " + HtmlEscape(grund);
   string cur   = AccountCurrency();
   return "<b>ScalpScout Trend " + HtmlEscape(Symbol()) + "</b>\n"
        + "Modus: " + ModusText() + FernMark(AbwModus()) + "\n"
        + "Risiko: " + Zahl(g_risiko, 2) + " %" + FernMark(AbwRisiko())
        + " | MaxLot: " + LotText(g_maxLot) + FernMark(AbwMaxLot()) + "\n"
        + "Tageslimit: " + LimitText() + FernMark(AbwLimit()) + "\n"
        + "Handelsfenster: " + FensterText() + " (Serverzeit)" + FernMark(AbwZeit()) + "\n"
        + "MinCRV: " + Zahl(g_minCRV, 2) + FernMark(AbwCrv()) + "\n"
        + "News-Pausen: " + ((g_newsAnz > 0) ? NewsText() : "keine") + FernMark(AbwNews()) + "\n"
        + "VWAP-Pflicht: " + AnAusText(g_vwapPflicht) + FernMark(AbwVwap())
        + " | Doppellunte: " + AnAusText(g_doppelLunte) + FernMark(AbwLunte())
        + " | M5-Filter: " + AnAusText(g_m5Filter) + FernMark(AbwM5()) + "\n"
        + "Break-even: " + AnAusText(g_beAktiv) + FernMark(AbwBe())
        + " | Trailing: " + AnAusText(g_trailAktiv) + FernMark(AbwTrail())
        + " | Tagesbericht: " + BerichtZeitText() + FernMark(AbwBericht()) + "\n"
        + "Trend: " + TrendText(g_trend)
        + " | AVWAP: " + ((g_avwap > 0.0) ? DoubleToString(g_avwap, Digits) : "-")
        + " | Ziel: " + ((g_ziel > 0.0) ? DoubleToString(g_ziel, Digits) : "-") + "\n"
        + "Kosten: " + KostenText(sp, ko) + " / max " + MaxKostenText(maxSp) + "\n"
        + "Tagesergebnis: " + DoubleToString(diff, 2) + " " + cur + " (" + DoubleToString(proz, 2) + " %)\n"
        + "Offene Positionen: " + IntegerToString(ZaehlePositionen()) + " ("
        + DoubleToString(OffenerGewinn(), 2) + " " + cur + ")\n"
        + "Konto: " + DoubleToString(AccountBalance(), 2) + " | Equity " + DoubleToString(AccountEquity(), 2)
        + " | freie Margin " + DoubleToString(AccountFreeMargin(), 2) + " " + cur + "\n"
        + status;
}

string TgHilfeText()
{
   return "<b>Befehle</b> (Werte in Klammern = jetzt)\n"
        + "/status - Lage, Einstellungen, Konto\n"
        + "/diag - Prüfung der letzten Kerze und Zähler seit Start\n"
        + "/positionen - offene Positionen mit Gewinn\n"
        + "/heute - heute geschlossene Trades\n"
        + "/schliessen - alle Positionen schließen (mit Bestätigung)\n"
        + "/stop - neue Signale pausieren, /start hebt die Pause auf\n"
        + "/modus manuell|signale|auto - (" + ModusText() + "); auto nur nach Bestätigung\n"
        + "/risiko X - 0.1 bis 25 % (" + Zahl(g_risiko, 2) + ")\n"
        + "/maxlot X - bis " + LotText(FernMaxLotObergrenze) + " Lot (" + LotText(g_maxLot) + ")\n"
        + "/limit X|aus - Tagesverlust 1 bis 100 % (" + LimitText() + ")\n"
        + "/zeit HH:MM-HH:MM - Handelsfenster Serverzeit (" + FensterText() + ")\n"
        + "/crv X - Mindest-CRV 1.0 bis 5.0 (" + Zahl(g_minCRV, 2) + ")\n"
        + "/news HH:MM-HH:MM,HH:MM-HH:MM|aus - News-Pausen (" + ((g_newsAnz > 0) ? NewsText() : "keine") + ")\n"
        + "/vwap an|aus - AVWAP-Berührung nötig (" + AnAusText(g_vwapPflicht) + ")\n"
        + "/lunte an|aus - Doppellunte zulassen (" + AnAusText(g_doppelLunte) + ")\n"
        + "/m5 an|aus - M5-Filter (" + AnAusText(g_m5Filter) + ")\n"
        + "/be an|aus - Break-even (" + AnAusText(g_beAktiv) + "), /trailing an|aus (" + AnAusText(g_trailAktiv) + ")\n"
        + "/zu TICKET - eine Position schließen (mit Bestätigung)\n"
        + "/sl TICKET PREIS|be - Stop-Loss setzen, be = auf Einstieg\n"
        + "/tp TICKET PREIS - Take-Profit setzen\n"
        + "/kauf [LOT], /verkauf [LOT] - Hand-Trade: SL 1.0, TP 2.0 x ATR, Lot aus Risiko oder Angabe (bis "
        + LotText(FernMaxLotObergrenze) + "), mit Bestätigung\n"
        + "/bericht [HH:MM|aus] - Tagesbericht jetzt senden bzw. Zeit setzen (" + BerichtZeitText() + ")\n"
        + "/reset - Fern-Änderungen löschen, Inputs gelten wieder\n"
        + "Zahlen mit Komma oder Punkt.";
}

string DiagSwingText(const double &a[], int n)
{
   if(n <= 0)
      return "-";
   string s = DoubleToString(a[0], Digits);
   if(n > 1)
      s += " / " + DoubleToString(a[1], Digits);
   return s;
}

string DiagHaken(int w)
{
   if(w == 1) return "✓";
   if(w == 0) return "✗";
   return "-";
}

string TgDiagText()
{
   if(g_dgZeit == 0)
      return "Diagnose: noch keine Kerze ausgewertet.";

   string s = "<b>Diagnose " + HtmlEscape(Symbol()) + "</b> (Kerze " + TimeToString(g_dgZeit, TIME_MINUTES) + ")\n";
   s += "Trend: " + TrendText(g_dgRichtung) + "\n";
   s += "Swing-Tiefs (neu / alt): " + DiagSwingText(g_dgTief, g_dgTiefN) + "\n";
   s += "Swing-Hochs (neu / alt): " + DiagSwingText(g_dgHoch, g_dgHochN) + "\n";

   s += "M5-Filter: ";
   if(g_dgM5 == 2)
      s += "aus\n";
   else if(g_dgM5 < 0)
      s += "nicht geprüft\n";
   else
      s += DiagHaken(g_dgM5) + " (Close " + DoubleToString(g_dgM5Close, Digits) + ", EMA " + DoubleToString(g_dgM5Ema, Digits) + ")\n";

   s += "AVWAP: " + ((g_dgAvwap > 0.0) ? DoubleToString(g_dgAvwap, Digits) : "-")
      + " | Berührung: " + DiagHaken(g_dgBerueh) + (g_vwapPflicht ? "" : " (nicht gefordert)") + "\n";
   s += "Muster: Farbwechsel " + DiagHaken(g_dgFarb) + " | Doppellunte "
      + ((g_dgLunte == 2) ? "aus" : DiagHaken(g_dgLunte)) + "\n";
   s += "Bruch-Sperre: " + ((g_dgBruch == 2) ? "abgeschaltet" : ((g_dgBruch == 1) ? "aktiv" : ((g_dgBruch == 0) ? "nicht aktiv" : "nicht geprüft"))) + "\n";
   s += "Ziel: " + ((g_dgZiel > 0.0) ? DoubleToString(g_dgZiel, Digits) : "keins") + "\n";
   s += "SL: " + ((g_dgSL > 0.0) ? DoubleToString(g_dgSL, Digits) : "-") + "\n";
   if(g_dgCrvGeprueft)
      s += "CRV nach Kosten: " + DoubleToString(g_dgCRV, 2) + " (MinCRV " + Zahl(g_minCRV, 2) + ") "
         + ((g_dgCRV >= g_minCRV) ? "✓" : "✗") + "\n";
   else
      s += "CRV nach Kosten: nicht berechnet (MinCRV " + Zahl(g_minCRV, 2) + ")\n";
   s += "Filter: " + HtmlEscape(g_dgFilter) + "\n";
   s += "<b>Ergebnis: " + HtmlEscape(g_dgEnde) + "</b>\n";

   s += "Seit Start: " + IntegerToString(g_dgKerzen) + " Kerzen | " + IntegerToString(g_dgSignale) + " Signale | "
      + IntegerToString(g_dgTrades) + " Trades | " + IntegerToString(g_vwGes) + " Signale verworfen";
   string t = "";
   int    h = 0;
   if(HistSpitze(g_vwText, g_vwAnz, g_vwN, t, h))
      s += "\nHäufigster Verwerfungsgrund: " + HtmlEscape(t) + " (" + IntegerToString(h) + "x)";
   if(HistSpitze(g_ksText, g_ksAnz, g_ksN, t, h))
      s += "\nHäufigster Grund ohne Signal: " + HtmlEscape(t) + " (" + IntegerToString(h) + "x)";
   return s;
}

// Offene eigene Positionen mit Gewinn
string TgPositionenText()
{
   string s   = "";
   int    n   = 0;
   double sum = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber || OrderType() > OP_SELL)
         continue;
      double pr = OrderProfit() + OrderSwap() + OrderCommission();
      sum += pr;
      n++;
      s += "#" + IntegerToString(OrderTicket()) + " " + ((OrderType() == OP_BUY) ? "BUY " : "SELL ")
         + DoubleToString(OrderLots(), 2) + " @" + DoubleToString(OrderOpenPrice(), Digits)
         + " SL " + ((OrderStopLoss() > 0.0) ? DoubleToString(OrderStopLoss(), Digits) : "-")
         + " TP " + ((OrderTakeProfit() > 0.0) ? DoubleToString(OrderTakeProfit(), Digits) : "-")
         + ": " + ((pr >= 0.0) ? "+" : "") + DoubleToString(pr, 2) + "\n";
   }
   if(n == 0)
      return "Keine offenen Positionen auf <b>" + HtmlEscape(Symbol()) + "</b> (Magic " + IntegerToString(MagicNumber) + ").";
   return "<b>Offene Positionen " + HtmlEscape(Symbol()) + "</b>\n" + s
        + "Summe: " + ((sum >= 0.0) ? "+" : "") + DoubleToString(sum, 2) + " " + AccountCurrency();
}

// Heute (Serverzeit-Tag) geschlossene eigene Trades
string TgHeuteText()
{
   datetime von = (datetime)((long)TimeCurrent() / 86400 * 86400);
   int    n = 0, gew = 0, verl = 0, tBest = 0, tSchl = 0;
   double sum = 0.0, best = 0.0, schl = 0.0;
   int total = OrdersHistoryTotal();
   for(int i = 0; i < total; i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol() || OrderType() > OP_SELL)
         continue;
      if(OrderCloseTime() < von)
         continue;
      double pr = OrderProfit() + OrderSwap() + OrderCommission();
      if(n == 0 || pr > best)
      {
         best  = pr;
         tBest = OrderTicket();
      }
      if(n == 0 || pr < schl)
      {
         schl  = pr;
         tSchl = OrderTicket();
      }
      n++;
      sum += pr;
      if(pr > 0.0) gew++;
      else if(pr < 0.0) verl++;
   }
   if(n == 0)
      return "Heute noch keine geschlossenen Trades auf <b>" + HtmlEscape(Symbol()) + "</b>.";
   string cur = AccountCurrency();
   return "<b>Heute " + HtmlEscape(Symbol()) + "</b> (Serverzeit-Tag)\n"
        + "Geschlossene Trades: " + IntegerToString(n) + " | Gewinner " + IntegerToString(gew)
        + " | Verlierer " + IntegerToString(verl) + "\n"
        + "Summe: " + ((sum >= 0.0) ? "+" : "") + DoubleToString(sum, 2) + " " + cur + "\n"
        + "Bester: #" + IntegerToString(tBest) + " " + ((best >= 0.0) ? "+" : "") + DoubleToString(best, 2) + "\n"
        + "Schlechtester: #" + IntegerToString(tSchl) + " " + ((schl >= 0.0) ? "+" : "") + DoubleToString(schl, 2);
}

//--- Einstellungen ändern -------------------------------------------
// Erfolgsmeldung "MinCRV: 2.0 → 1.5" + Journal
void FernGeaendert(string name, string alt, string neu)
{
   Print("ScalpScout Trend Fern-Änderung: ", name, " ", alt, " -> ", neu);
   TgNachrichtSenden(HtmlEscape(name) + ": " + HtmlEscape(alt) + " → " + HtmlEscape(neu), "");
   UiAktualisieren();
}

// Zahl aus dem Befehl lesen und gegen den Bereich prüfen; sonst Fehlermeldung
bool TgZahlArg(string name, string arg, double von, double bis, string bereichText, double &wert)
{
   double v = 0.0;
   if(!ZahlParsen(arg, v) || v < von - 1e-9 || v > bis + 1e-9)
   {
      TgNachrichtSenden("⚠️ " + HtmlEscape(name) + ": ungültiger Wert. Erlaubt: " + bereichText + ".", "");
      return false;
   }
   wert = v;
   return true;
}

int AnAusParsen(string a)
{
   if(a == "an" || a == "ein" || a == "on" || a == "1")
      return 1;
   if(a == "aus" || a == "off" || a == "0")
      return 0;
   return -1;
}

void TgSchalterBefehl(string name, string arg, string schluessel, bool &ziel)
{
   int w = AnAusParsen(arg);
   if(w < 0)
   {
      TgNachrichtSenden("⚠️ " + HtmlEscape(name) + ": bitte 'an' oder 'aus' angeben (jetzt: " + AnAusText(ziel) + ").", "");
      return;
   }
   string alt = AnAusText(ziel);
   ziel = (w == 1);
   FernSetzen(schluessel, ziel ? 1.0 : 0.0);
   FernGeaendert(name, alt, AnAusText(ziel));
}

void TgRisikoBefehl(string arg)
{
   double v = 0.0;
   if(!TgZahlArg("Risiko", arg, 0.1, 25.0, "0.1 bis 25 (Prozent vom Equity)", v))
      return;
   string alt = Zahl(g_risiko, 2) + " %";
   g_risiko = NormalizeDouble(v, 2);
   FernSetzen("risiko", g_risiko);
   FernGeaendert("Risiko", alt, Zahl(g_risiko, 2) + " %");
}

void TgMaxLotBefehl(string arg)
{
   double minLot = MarketInfo(Symbol(), MODE_MINLOT);
   double grenze = FernMaxLotObergrenze;
   if(minLot <= 0.0 || grenze < minLot - 1e-9)
   {
      TgNachrichtSenden("⚠️ MaxLot: Obergrenze " + LotText(grenze) + " liegt unter MinLot " + LotText(minLot)
                        + ", keine Änderung per Telegram möglich.", "");
      return;
   }
   double v = 0.0;
   if(!TgZahlArg("MaxLot", arg, minLot, grenze, LotText(minLot) + " bis " + LotText(grenze) + " Lot", v))
      return;
   double lot = LotAbrunden(v);
   if(lot < minLot - 1e-9 || lot > grenze + 1e-9)
   {
      TgNachrichtSenden("⚠️ MaxLot: ungültiger Wert. Erlaubt: " + LotText(minLot) + " bis " + LotText(grenze) + " Lot.", "");
      return;
   }
   string alt = LotText(g_maxLot);
   g_maxLot = lot;
   FernSetzen("maxlot", g_maxLot);
   FernGeaendert("MaxLot", alt, LotText(g_maxLot));
}

void TgLimitBefehl(string arg)
{
   double v = 0.0;
   if(arg == "aus" || arg == "off" || arg == "0")
      v = 0.0;
   else if(!TgZahlArg("Tageslimit", arg, 1.0, 100.0, "1 bis 100 (Prozent) oder aus", v))
      return;
   string alt = LimitText();
   g_limitProz = NormalizeDouble(v, 2);
   FernSetzen("limit", g_limitProz);
   g_tagesLimit = false;      // neu bewerten: gilt das neue Limit schon als erreicht, rastet es sofort wieder ein
   TagPruefen();
   FernGeaendert("Tageslimit", alt, LimitText());
}

void TgZeitBefehl(string arg)
{
   int von = -1, bis = -1;
   int p = StringFind(arg, "-");
   if(p > 0)
   {
      string a = StringSubstr(arg, 0, p);
      string b = StringSubstr(arg, p + 1);
      StringTrimLeft(a);
      StringTrimRight(a);
      StringTrimLeft(b);
      StringTrimRight(b);
      von = ParseHHMM(a);
      bis = ParseHHMM(b);
   }
   if(von < 0 || bis < 0 || von == bis)
   {
      TgNachrichtSenden("⚠️ Handelsfenster: Format HH:MM-HH:MM in Serverzeit, Beginn und Ende verschieden, "
                        + "z. B. /zeit 08:00-20:00 (ganztägig: 00:00-23:59). Jetzt: " + FensterText() + ".", "");
      return;
   }
   string alt = FensterText();
   g_startMin = von;
   g_endeMin  = bis;
   FernSetzen("von", von);
   FernSetzen("bis", bis);
   FernGeaendert("Handelsfenster", alt, FensterText());
}

void TgCrvBefehl(string arg)
{
   double v = 0.0;
   if(!TgZahlArg("MinCRV", arg, 1.0, 5.0, "1.0 bis 5.0", v))
      return;
   string alt = Zahl(g_minCRV, 2);
   g_minCRV = NormalizeDouble(v, 2);
   FernSetzen("crv", g_minCRV);
   FernGeaendert("MinCRV", alt, Zahl(g_minCRV, 2));
}

void TgNewsBefehl(string arg)
{
   if(arg == "")
   {
      TgNachrichtSenden("News-Pausen jetzt: " + ((g_newsAnz > 0) ? NewsText() : "keine")
                        + "\nÄndern: /news HH:MM-HH:MM,HH:MM-HH:MM (Serverzeit) oder /news aus", "");
      return;
   }
   string alt = NewsText();
   string neu = arg;
   if(neu == "aus" || neu == "off" || neu == "keine")
      neu = "";
   if(!NewsParsen(neu) || g_newsAnz > FERN_MAXPAUSEN || (neu != "" && g_newsAnz == 0))
   {
      NewsParsen(alt);          // alten Stand wiederherstellen
      TgNachrichtSenden("⚠️ News-Pausen: Format HH:MM-HH:MM[,HH:MM-HH:MM] in Serverzeit, höchstens "
                        + IntegerToString(FERN_MAXPAUSEN) + " Pausen, oder /news aus.", "");
      return;
   }
   FernNewsSpeichern(NewsText());
   FernGeaendert("News-Pausen", (alt == "") ? "keine" : alt, (g_newsAnz > 0) ? NewsText() : "keine");
}

//--- Rückfragen mit Knöpfen (Vollautomatik, Alle schließen) ---------
string TgTastaturCfg(string aktion, string jaText)
{
   return "{\"inline_keyboard\":[[{\"text\":\"" + JsonEscape(jaText) + "\",\"callback_data\":\"cfg_" + aktion + "_ja\"},"
          + "{\"text\":\"" + JsonEscape("❌ Abbrechen") + "\",\"callback_data\":\"cfg_" + aktion + "_nein\"}]]}";
}

// Gültigkeit einer Rückfrage in Sekunden ([3] = Hand-Trade kürzer)
int CfgGueltig(int idx)
{
   return (idx == 3) ? HAND_GUELTIG_SEK : CFG_GUELTIG_SEK;
}

// Rückfrage beenden: Knöpfe entfernen, Status unter den Text schreiben, Zustand löschen
void CfgBeenden(int idx, string status)
{
   if(g_cfgZeit[idx] == 0)
      return;
   long   m = g_cfgMsg[idx];
   string t = g_cfgText[idx];
   g_cfgZeit[idx] = 0;
   g_cfgMsg[idx]  = 0;
   if(m > 0)
      TgNachrichtBearbeiten(m, t + "\n" + status);
}

void CfgAnlegen(int idx, string html, string tastatur)
{
   if(g_cfgZeit[idx] > 0)
      CfgBeenden(idx, "⌛ ersetzt durch neue Anfrage");
   long m = TgNachrichtSenden(html + "\n⏱ gültig " + IntegerToString(CfgGueltig(idx)) + " s", tastatur);
   if(m <= 0)
      return;
   g_cfgZeit[idx] = TimeLocal();
   g_cfgMsg[idx]  = m;
   g_cfgText[idx] = html;
}

// In OnTimer: abgelaufene Rückfragen schließen
void CfgAblaufPruefen()
{
   for(int i = 0; i < 4; i++)
      if(g_cfgZeit[i] > 0 && TimeLocal() - g_cfgZeit[i] > CfgGueltig(i))
         CfgBeenden(i, "⌛ abgelaufen");
}

void TgSchliessenBefehl()
{
   int n = ZaehlePositionen();
   if(n <= 0)
   {
      TgNachrichtSenden("Keine offenen Positionen auf <b>" + HtmlEscape(Symbol()) + "</b> (Magic " + IntegerToString(MagicNumber) + ").", "");
      return;
   }
   double g = OffenerGewinn();
   CfgAnlegen(1, "<b>" + HtmlEscape(Symbol()) + "</b>: " + IntegerToString(n) + " Position(en) offen ("
                 + ((g >= 0.0) ? "+" : "") + DoubleToString(g, 2) + " " + AccountCurrency() + ").\n"
                 + "Alle jetzt schließen? Danach sind neue Trades gesperrt (/start hebt die Sperre auf).",
              TgTastaturCfg("close", "✅ Alle schließen"));
}

// Betriebsart ohne Rückfrage wechseln (manuell/signale)
void TgModusWechseln(ENUM_MODUS neu)
{
   if(neu == g_modus)
   {
      TgNachrichtSenden("Modus ist bereits " + ModusText() + ".", "");
      return;
   }
   string alt = ModusText();
   g_modus = neu;
   FernSetzen("modus", (double)((int)neu));
   if(neu != MANUELLE_FREIGABE && g_sig.aktiv)
      SignalVerwerfen("Modus gewechselt", "⌛ Modus gewechselt");
   HinweisSetzen("Modus per Telegram: " + ModusText());
   FernGeaendert("Modus", alt, ModusText());
}

void TgModusBefehl(string arg)
{
   if(arg == "manuell")
      TgModusWechseln(MANUELLE_FREIGABE);
   else if(arg == "signale")
      TgModusWechseln(NUR_SIGNALE);
   else if(arg == "auto" || arg == "vollautomatik")
   {
      if(g_modus == VOLLAUTOMATIK)
      {
         TgNachrichtSenden("Modus ist bereits " + ModusText() + ".", "");
         return;
      }
      CfgAnlegen(0, "<b>Vollautomatik einschalten?</b>\nDer EA eröffnet dann Trades ohne weitere Freigabe "
                    + "(Risiko " + Zahl(g_risiko, 2) + " %, MaxLot " + LotText(g_maxLot) + ").",
                 TgTastaturCfg("auto", "✅ Vollautomatik einschalten"));
   }
   else
      TgNachrichtSenden("⚠️ Modus: erlaubt sind manuell, signale oder auto. Jetzt: " + ModusText() + ".", "");
}

// Knopfdruck "cfg_..." (nur aus berechtigtem Chat); cbMsg = message_id der Nachricht mit dem Knopf
void TgCfgCallback(string cbId, string data, long cbMsg)
{
   int  idx    = -1;
   bool ja     = false;
   int  ticket = 0;
   if(data == "cfg_auto_ja")         { idx = 0; ja = true; }
   else if(data == "cfg_auto_nein")  { idx = 0; }
   else if(data == "cfg_close_ja")   { idx = 1; ja = true; }
   else if(data == "cfg_close_nein") { idx = 1; }
   else if(data == "cfg_hand_ja")    { idx = 3; ja = true; }
   else if(data == "cfg_hand_nein")  { idx = 3; }
   else if(StringFind(data, "cfg_zu_") == 0)           // cfg_zu_<ticket>_ja / _nein
   {
      int e = StringFind(data, "_", 7);
      if(e > 7)
      {
         ticket = (int)StringToInteger(StringSubstr(data, 7, e - 7));
         string rest = StringSubstr(data, e + 1);
         if(rest == "ja")        { idx = 2; ja = true; }
         else if(rest == "nein") { idx = 2; }
      }
   }
   if(idx < 0)
   {
      TgCallbackAntwort(cbId, "unbekannte Aktion");
      return;
   }
   if(g_cfgZeit[idx] == 0)
   {
      TgCallbackAntwort(cbId, "Anfrage abgelaufen");
      if(cbMsg > 0)
         TgNachrichtBearbeiten(cbMsg, "⌛ Anfrage abgelaufen");     // Knöpfe der alten Nachricht entfernen
      return;
   }
   if((cbMsg > 0 && g_cfgMsg[idx] > 0 && cbMsg != g_cfgMsg[idx]) || (idx == 2 && ticket != g_cfgTicket[2]))
   {
      TgCallbackAntwort(cbId, "veraltete Anfrage");
      if(cbMsg > 0)
         TgNachrichtBearbeiten(cbMsg, "⌛ ersetzt durch neue Anfrage");
      return;
   }
   if(TimeLocal() - g_cfgZeit[idx] > CfgGueltig(idx))
   {
      TgCallbackAntwort(cbId, "Anfrage abgelaufen");
      CfgBeenden(idx, "⌛ abgelaufen");
      return;
   }
   if(!ja)
   {
      TgCallbackAntwort(cbId, "abgebrochen");
      CfgBeenden(idx, "❌ abgebrochen");
      return;
   }

   if(idx == 0)
   {
      g_modus = VOLLAUTOMATIK;
      FernGvLoeschen("modus");         // Vollautomatik wird nie gespeichert: nach Neustart gilt wieder der Input/letzte sichere Modus
      HinweisSetzen("Vollautomatik per Telegram eingeschaltet");
      Print("ScalpScout Trend Fern-Änderung: Modus -> Vollautomatik (bestätigt per Telegram)");
      TgCallbackAntwort(cbId, "Vollautomatik an");
      CfgBeenden(0, "✅ Vollautomatik eingeschaltet. Zurück mit /modus manuell oder /modus signale.");
   }
   else if(idx == 1)
   {
      int geschlossen = 0, fehler = 0;
      AlleSchliessen(geschlossen, fehler);
      g_stopTg = true;
      TgCallbackAntwort(cbId, "ausgeführt");
      CfgBeenden(1, "🛑 " + IntegerToString(geschlossen) + " Position(en) geschlossen, " + IntegerToString(fehler)
                    + " Fehler. Neue Trades gesperrt - /start hebt die Sperre auf.");
   }
   else if(idx == 2)
   {
      string erg = "";
      bool   ok  = PositionSchliessen(g_cfgTicket[2], erg);
      TgCallbackAntwort(cbId, ok ? "geschlossen" : "nicht geschlossen");
      CfgBeenden(2, ok ? "✅ " + HtmlEscape(erg) : "⚠️ nicht geschlossen: " + HtmlEscape(erg));
   }
   else
   {
      string erg = "";
      bool   ok  = HandTradeOeffnen(g_cfgDir[3], g_cfgLot[3], erg);
      TgCallbackAntwort(cbId, ok ? "ausgeführt" : "nicht ausgeführt");
      CfgBeenden(3, ok ? "✅ ausgeführt: " + HtmlEscape(erg) : "⚠️ nicht ausgeführt: " + HtmlEscape(erg));
   }
   UiAktualisieren();
}

//--- Einzelne Positionen, Hand-Trades, Tagesbericht -----------------
// Ticket aus dem Befehl ("123" oder "#123")
bool TicketParsen(string s, int &ticket)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   if(StringLen(s) > 0 && StringGetCharacter(s, 0) == 35)       // 35 = '#'
      s = StringSubstr(s, 1);
   int n = StringLen(s);
   if(n == 0 || n > 10)
      return false;
   for(int i = 0; i < n; i++)
   {
      int c = (int)StringGetCharacter(s, i);
      if(c < 48 || c > 57)
         return false;
   }
   long t = StringToInteger(s);
   if(t <= 0 || t > 2147483647)
      return false;
   ticket = (int)t;
   return true;
}

// Wählt das Ticket aus; true nur für eine offene Position dieses EAs auf diesem Symbol
bool EigenePositionWaehlen(int ticket)
{
   if(ticket <= 0 || !OrderSelect(ticket, SELECT_BY_TICKET))
      return false;
   if(OrderCloseTime() != 0)
      return false;
   return (OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber && OrderType() <= OP_SELL);
}

// Eine einzelne eigene Position schließen (ohne Kill-Switch)
bool PositionSchliessen(int ticket, string &ergebnis)
{
   ergebnis = "";
   if(!EigenePositionWaehlen(ticket))
   {
      ergebnis = "Position #" + IntegerToString(ticket) + " nicht (mehr) offen";
      return false;
   }
   int    typ  = OrderType();
   double lots = OrderLots();
   int    slip = SlippagePunkte();
   bool   ok   = false;
   for(int v = 1; v <= 3 && !ok; v++)
   {
      RefreshRates();
      double preis = (typ == OP_BUY) ? Bid : Ask;
      ResetLastError();
      ok = OrderClose(ticket, lots, preis, slip, clrOrange);
      if(!ok)
      {
         int err = GetLastError();
         LogFehler("OrderClose #" + IntegerToString(ticket) + " (Versuch " + IntegerToString(v) + ")", err);
         ergebnis = "OrderClose: " + FehlerText(err) + " (" + IntegerToString(err) + ")";
         if(!IsTesting())
            Sleep(200);
         if(!OrderSelect(ticket, SELECT_BY_TICKET))
            break;
         if(OrderCloseTime() != 0)      // inzwischen geschlossen (z. B. durch SL/TP)
         {
            ok = true;
            break;
         }
      }
   }
   if(!ok)
      return false;
   ergebnis = "Position #" + IntegerToString(ticket) + " geschlossen";
   if(OrderSelect(ticket, SELECT_BY_TICKET))
   {
      double pr = OrderProfit() + OrderSwap() + OrderCommission();
      ergebnis += ": " + ((pr >= 0.0) ? "+" : "") + DoubleToString(pr, 2) + " " + AccountCurrency();
   }
   Print("ScalpScout Trend Fern-Aktion: ", ergebnis);
   return true;
}

void TgZuBefehl(string arg)
{
   int ticket = 0;
   if(!TicketParsen(arg, ticket) || !EigenePositionWaehlen(ticket))
   {
      TgNachrichtSenden("⚠️ /zu TICKET: nur offene Positionen dieses EAs auf " + HtmlEscape(Symbol())
                        + ". /positionen zeigt die Tickets.", "");
      return;
   }
   double pr = OrderProfit() + OrderSwap() + OrderCommission();
   string html = "Position <b>#" + IntegerToString(ticket) + "</b> " + ((OrderType() == OP_BUY) ? "BUY " : "SELL ")
               + DoubleToString(OrderLots(), 2) + " " + HtmlEscape(Symbol()) + " (" + ((pr >= 0.0) ? "+" : "")
               + DoubleToString(pr, 2) + " " + AccountCurrency() + ") jetzt schließen?";
   g_cfgTicket[2] = ticket;
   CfgAnlegen(2, html, TgTastaturCfg("zu_" + IntegerToString(ticket), "✅ Schließen"));
}

// /sl und /tp: Kurs setzen (oder /sl TICKET be); StopLevel und Seite werden geprüft
void TgSlTpBefehl(bool istSL, string arg)
{
   string name = istSL ? "SL" : "TP";
   string a1 = arg, a2 = "";
   int sp = StringFind(arg, " ");
   if(sp > 0)
   {
      a1 = StringSubstr(arg, 0, sp);
      a2 = StringSubstr(arg, sp + 1);
      StringTrimLeft(a2);
      StringTrimRight(a2);
   }
   int ticket = 0;
   if(a2 == "" || !TicketParsen(a1, ticket) || !EigenePositionWaehlen(ticket))
   {
      TgNachrichtSenden("⚠️ /" + (istSL ? "sl TICKET PREIS|be" : "tp TICKET PREIS") + ": Ticket einer offenen Position dieses EAs und Preis angeben. "
                        + "/positionen zeigt die Tickets.", "");
      return;
   }
   RefreshRates();
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   int    typ     = OrderType();
   double offen   = OrderOpenPrice();
   double sl      = OrderStopLoss();
   double tp      = OrderTakeProfit();
   double neu     = 0.0;
   if(a2 == "be")
   {
      if(!istSL)
      {
         TgNachrichtSenden("⚠️ 'be' gilt nur für /sl.", "");
         return;
      }
      neu = (typ == OP_BUY) ? offen + BE_PufferPunkte * Point : offen - BE_PufferPunkte * Point;
   }
   else if(!ZahlParsen(a2, neu) || neu <= 0.0)
   {
      TgNachrichtSenden("⚠️ " + name + ": ungültiger Preis. Beispiel: /" + (istSL ? "sl" : "tp") + " " + IntegerToString(ticket)
                        + " " + DoubleToString(Bid, Digits), "");
      return;
   }
   neu = NormalizeDouble(neu, Digits);
   bool seiteOK;
   if(istSL)
      seiteOK = (typ == OP_BUY) ? (neu <= Bid - stopLvl) : (neu >= Ask + stopLvl);
   else
      seiteOK = (typ == OP_BUY) ? (neu >= Bid + stopLvl) : (neu <= Ask - stopLvl);
   if(!seiteOK)
   {
      TgNachrichtSenden("⚠️ " + name + " " + DoubleToString(neu, Digits) + " nicht möglich: falsche Seite oder zu nah am Kurs "
                        + "(Bid " + DoubleToString(Bid, Digits) + ", Ask " + DoubleToString(Ask, Digits)
                        + ", Mindestabstand " + DoubleToString(stopLvl, Digits) + ").", "");
      return;
   }
   double alt = istSL ? sl : tp;
   ResetLastError();
   bool ok = OrderModify(ticket, offen, istSL ? neu : sl, istSL ? tp : neu, 0, clrDodgerBlue);
   if(!ok)
   {
      int err = GetLastError();
      if(err == 1)
         TgNachrichtSenden(name + " #" + IntegerToString(ticket) + " steht schon auf " + DoubleToString(neu, Digits) + ".", "");
      else
      {
         LogFehler("OrderModify #" + IntegerToString(ticket), err);
         TgNachrichtSenden("⚠️ " + name + " #" + IntegerToString(ticket) + " nicht geändert: " + HtmlEscape(FehlerText(err))
                           + " (" + IntegerToString(err) + ")", "");
      }
      return;
   }
   FernGeaendert(name + " #" + IntegerToString(ticket), (alt > 0.0) ? DoubleToString(alt, Digits) : "keiner", DoubleToString(neu, Digits));
}

// Plan für einen Hand-Trade: SL 1.0 x ATR, TP 2.0 x ATR vom aktuellen Preis (mindestens StopLevel);
// lotWunsch 0 = Lot aus Risiko (mit MaxLot-Deckel), sonst das gewünschte Lot (Rahmen prüft der Aufrufer).
bool HandPlan(int richtung, double lotWunsch, Plan &p, string &grund)
{
   grund = "";
   RefreshRates();
   double atr = AktuelleATR();
   if(atr <= 0.0)
   {
      grund = "ATR nicht verfügbar";
      return false;
   }
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   double spread  = Ask - Bid;
   p.richtung  = richtung;
   p.atr       = atr;
   p.typ       = 0;
   p.preis     = (richtung > 0) ? Ask : Bid;
   p.spreadPkt = SpreadPunkte();
   p.kommPkt   = KommissionPunkte();
   double slDist = MathMax(1.0 * atr, stopLvl + spread + Point);
   double tpDist = MathMax(2.0 * atr, stopLvl + spread + Point);
   p.sl = NormalizeDouble((richtung > 0) ? p.preis - slDist : p.preis + slDist, Digits);
   p.tp = NormalizeDouble((richtung > 0) ? p.preis + tpDist : p.preis - tpDist, Digits);
   bool seiteOK = (richtung > 0) ? (p.sl <= Bid - stopLvl && p.tp >= Bid + stopLvl)
                                 : (p.sl >= Ask + stopLvl && p.tp <= Ask - stopLvl);
   if(!seiteOK)
   {
      grund = "SL/TP unter dem Mindestabstand des Brokers";
      return false;
   }
   p.slDist = MathAbs(p.preis - p.sl);
   p.tpDist = MathAbs(p.preis - p.tp);
   p.crv    = CrvNachKosten(p.slDist, p.tpDist);

   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double minLot    = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLotBr  = MarketInfo(Symbol(), MODE_MAXLOT);
   if(tickSize <= 0.0 || tickValue <= 0.0 || minLot <= 0.0)
   {
      grund = "Symbol-Daten (TickValue/TickSize/MinLot) fehlen";
      return false;
   }
   double lot = 0.0;
   if(lotWunsch > 0.0)
      lot = LotAbrunden(lotWunsch);
   else
   {
      double verlustProLot = p.slDist / tickSize * tickValue + KommissionProLot;
      if(verlustProLot <= 0.0)
      {
         grund = "Verlust pro Lot ungültig";
         return false;
      }
      lot = LotAbrunden(AccountEquity() * g_risiko / 100.0 / verlustProLot);
      if(lot < minLot - 1e-9)
      {
         grund = "Lot aus Risiko " + DoubleToString(g_risiko, 1) + " % kleiner als MinLot " + DoubleToString(minLot, 2)
                 + " - Lot angeben, z. B. /kauf " + DoubleToString(minLot, 2);
         return false;
      }
      if(lot > g_maxLot)
         lot = LotAbrunden(g_maxLot);
   }
   if(maxLotBr > 0.0 && lot > maxLotBr)
      lot = LotAbrunden(maxLotBr);
   if(lot < minLot - 1e-9)
   {
      grund = "Lot " + DoubleToString(lot, 2) + " < MinLot " + DoubleToString(minLot, 2);
      return false;
   }
   p.lot = lot;

   ResetLastError();
   double fm  = AccountFreeMarginCheck(Symbol(), (richtung > 0) ? OP_BUY : OP_SELL, p.lot);
   int    err = GetLastError();
   if(fm <= 0.0 || err == FEHLER_NICHT_GENUG_GELD)
   {
      if(err != 0)
         LogFehler("AccountFreeMarginCheck", err);
      grund = "Nicht genug freie Margin für " + DoubleToString(p.lot, 2) + " Lot";
      return false;
   }
   return true;
}

// Hand-Trade eröffnen: Schutzfilter ohne Zeitfenster/News, Plan mit frischen Preisen
bool HandTradeOeffnen(int richtung, double lotWunsch, string &ergebnis)
{
   ergebnis = "";
   string grund = "";
   if(!HandelErlaubt(grund, AktuelleATR(), false))
   {
      ergebnis = grund;
      return false;
   }
   int   cmd = (richtung > 0) ? OP_BUY : OP_SELL;
   color clr = (richtung > 0) ? clrLime : clrRed;
   int   slip = SlippagePunkte();
   int   max  = MathMax(1, OrderVersuche);
   for(int v = 1; v <= max; v++)
   {
      if(!IsTesting())
      {
         int warte = 0;
         while(IsTradeContextBusy() && warte < 60)
         {
            Sleep(50);
            warte++;
         }
      }
      Plan p;
      if(!HandPlan(richtung, lotWunsch, p, grund))
      {
         ergebnis = grund;
         return false;
      }
      ResetLastError();
      int ticket = OrderSend(Symbol(), cmd, p.lot, p.preis, slip, p.sl, p.tp, ORDER_KOMMENTAR, MagicNumber, 0, clr);
      if(ticket > 0)
      {
         g_orderTicket = ticket;
         g_orderPreis  = p.preis;
         if(OrderSelect(ticket, SELECT_BY_TICKET))
            g_orderPreis = OrderOpenPrice();
         g_dgTrades++;
         ergebnis = "#" + IntegerToString(ticket) + " " + ((richtung > 0) ? "BUY " : "SELL ") + DoubleToString(p.lot, 2)
                    + " @" + DoubleToString(g_orderPreis, Digits) + " SL " + DoubleToString(p.sl, Digits)
                    + " TP " + DoubleToString(p.tp, Digits);
         Print("ScalpScout Trend Fern-Aktion: Hand-Trade ", ergebnis, " (Versuch ", v, ")");
         HinweisSetzen("Hand-Trade per Telegram: " + ergebnis);
         return true;
      }
      int err = GetLastError();
      LogFehler("OrderSend Hand-Trade (Versuch " + IntegerToString(v) + "/" + IntegerToString(max) + ")", err);
      ergebnis = "OrderSend: " + FehlerText(err) + " (" + IntegerToString(err) + ")";
      bool wiederholen = (err == FEHLER_REQUOTE || err == FEHLER_PREIS_GEAENDERT ||
                          err == FEHLER_KEINE_KURSE || err == FEHLER_BROKER_BESCHAEFT ||
                          err == FEHLER_KONTEXT_BELEGT);
      if(!wiederholen)
         return false;
      if(!IsTesting())
         Sleep(200);
   }
   return false;
}

// /kauf [LOT] und /verkauf [LOT]: Vorschau mit Knöpfen (30 s)
void TgHandBefehl(int richtung, string arg)
{
   double lotWunsch = 0.0;
   if(arg != "")
   {
      double minLot = MarketInfo(Symbol(), MODE_MINLOT);
      double grenze = FernMaxLotObergrenze;
      if(minLot <= 0.0 || grenze < minLot - 1e-9)
      {
         TgNachrichtSenden("⚠️ Lot: Obergrenze " + LotText(grenze) + " liegt unter MinLot " + LotText(minLot) + ".", "");
         return;
      }
      double v = 0.0;
      if(!TgZahlArg("Lot", arg, minLot, grenze, LotText(minLot) + " bis " + LotText(grenze) + " Lot", v))
         return;
      lotWunsch = LotAbrunden(v);
      if(lotWunsch < minLot - 1e-9)
      {
         TgNachrichtSenden("⚠️ Lot: ungültiger Wert. Erlaubt: " + LotText(minLot) + " bis " + LotText(grenze) + " Lot.", "");
         return;
      }
   }
   string grund = "";
   if(!HandelErlaubt(grund, AktuelleATR(), false))
   {
      TgNachrichtSenden("⚠️ Hand-Trade nicht möglich: " + HtmlEscape(grund), "");
      return;
   }
   Plan p;
   if(!HandPlan(richtung, lotWunsch, p, grund))
   {
      TgNachrichtSenden("⚠️ Hand-Trade nicht möglich: " + HtmlEscape(grund), "");
      return;
   }
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double riskoGeld = p.slDist / tickSize * tickValue * p.lot + KommissionProLot * p.lot;
   string html = "<b>Hand-Trade " + HtmlEscape(Symbol()) + "</b>  " + ((richtung > 0) ? "🟢 KAUF" : "🔴 VERKAUF") + "\n"
               + "Einstieg ca.: " + DoubleToString(p.preis, Digits) + "\n"
               + "SL: " + DoubleToString(p.sl, Digits) + " (" + DoubleToString(p.slDist / Point, 0) + " Pkt)\n"
               + "TP: " + DoubleToString(p.tp, Digits) + " (" + DoubleToString(p.tpDist / Point, 0) + " Pkt)\n"
               + "Lot: " + LotText(p.lot) + " | Verlust bei SL ca. " + DoubleToString(riskoGeld, 2) + " " + AccountCurrency() + "\n"
               + "Kosten: " + KostenText(p.spreadPkt, p.kommPkt) + " Pkt";
   g_cfgDir[3] = richtung;
   g_cfgLot[3] = lotWunsch;
   CfgAnlegen(3, html, TgTastaturCfg("hand", "✅ Ausführen"));
}

// Tagesbericht: heutige Trades, Konto, offene Positionen, Fern-Einstellungen
string BerichtText()
{
   string cur = AccountCurrency();
   string fl  = FernListe();
   return "<b>Tagesbericht " + HtmlEscape(Symbol()) + "</b> (" + TimeToString(TimeCurrent(), TIME_DATE) + ")\n"
        + TgHeuteText() + "\n"
        + "Kontostand: " + DoubleToString(AccountBalance(), 2) + " | Equity " + DoubleToString(AccountEquity(), 2) + " " + cur + "\n"
        + "Offene Positionen: " + IntegerToString(ZaehlePositionen()) + " (" + DoubleToString(OffenerGewinn(), 2) + " " + cur + ")\n"
        + "Fern-Einstellungen: " + ((fl != "") ? HtmlEscape(fl) : "keine (Inputs gelten)");
}

// In OnTimer: einmal pro Serverzeit-Tag ab der eingestellten Zeit senden
void BerichtPruefen()
{
   if(g_berichtMin < 0 || !TgBereit())
      return;
   datetime zt    = TimeCurrent();
   datetime heute = (datetime)((long)zt / 86400 * 86400);
   if(g_berichtTag == heute)
      return;
   if(TimeHour(zt) * 60 + TimeMinute(zt) < g_berichtMin)
      return;
   if(TgNachrichtSenden(BerichtText(), "") > 0)
      g_berichtTag = heute;
}

void TgBerichtBefehl(string arg)
{
   if(arg == "")
   {
      TgNachrichtSenden(BerichtText(), "");
      return;
   }
   int neu = -1;
   if(arg != "aus" && arg != "off")
   {
      neu = ParseHHMM(arg);
      if(neu < 0)
      {
         TgNachrichtSenden("⚠️ Tagesbericht: Format HH:MM (Serverzeit) oder aus. Jetzt: " + BerichtZeitText()
                           + ". /bericht ohne Angabe sendet ihn sofort.", "");
         return;
      }
   }
   string alt = BerichtZeitText();
   g_berichtMin = neu;
   FernSetzen("bericht", (double)neu);
   BerichtNeuAnsetzen();
   FernGeaendert("Tagesbericht", alt, BerichtZeitText());
}

// Textbefehle aus dem Chat (siehe /hilfe)
void TgBefehl(string text)
{
   string t = text;
   StringReplace(t, "\n", " ");
   StringReplace(t, "\r", " ");
   StringReplace(t, "\t", " ");
   StringTrimLeft(t);
   StringTrimRight(t);
   if(StringGetCharacter(t, 0) != 47)      // 47 = '/'
      return;
   StringToLower(t);
   string cmd = t;
   string arg = "";
   int sp = StringFind(t, " ");
   if(sp > 0)
   {
      cmd = StringSubstr(t, 0, sp);
      arg = StringSubstr(t, sp + 1);
   }
   StringTrimLeft(arg);
   StringTrimRight(arg);
   int at = StringFind(cmd, "@");          // "/status@MeinBot"
   if(at > 0)
      cmd = StringSubstr(cmd, 0, at);

   if(cmd == "/status")
      TgNachrichtSenden(TgStatusText(), "");
   else if(cmd == "/hilfe" || cmd == "/help")
      TgNachrichtSenden(TgHilfeText(), "");
   else if(cmd == "/diag")
      TgNachrichtSenden(TgDiagText(), "");
   else if(cmd == "/positionen")
      TgNachrichtSenden(TgPositionenText(), "");
   else if(cmd == "/heute")
      TgNachrichtSenden(TgHeuteText(), "");
   else if(cmd == "/schliessen" || cmd == "/schließen")
      TgSchliessenBefehl();
   else if(cmd == "/stop")
   {
      g_tgPause = true;
      HinweisSetzen("Pausiert per Telegram");
      TgNachrichtSenden("⏸ Pausiert: neue Signale werden blockiert. /start hebt die Pause auf.", "");
   }
   else if(cmd == "/start")
   {
      g_tgPause = false;
      string zusatz = "";
      if(g_gestoppt && g_stopTg)
      {
         g_gestoppt = false;
         g_stopTg   = false;
         zusatz     = " Die Sperre nach /schliessen ist ebenfalls aufgehoben.";
      }
      HinweisSetzen("Pause per Telegram aufgehoben");
      TgNachrichtSenden("▶️ Pause aufgehoben: neue Signale sind wieder erlaubt." + zusatz, "");
   }
   else if(cmd == "/zu")
      TgZuBefehl(arg);
   else if(cmd == "/sl")
      TgSlTpBefehl(true, arg);
   else if(cmd == "/tp")
      TgSlTpBefehl(false, arg);
   else if(cmd == "/kauf")
      TgHandBefehl(1, arg);
   else if(cmd == "/verkauf")
      TgHandBefehl(-1, arg);
   else if(cmd == "/be")
      TgSchalterBefehl("Break-even", arg, "be", g_beAktiv);
   else if(cmd == "/trailing")
      TgSchalterBefehl("Trailing", arg, "trail", g_trailAktiv);
   else if(cmd == "/bericht")
      TgBerichtBefehl(arg);
   else if(cmd == "/modus")
      TgModusBefehl(arg);
   else if(cmd == "/risiko")
      TgRisikoBefehl(arg);
   else if(cmd == "/maxlot")
      TgMaxLotBefehl(arg);
   else if(cmd == "/limit")
      TgLimitBefehl(arg);
   else if(cmd == "/zeit")
      TgZeitBefehl(arg);
   else if(cmd == "/crv")
      TgCrvBefehl(arg);
   else if(cmd == "/news")
      TgNewsBefehl(arg);
   else if(cmd == "/vwap")
      TgSchalterBefehl("VWAP-Pflicht", arg, "vwap", g_vwapPflicht);
   else if(cmd == "/lunte")
      TgSchalterBefehl("Doppellunte", arg, "lunte", g_doppelLunte);
   else if(cmd == "/m5")
      TgSchalterBefehl("M5-Filter", arg, "m5", g_m5Filter);
   else if(cmd == "/reset")
   {
      FernZuruecksetzen();
      Print("ScalpScout Trend Fern-Änderung: alle Fern-Einstellungen gelöscht, Inputs gelten wieder");
      TgNachrichtSenden("♻️ Fern-Einstellungen gelöscht: die Inputs gelten wieder.\nModus: " + ModusText() + " | Risiko "
                        + Zahl(g_risiko, 2) + " % | MaxLot " + LotText(g_maxLot) + " | MinCRV " + Zahl(g_minCRV, 2), "");
      UiAktualisieren();
   }
   else
      TgNachrichtSenden("Unbekannter Befehl " + HtmlEscape(cmd) + ". /hilfe zeigt alle Befehle.", "");
}

// Ein einzelnes Update (Abschnitt ab "update_id") auswerten
void TgUpdateBehandeln(string seg)
{
   int pc = StringFind(seg, "\"callback_query\":");
   if(pc >= 0)
   {
      string cbId = "", data = "";
      if(!JsonText(seg, "id", pc, cbId) || !JsonText(seg, "data", pc, data))
         return;
      long chat = 0;
      int  pch  = StringFind(seg, "\"chat\":{", pc);
      bool hatChat = (pch >= 0 && JsonZahl(seg, "id", pch, chat));
      if(!hatChat)
      {
         int pf = StringFind(seg, "\"from\":{", pc);
         hatChat = (pf >= 0 && JsonZahl(seg, "id", pf, chat));
      }
      if(!hatChat || IntegerToString(chat) != g_tgChat)
      {
         Print("ScalpScout Trend Telegram: Knopfdruck aus fremdem Chat ignoriert.");
         return;
      }

      if(StringFind(data, "cfg_") == 0)       // Rückfrage-Knöpfe (Vollautomatik, Alle schließen)
      {
         long cbMsg = 0;
         int  pmsg  = StringFind(seg, "\"message\":{", pc);
         if(pmsg >= 0)
            JsonZahl(seg, "message_id", pmsg, cbMsg);
         TgCfgCallback(cbId, data, cbMsg);
         return;
      }

      int us = StringFind(data, "_");
      if(us < 0)
         return;
      string aktion = StringSubstr(data, 0, us);
      int    sid    = (int)StringToInteger(StringSubstr(data, us + 1));
      if(!g_sig.aktiv || sid != g_sigId)
      {
         TgCallbackAntwort(cbId, "Signal abgelaufen");
         return;
      }

      if(aktion == "ja")
      {
         string erg   = "";
         string kopf  = g_tgKopf;
         long   msgId = g_sigMsgId;
         bool   ok    = SignalAusfuehren(true, erg);
         TgCallbackAntwort(cbId, ok ? "ausgeführt" : "nicht ausgeführt");
         if(msgId > 0)
            TgNachrichtBearbeiten(msgId, kopf + "\n" + (ok ? "✅ ausgeführt: " + erg
                                                         : "⚠️ nicht ausgeführt: " + HtmlEscape(erg)));
         UiAktualisieren();
      }
      else if(aktion == "nein")
      {
         TgCallbackAntwort(cbId, "verworfen");
         SignalVerwerfen("per Telegram verworfen", "❌ verworfen");
         HinweisSetzen("Signal verworfen (Telegram)");
         UiAktualisieren();
      }
      return;
   }

   int pm = StringFind(seg, "\"message\":{");
   if(pm >= 0)
   {
      long chat = 0;
      int  pch  = StringFind(seg, "\"chat\":{", pm);
      if(pch < 0 || !JsonZahl(seg, "id", pch, chat))
         return;
      if(IntegerToString(chat) != g_tgChat)
      {
         Print("ScalpScout Trend Telegram: Nachricht aus fremdem Chat ignoriert.");
         return;
      }
      string text = "";
      if(JsonText(seg, "text", pch, text))
         TgBefehl(text);
   }
}

// Antwort von getUpdates in einzelne Updates zerlegen und abarbeiten
void TgUpdatesVerarbeiten(string antwort)
{
   string marke = "\"update_id\":";
   int pos = StringFind(antwort, marke);
   while(pos >= 0)
   {
      int naechst = StringFind(antwort, marke, pos + StringLen(marke));
      string seg  = (naechst >= 0) ? StringSubstr(antwort, pos, naechst - pos) : StringSubstr(antwort, pos);
      long uid = 0;
      if(JsonZahl(seg, "update_id", 0, uid) && uid + 1 > g_tgOffset)
         g_tgOffset = uid + 1;          // zuerst bestätigen, dann behandeln (kein doppeltes Ausführen)
      TgUpdateBehandeln(seg);
      pos = naechst;
   }
}

// In OnTimer: alle TelegramAbfrageSek Sekunden neue Updates holen
void TgAbfragen()
{
   if(!TgBereit())
      return;
   datetime jetzt = TimeLocal();
   if(jetzt - g_tgLetzteAbfrage < MathMax(1, TelegramAbfrageSek))
      return;
   g_tgLetzteAbfrage = jetzt;

   string body = "{\"offset\":" + IntegerToString(g_tgOffset)
                 + ",\"timeout\":0,\"allowed_updates\":[\"callback_query\",\"message\"]}";
   string antwort = "";
   if(!TgAnfrage("getUpdates", body, antwort))
      return;
   TgUpdatesVerarbeiten(antwort);
}

// Meldung "Position #x geschlossen" für die aktuell selektierte (geschlossene) Order
void TgSchliessungMelden()
{
   int    ticket = OrderTicket();
   double profit = OrderProfit() + OrderSwap() + OrderCommission();
   double cp     = OrderClosePrice();
   double sl     = OrderStopLoss();
   double tp     = OrderTakeProfit();
   string kom    = OrderComment();
   StringToLower(kom);
   double tol    = 2.0 * Point;

   string grund = "manuell";
   if(StringFind(kom, "[tp]") >= 0)
      grund = "TP";
   else if(StringFind(kom, "[sl]") >= 0)
      grund = "SL";
   else if(tp > 0.0 && MathAbs(cp - tp) <= tol)
      grund = "TP";
   else if(sl > 0.0 && MathAbs(cp - sl) <= tol)
      grund = "SL";

   TgNachrichtSenden("<b>" + HtmlEscape(Symbol()) + "</b> Position #" + IntegerToString(ticket) + " geschlossen: "
                     + ((profit >= 0.0) ? "+" : "") + DoubleToString(profit, 2) + " " + AccountCurrency()
                     + " (" + grund + ")", "");
}

// Aktuell offene eigene Tickets merken (beim Start)
void TgOffenMerken()
{
   ArrayResize(g_tgOffen, 0);
   ArrayResize(g_tgVersuche, 0);
   int nn = 0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber || OrderType() > OP_SELL)
         continue;
      ArrayResize(g_tgOffen, nn + 1);
      ArrayResize(g_tgVersuche, nn + 1);
      g_tgOffen[nn]    = OrderTicket();
      g_tgVersuche[nn] = 0;
      nn++;
   }
}

// In OnTimer: neu geschlossene eigene Positionen erkennen und melden
void TgSchliessungenPruefen()
{
   if(!TelegramMeldeSchliessung || !TgBereit())
      return;

   int neu[];
   int neuV[];
   int nn = 0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber || OrderType() > OP_SELL)
         continue;
      ArrayResize(neu, nn + 1);
      ArrayResize(neuV, nn + 1);
      neu[nn]  = OrderTicket();
      neuV[nn] = 0;
      nn++;
   }

   int alt = ArraySize(g_tgOffen);
   for(int k = 0; k < alt; k++)
   {
      int  t = g_tgOffen[k];
      bool nochOffen = false;
      for(int j = 0; j < nn; j++)
      {
         if(neu[j] == t)
         {
            nochOffen = true;
            break;
         }
      }
      if(nochOffen)
         continue;
      if(OrderSelect(t, SELECT_BY_TICKET) && OrderCloseTime() > 0)
         TgSchliessungMelden();
      else if(g_tgVersuche[k] < 30)      // Historie evtl. noch nicht aktuell: später erneut suchen
      {
         ArrayResize(neu, nn + 1);
         ArrayResize(neuV, nn + 1);
         neu[nn]  = t;
         neuV[nn] = g_tgVersuche[k] + 1;
         nn++;
      }
   }

   ArrayResize(g_tgOffen, nn);
   ArrayResize(g_tgVersuche, nn);
   for(int m = 0; m < nn; m++)
   {
      g_tgOffen[m]    = neu[m];
      g_tgVersuche[m] = neuV[m];
   }
}

// In OnInit: Telegram prüfen, alte Updates überspringen, Begrüßung senden
void TelegramStarten()
{
   g_tgAktiv     = false;
   g_tgGesperrt  = false;
   g_tgVerbunden = false;
   g_tgFehler    = 0;
   g_tgOffset    = 0;
   g_tgSperreBis = 0;
   g_tgLetzteAbfrage = TimeLocal();
   ArrayResize(g_tgOffen, 0);
   ArrayResize(g_tgVersuche, 0);

   if(!TelegramAktiv || IsTesting())
      return;
   g_tgToken = TelegramToken;
   g_tgChat  = TelegramChatID;
   StringTrimLeft(g_tgToken);
   StringTrimRight(g_tgToken);
   StringTrimLeft(g_tgChat);
   StringTrimRight(g_tgChat);
   if(g_tgToken == "" || g_tgChat == "")
   {
      Print("ScalpScout Trend Telegram: Token oder Chat-ID fehlt - Telegram bleibt aus.");
      return;
   }
   g_tgAktiv = true;

   // Alte Updates überspringen: nur das letzte holen und dahinter weiterlesen
   string antwort = "";
   if(TgAnfrage("getUpdates", "{\"offset\":-1,\"timeout\":0,\"allowed_updates\":[\"callback_query\",\"message\"]}", antwort))
   {
      int p = StringFind(antwort, "\"update_id\":");
      long uid = 0;
      if(p >= 0 && JsonZahl(antwort, "update_id", p, uid))
         g_tgOffset = uid + 1;
   }
   TgOffenMerken();
   string gruss = "ScalpScout Trend auf <b>" + HtmlEscape(Symbol()) + "</b> gestartet (Modus " + ModusText() + ")\nBefehle: /hilfe";
   string fernTxt = FernListe();
   if(fernTxt != "")
      gruss += "\nFern-Einstellungen aktiv: " + HtmlEscape(fernTxt);
   TgNachrichtSenden(gruss, "");
}

//+------------------------------------------------------------------+
//| Strategie Trend-Pullback (AVWAP)                                 |
//+------------------------------------------------------------------+
// Läuft nur auf geschlossenen Kerzen (Shift 1) und einmal pro neuer M1-Kerze.

double UntereLunte(int s)
{
   return MathMin(iOpen(Symbol(), PERIOD_M1, s), iClose(Symbol(), PERIOD_M1, s)) - iLow(Symbol(), PERIOD_M1, s);
}

double ObereLunte(int s)
{
   return iHigh(Symbol(), PERIOD_M1, s) - MathMax(iOpen(Symbol(), PERIOD_M1, s), iClose(Symbol(), PERIOD_M1, s));
}

double KerzenKoerper(int s)
{
   return MathAbs(iClose(Symbol(), PERIOD_M1, s) - iOpen(Symbol(), PERIOD_M1, s));
}

// Schritt 1: bestätigte Swing-Hochs/-Tiefs (neueste zuerst) mit Preis und Shift
void SwingsSuchen()
{
   g_swHN = 0;
   g_swLN = 0;
   int n   = SwingStaerke;
   int anz = MathMin(SwingLookback + n + 1, iBars(Symbol(), PERIOD_M1));
   g_anzKerzen = anz;
   if(n < 1 || anz < 2 * n + 3)
      return;

   double hi[], lo[];
   ArrayResize(hi, anz);
   ArrayResize(lo, anz);
   for(int s = 0; s < anz; s++)
   {
      hi[s] = iHigh(Symbol(), PERIOD_M1, s);
      lo[s] = iLow(Symbol(), PERIOD_M1, s);
   }
   ArrayResize(g_swHP, anz);
   ArrayResize(g_swHB, anz);
   ArrayResize(g_swLP, anz);
   ArrayResize(g_swLB, anz);

   // Pivot bei i: Nachbarn i-n..i-1 (jünger, mindestens Shift 1) und i+1..i+n (älter) müssen existieren
   int bis = MathMin(SwingLookback, anz - 1 - n);
   for(int i = n + 1; i <= bis; i++)
   {
      bool ph = true;
      bool pl = true;
      for(int k = 1; k <= n; k++)
      {
         if(hi[i] <= hi[i - k] || hi[i] <= hi[i + k]) ph = false;
         if(lo[i] >= lo[i - k] || lo[i] >= lo[i + k]) pl = false;
         if(!ph && !pl)
            break;
      }
      if(ph)
      {
         g_swHP[g_swHN] = hi[i];
         g_swHB[g_swHN] = i;
         g_swHN++;
      }
      if(pl)
      {
         g_swLP[g_swLN] = lo[i];
         g_swLB[g_swLN] = i;
         g_swLN++;
      }
   }
}

// Schritt 2/3: Trend (+1/-1/0) und Ankerkerze (Beginn der Kette steigender Tiefs bzw. fallender Hochs)
int TrendBestimmen()
{
   g_trend      = 0;
   g_ankerShift = -1;
   bool auf = false;
   bool ab  = false;
   if(g_swLN >= 2 && g_swLP[0] > g_swLP[1])
   {
      auf = true;
      if(!TrendNurTiefs)
         auf = (g_swHN >= 2 && g_swHP[0] > g_swHP[1]);
   }
   if(g_swHN >= 2 && g_swHP[0] < g_swHP[1])
   {
      ab = true;
      if(!TrendNurTiefs)
         ab = (g_swLN >= 2 && g_swLP[0] < g_swLP[1]);
   }
   if(auf == ab)      // weder noch oder widersprüchlich -> seitwärts
      return 0;
   if(auf)
   {
      int k = 0;
      while(k + 1 < g_swLN && g_swLP[k] > g_swLP[k + 1])
         k++;
      g_ankerShift = g_swLB[k];
      g_trend = 1;
   }
   else
   {
      int k = 0;
      while(k + 1 < g_swHN && g_swHP[k] < g_swHP[k + 1])
         k++;
      g_ankerShift = g_swHB[k];
      g_trend = -1;
   }
   return g_trend;
}

// Schritt 3: AVWAP = Summe(typischer Preis * Tick-Volumen) / Summe(Tick-Volumen) ab Anker bis Shift 1
bool AvwapBerechnen(int anker)
{
   g_avwap = 0.0;
   if(anker < 1 || anker >= g_anzKerzen)
      return false;
   ArrayResize(g_avwapReihe, g_anzKerzen);
   double sumPV = 0.0;
   double sumV  = 0.0;
   for(int s = anker; s >= 1; s--)
   {
      double typ = (iHigh(Symbol(), PERIOD_M1, s) + iLow(Symbol(), PERIOD_M1, s) + iClose(Symbol(), PERIOD_M1, s)) / 3.0;
      double v   = (double)iVolume(Symbol(), PERIOD_M1, s);
      if(v < 1.0)
         v = 1.0;                       // Sicherung gegen Division durch null
      sumPV += typ * v;
      sumV  += v;
      g_avwapReihe[s] = sumPV / sumV;
   }
   g_avwap = g_avwapReihe[1];
   return (g_avwap > 0.0);
}

// AVWAP als Reihe von OBJ_TREND-Segmenten (max. 200 Kerzen); nur bei neuer Kerze aufgerufen
void AvwapZeichnen()
{
   if(!g_ui)
      return;
   ObjectsDeleteAll(0, PRAEFIX + "avwap_");
   if(g_trend != 0 && g_avwap > 0.0 && g_ankerShift >= 2)
   {
      int von = MathMin(g_ankerShift, 200);
      for(int s = von; s >= 2; s--)
      {
         string name = PRAEFIX + "avwap_" + IntegerToString(s);
         if(ObjectCreate(0, name, OBJ_TREND, 0, iTime(Symbol(), PERIOD_M1, s), g_avwapReihe[s],
                         iTime(Symbol(), PERIOD_M1, s - 1), g_avwapReihe[s - 1]))
         {
            ObjectSetInteger(0, name, OBJPROP_RAY, false);
            ObjectSetInteger(0, name, OBJPROP_COLOR, clrGold);
            ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
            ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
            ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
         }
      }
   }
   ChartRedraw(0);
}

// Nächstes Swing-Hoch über (Long) bzw. Swing-Tief unter (Short) dem Referenzpreis; 0 = keins
double ZielSuchen(int richtung, double ref)
{
   double best = 0.0;
   if(ref <= 0.0)
      return 0.0;
   if(richtung > 0)
   {
      for(int i = 0; i < g_swHN; i++)
         if(g_swHP[i] > ref && (best == 0.0 || g_swHP[i] < best))
            best = g_swHP[i];
   }
   else
   {
      for(int j = 0; j < g_swLN; j++)
         if(g_swLP[j] < ref && (best == 0.0 || g_swLP[j] > best))
            best = g_swLP[j];
   }
   return best;
}

// Schritt 4: Bruch-Sperre. true = gesperrt.
// Long: letztes Swing-Hoch wurde danach überschritten und seitdem ist noch kein neues Swing-Tief bestätigt.
bool BruchGesperrt(int richtung)
{
   if(richtung > 0)
   {
      if(g_swHN < 1)
         return false;
      double sw = g_swHP[0];
      int bruch = -1;
      for(int s = g_swHB[0] - 1; s >= 1; s--)        // vom ältesten zum jüngsten: erster Bruch
      {
         if(iHigh(Symbol(), PERIOD_M1, s) > sw)
         {
            bruch = s;
            break;
         }
      }
      if(bruch < 0)
         return false;
      if(g_swLN > 0 && g_swLB[0] < bruch)           // neues Tief nach dem Bruch bestätigt
         return false;
      return true;
   }
   if(g_swLN < 1)
      return false;
   double sw2 = g_swLP[0];
   int bruch2 = -1;
   for(int s2 = g_swLB[0] - 1; s2 >= 1; s2--)
   {
      if(iLow(Symbol(), PERIOD_M1, s2) < sw2)
      {
         bruch2 = s2;
         break;
      }
   }
   if(bruch2 < 0)
      return false;
   if(g_swHN > 0 && g_swHB[0] < bruch2)             // neues Hoch nach dem Bruch bestätigt
      return false;
   return true;
}

// Schritte 1-9 auf der geschlossenen Kerze. Rückgabe +1 Long, -1 Short, 0 kein Signal.
// Bei Signal: slOut/tpOut = absolute Preise, typOut = 1 Farbwechsel / 2 Doppellunte, crvOut = CRV nach Kosten.
int PullbackPruefen(double &atr, double &slOut, double &tpOut, int &typOut, double &crvOut)
{
   atr = 0.0;
   slOut = 0.0;
   tpOut = 0.0;
   typOut = 0;
   crvOut = 0.0;
   g_trend = 0;
   g_avwap = 0.0;
   g_ziel  = 0.0;
   g_ankerShift = -1;
   g_swHN = 0;
   g_swLN = 0;

   DiagReset();
   if(iBars(Symbol(), PERIOD_M1) < 2 * SwingStaerke + MathMax(ATR_Periode, 3) + 5)
   {
      g_stratGrund = "Zu wenig Historie";
      return 0;
   }
   atr = AktuelleATR();
   if(atr <= 0.0)
   {
      g_stratGrund = "ATR nicht verfügbar";
      return 0;
   }
   RefreshRates();

   SwingsSuchen();
   int r = TrendBestimmen();
   if(r == 0)
   {
      g_stratGrund = "Kein Trend";
      return 0;
   }
   g_ziel = ZielSuchen(r, (r > 0) ? Ask : Bid);
   if(!AvwapBerechnen(g_ankerShift))
   {
      g_stratGrund = "AVWAP nicht berechenbar";
      return 0;
   }

   // "Herauszoomen": M5-Filter
   if(g_m5Filter)
   {
      if(iBars(Symbol(), PERIOD_M5) < M5_EMA_Periode * 2)
      {
         g_stratGrund = "M5-Daten fehlen";
         return 0;
      }
      double ema5 = iMA(Symbol(), PERIOD_M5, M5_EMA_Periode, 0, MODE_EMA, PRICE_CLOSE, 1);
      double c5   = iClose(Symbol(), PERIOD_M5, 1);
      if(ema5 <= 0.0 || c5 <= 0.0)
      {
         g_stratGrund = "M5-Daten fehlen";
         return 0;
      }
      g_dgM5Close = c5;
      g_dgM5Ema   = ema5;
      g_dgM5      = ((r > 0 && c5 <= ema5) || (r < 0 && c5 >= ema5)) ? 0 : 1;
      if((r > 0 && c5 <= ema5) || (r < 0 && c5 >= ema5))
      {
         g_stratGrund = (r > 0) ? "M5-Filter: Close unter EMA, kein Long" : "M5-Filter: Close über EMA, kein Short";
         return 0;
      }
   }

   if(BruchSperreAktiv)
      g_dgBruch = BruchGesperrt(r) ? 1 : 0;
   if(BruchSperreAktiv && g_dgBruch == 1)
   {
      g_stratGrund = (r > 0) ? "Hoch gebrochen – warte auf höheres Tief" : "Tief gebrochen – warte auf tieferes Hoch";
      return 0;
   }

   // Einstiegsmuster
   double o1 = iOpen(Symbol(), PERIOD_M1, 1);
   double c1 = iClose(Symbol(), PERIOD_M1, 1);
   double o2 = iOpen(Symbol(), PERIOD_M1, 2);
   double c2 = iClose(Symbol(), PERIOD_M1, 2);
   double nahe = VWAP_NaeheATR * atr;
   double tol  = DoppelLunteToleranzATR * atr;
   int    typ  = 0;
   double ext  = 0.0;        // Formationsextrem (Long: tiefstes Tief, Short: höchstes Hoch)
   bool   vwapFehlt = false;
   if(g_tgAktiv)
      DiagMuster(r, nahe, tol);              // nur Anzeige für /diag, ändert die Signal-Logik nicht

   if(r > 0)
   {
      double l1 = iLow(Symbol(), PERIOD_M1, 1);
      double l2 = iLow(Symbol(), PERIOD_M1, 2);
      double l3 = iLow(Symbol(), PERIOD_M1, 3);
      if(c2 < o2 && c1 > o1 && c1 > g_avwap)                          // a) Farbwechsel rot -> grün
      {
         double e = MathMin(l1, l2);
         if(!g_vwapPflicht || e <= g_avwap + nahe)
         {
            typ = 1;
            ext = e;
         }
         else
            vwapFehlt = true;
      }
      if(typ == 0 && g_doppelLunte && c1 > o1)                       // b) Doppellunte
      {
         bool paar = false;
         for(int a = 1; a <= 2 && !paar; a++)
            for(int b = a + 1; b <= 3 && !paar; b++)
               if(MathAbs(iLow(Symbol(), PERIOD_M1, a) - iLow(Symbol(), PERIOD_M1, b)) <= tol &&
                  UntereLunte(a) > KerzenKoerper(a) && UntereLunte(b) > KerzenKoerper(b))
                  paar = true;
         if(paar)
         {
            double e2 = MathMin(l1, MathMin(l2, l3));
            if(!g_vwapPflicht || e2 <= g_avwap + nahe)
            {
               typ = 2;
               ext = e2;
            }
            else
               vwapFehlt = true;
         }
      }
   }
   else
   {
      double h1 = iHigh(Symbol(), PERIOD_M1, 1);
      double h2 = iHigh(Symbol(), PERIOD_M1, 2);
      double h3 = iHigh(Symbol(), PERIOD_M1, 3);
      if(c2 > o2 && c1 < o1 && c1 < g_avwap)                          // a) Farbwechsel grün -> rot
      {
         double e = MathMax(h1, h2);
         if(!g_vwapPflicht || e >= g_avwap - nahe)
         {
            typ = 1;
            ext = e;
         }
         else
            vwapFehlt = true;
      }
      if(typ == 0 && g_doppelLunte && c1 < o1)                       // b) Doppellunte (obere Lunten)
      {
         bool paar = false;
         for(int a = 1; a <= 2 && !paar; a++)
            for(int b = a + 1; b <= 3 && !paar; b++)
               if(MathAbs(iHigh(Symbol(), PERIOD_M1, a) - iHigh(Symbol(), PERIOD_M1, b)) <= tol &&
                  ObereLunte(a) > KerzenKoerper(a) && ObereLunte(b) > KerzenKoerper(b))
                  paar = true;
         if(paar)
         {
            double e2 = MathMax(h1, MathMax(h2, h3));
            if(!g_vwapPflicht || e2 >= g_avwap - nahe)
            {
               typ = 2;
               ext = e2;
            }
            else
               vwapFehlt = true;
         }
      }
   }
   if(typ == 0)
   {
      g_stratGrund = vwapFehlt ? "AVWAP nicht berührt" : "Kein Einstiegsmuster";
      return 0;
   }

   // SL (Short: plus Spread, da am Ask ausgelöst) und TP (nächstes Swing-Ziel mit Puffer)
   double spread = Ask - Bid;
   double sl, tp, slDist, tpDist;
   if(g_ziel <= 0.0)
   {
      g_stratGrund = (r > 0) ? "Kein Ziel oberhalb" : "Kein Ziel unterhalb";
      return 0;
   }
   if(r > 0)
   {
      sl = ext - SL_PufferATR * atr;
      tp = g_ziel - TP_PufferATR * atr;
      slDist = Ask - sl;
      tpDist = tp - Ask;
   }
   else
   {
      sl = ext + SL_PufferATR * atr + spread;
      tp = g_ziel + TP_PufferATR * atr;
      slDist = sl - Bid;
      tpDist = Bid - tp;
   }
   sl = NormalizeDouble(sl, Digits);
   tp = NormalizeDouble(tp, Digits);
   g_dgSL = sl;
   g_dgTP = tp;
   if(slDist <= 0.0 || tpDist <= 0.0)
   {
      g_stratGrund = "Ziel zu nah / SL ungültig";
      return 0;
   }

   // Schritt 8: CRV nach Kosten
   double crv = CrvNachKosten(slDist, tpDist);
   g_dgCRV         = crv;
   g_dgCrvGeprueft = true;
   if(crv < g_minCRV)
   {
      g_stratGrund = "CRV " + DoubleToString(crv, 1) + " < MinCRV " + DoubleToString(g_minCRV, 1);
      return 0;
   }

   // Schritt 9: Mindestabstände (StopLevel)
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   bool lvlOK = (r > 0) ? (sl <= Bid - stopLvl && tp >= Bid + stopLvl)
                        : (sl >= Ask + stopLvl && tp <= Ask - stopLvl);
   if(!lvlOK)
   {
      g_stratGrund = "Mindestabstand (StopLevel) unterschritten";
      return 0;
   }

   slOut  = sl;
   tpOut  = tp;
   typOut = typ;
   crvOut = crv;
   g_stratGrund = "Signal " + ((r > 0) ? "LONG" : "SHORT") + " (" + TypText(typ) + ")";
   return r;
}

// Rahmen: Prüfung + AVWAP-Linie im Chart (nur einmal pro neuer Kerze)
int PullbackErkennen(double &atr, double &slOut, double &tpOut, int &typOut, double &crvOut)
{
   int r = PullbackPruefen(atr, slOut, tpOut, typOut, crvOut);
   DiagSpeichern(r, atr);
   AvwapZeichnen();
   return r;
}

void NeueKerzeAuswerten()
{
   double atr = 0.0;
   double slF = 0.0;
   double tpF = 0.0;
   double crvF = 0.0;
   int    typF = 0;
   int sig = PullbackErkennen(atr, slF, tpF, typF, crvF);
   g_dgKerzen++;
   if(sig == 0)
   {
      if(g_tgAktiv)
         HistZaehlen(g_ksKey, g_ksText, g_ksAnz, g_ksN, g_ksGes, g_stratGrund);
      return;
   }
   g_dgSignale++;

   string txt = (sig > 0) ? "LONG" : "SHORT";
   string grund;

   if(!HandelErlaubt(grund, atr))
   {
      HinweisSetzen("Signal " + txt + " blockiert: " + grund);
      DiagVerworfen(grund);
      g_dgEnde += " - nicht gehandelt: " + grund;
      return;
   }

   Plan p;
   if(!BerechnePlan(sig, atr, p, grund, slF, tpF, typF))
   {
      HinweisSetzen("Signal " + txt + " ohne Trade: " + grund);
      DiagVerworfen(grund);
      g_dgEnde += " - nicht gehandelt: " + grund;
      return;
   }

   string meldung = "ScalpScout Trend " + Symbol() + " " + txt + " (" + TypText(p.typ) + ") @" + DoubleToString(p.preis, Digits)
                    + " SL " + DoubleToString(p.sl, Digits) + " TP " + DoubleToString(p.tp, Digits)
                    + " Lot " + DoubleToString(p.lot, 2) + " " + KostenText(p.spreadPkt, p.kommPkt)
                    + " CRV nach Kosten 1:" + DoubleToString(p.crv, 2);

   switch(g_modus)
   {
      case NUR_SIGNALE:
         Melden(meldung + " (nur Signal)");
         HinweisSetzen("Signal " + txt + " gemeldet (kein Trade)");
         TgNachrichtSenden(TgSignalText(p) + "\nnur Signal, kein Trade", "");
         break;

      case VOLLAUTOMATIK:
         if(OrderOeffnen(sig, atr, grund, slF, tpF))
         {
            Melden(meldung + " - ausgeführt");
            HinweisSetzen("Auto-Trade " + txt + " eröffnet");
            TgNachrichtSenden(TgSignalText(p) + "\n✅ automatisch ausgeführt: #" + IntegerToString(g_orderTicket)
                              + " @" + DoubleToString(g_orderPreis, Digits), "");
         }
         else
         {
            HinweisSetzen("Auto-Trade " + txt + " fehlgeschlagen: " + grund);
            DiagVerworfen(grund);
            g_dgEnde += " - nicht gehandelt: " + grund;
         }
         break;

      case MANUELLE_FREIGABE:
         if(g_sig.aktiv)
            SignalVerwerfen("durch neues Signal ersetzt", "⌛ ersetzt durch neues Signal");
         g_sig.aktiv = true;
         g_sig.zeit  = TimeLocal();
         g_sig.plan  = p;
         g_sigId     = TgNeueSignalId();
         g_sigMsgId  = 0;
         g_tgKopf    = TgSignalKopf(p);
         PanelZeigen();
         Melden(meldung + " - Freigabe im Chart nötig (" + IntegerToString(SignalGueltigSek) + " s)");
         g_sigMsgId  = TgNachrichtSenden(TgSignalText(p) + "\n⏱ gültig " + IntegerToString(SignalGueltigSek) + " s",
                                         TgTastatur(g_sigId));
         break;
   }
}

//+------------------------------------------------------------------+
//| Expert-Funktionen                                                |
//+------------------------------------------------------------------+
int OnInit()
{
   // Eingaben prüfen
   g_startMin = ParseHHMM(HandelStart);
   g_endeMin  = ParseHHMM(HandelEnde);
   if(g_startMin < 0 || g_endeMin < 0)
   {
      Alert("ScalpScout Trend: HandelStart/HandelEnde müssen das Format HH:MM haben (z. B. 08:00).");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(ATR_Periode < 1 || SwingStaerke < 1 || SwingLookback < 2 * SwingStaerke + 10 || M5_EMA_Periode < 1 ||
      VWAP_NaeheATR < 0.0 || DoppelLunteToleranzATR < 0.0 || SL_PufferATR < 0.0 || TP_PufferATR < 0.0 ||
      MinCRV <= 0.0 || RisikoProzent <= 0.0 || MaxLot <= 0.0 || MaxOffenePositionen < 1 || SignalGueltigSek < 1 ||
      KommissionProLot < 0.0 || FernMaxLotObergrenze < 0.0)
   {
      Alert("ScalpScout Trend: Ungültige Eingabewerte (Perioden, SwingStaerke >= 1, SwingLookback >= 2*SwingStaerke+10, MinCRV, Risiko, MaxLot müssen > 0 sein; Puffer/Kommission nicht negativ).");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!NewsParsen(NewsPausen))
   {
      Alert("ScalpScout Trend: NewsPausen muss das Format HH:MM-HH:MM[,HH:MM-HH:MM] haben (z. B. 15:25-15:45).");
      return INIT_PARAMETERS_INCORRECT;
   }
   string berichtEin = TagesberichtZeit;
   StringTrimLeft(berichtEin);
   StringTrimRight(berichtEin);
   if(berichtEin != "" && ParseHHMM(berichtEin) < 0)
   {
      Alert("ScalpScout Trend: TagesberichtZeit muss das Format HH:MM haben (z. B. 23:05) oder leer sein.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(Period() != PERIOD_M1)
      Print("ScalpScout Trend WARNUNG: EA ist für den M1-Chart gedacht (aktuell: ", Period(), " Min.). Auswertung läuft trotzdem auf M1.");

   // Laufzeit-Einstellungen: zuerst die Inputs, dann (nur live) die per Telegram gespeicherten Fern-Werte
   FernEingabenSetzen();
   FernLaden();
   BerichtNeuAnsetzen();
   string fernListe = FernListe();
   if(fernListe != "")
      Print("ScalpScout Trend: Fern-Einstellungen aktiv: ", fernListe);
   g_ui = (!IsTesting() || IsVisualMode());

   g_sig.aktiv = false;
   g_gestoppt  = false;
   g_hinweis   = "";
   g_histAnzahl = -1;
   g_sigId     = 0;
   g_sigMsgId  = 0;
   g_tgKopf    = "";
   g_tgPause   = false;
   g_stopTg    = false;
   for(int ci = 0; ci < 4; ci++)
   {
      g_cfgZeit[ci] = 0;
      g_cfgMsg[ci]  = 0;
   }
   g_trend     = 0;
   g_avwap     = 0.0;
   g_ziel      = 0.0;
   g_stratGrund = "wartet auf die erste Kerze";

   // Tagesstart (live aus globalen Variablen wiederherstellen)
   g_gvTag    = "SST_" + IntegerToString(AccountNumber()) + "_" + IntegerToString(MagicNumber) + "_tag";
   g_gvEquity = "SST_" + IntegerToString(AccountNumber()) + "_" + IntegerToString(MagicNumber) + "_eq";
   datetime heute = (datetime)((long)TimeCurrent() / 86400 * 86400);
   g_tag = 0;
   g_tagEquity = AccountEquity();
   if(!IsTesting() && GlobalVariableCheck(g_gvTag) && GlobalVariableCheck(g_gvEquity) &&
      (datetime)GlobalVariableGet(g_gvTag) == heute)
   {
      g_tag       = heute;
      g_tagEquity = GlobalVariableGet(g_gvEquity);
   }
   TagPruefen();

   // Telegram (nur live, nur mit Token und Chat-ID)
   TelegramStarten();

   // Erst die nächste neue Kerze auswerten (keine alte Kerze beim Anhängen)
   g_letzteKerze = iTime(Symbol(), PERIOD_M1, 0);

   if(g_ui)
   {
      InfoAufbauen();
      double a0, s0, t0, c0;
      int    ty0;
      PullbackErkennen(a0, s0, t0, ty0, c0);   // nur Anzeige (Trend/AVWAP), kein Handel
      UiAktualisieren();
   }
   if(!IsTesting())
      EventSetTimer(1);

   Print("ScalpScout Trend gestartet: ", Symbol(), ", Modus ", ModusText(), ", MaxLot ", DoubleToString(g_maxLot, 2),
         ", Risiko ", DoubleToString(g_risiko, 1), " %, Digits ", Digits, ", Point ", DoubleToString(Point, Digits));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PRAEFIX);
   Comment("");
   ChartRedraw(0);
   Print("ScalpScout Trend beendet (Grund ", reason, ").");
}

void OnTick()
{
   TagPruefen();
   PositionenVerwalten();
   SignalPruefen();

   datetime kerze = iTime(Symbol(), PERIOD_M1, 0);
   if(kerze != g_letzteKerze && kerze > 0)
   {
      g_letzteKerze = kerze;
      NeueKerzeAuswerten();
   }

   if(g_ui)
   {
      uint jetzt = GetTickCount();
      if(jetzt - g_uiLetzte >= 500)
      {
         g_uiLetzte = jetzt;
         UiAktualisieren();
      }
   }
}

// Läuft jede Sekunde (live): Signalablauf auch ohne neue Ticks erkennen
void OnTimer()
{
   TagPruefen();
   SignalPruefen();
   TgAbfragen();
   CfgAblaufPruefen();
   BerichtPruefen();
   TgSchliessungenPruefen();
   UiAktualisieren();
}

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id != CHARTEVENT_OBJECT_CLICK)
      return;

   if(sparam == OBJ_PNL_OK)
   {
      ObjectSetInteger(0, OBJ_PNL_OK, OBJPROP_STATE, false);
      string ergebnis = "";
      SignalAusfuehren(false, ergebnis);
      UiAktualisieren();
   }
   else if(sparam == OBJ_PNL_NO)
   {
      ObjectSetInteger(0, OBJ_PNL_NO, OBJPROP_STATE, false);
      SignalVerwerfen("vom Nutzer verworfen", "❌ am PC verworfen");
      HinweisSetzen("Signal verworfen");
      UiAktualisieren();
   }
   else if(sparam == OBJ_KILL)
   {
      ObjectSetInteger(0, OBJ_KILL, OBJPROP_STATE, false);
      int antwort = MessageBox("Alle Positionen von ScalpScout Trend (Magic " + IntegerToString(MagicNumber)
                               + ") auf " + Symbol() + " jetzt schließen?\n\nDanach sind neue Trades gesperrt, bis der EA neu gestartet wird.",
                               "ScalpScout Trend - ALLES SCHLIESSEN", MB_YESNO | MB_ICONWARNING);
      if(antwort == IDYES)
      {
         int gz = 0, fz = 0;
         AlleSchliessen(gz, fz);
      }
      UiAktualisieren();
   }
}
//+------------------------------------------------------------------+
