//+------------------------------------------------------------------+
//|                                                  ScalpScout.mq4  |
//|  Scalping-Assistent für M1: erkennt Volatilitäts-/Liquiditäts-   |
//|  schübe, zeigt Signale zur manuellen Freigabe oder handelt       |
//|  vollautomatisch. Keine Gewinnzusage - Handel auf eigenes Risiko.|
//+------------------------------------------------------------------+
#property copyright   "maehrsteuern"
#property version     "1.30"
#property description "ScalpScout - M1-Scalping-Assistent (Signal, manuelle Freigabe, Vollautomatik, Telegram-Fernsteuerung, Retest-Einstieg)"
#property strict

//--- Betriebsart (muss vor den Inputs definiert sein)
enum ENUM_MODUS
{
   MANUELLE_FREIGABE = 0,  // Manuelle Freigabe (Knopf im Chart)
   VOLLAUTOMATIK     = 1,  // Vollautomatik (handelt selbst)
   NUR_SIGNALE       = 2   // Nur Signale (Alert/Push, kein Trade)
};

//--- Einstiegsart (muss vor den Inputs definiert sein)
enum ENUM_EINSTIEG
{
   EINSTIEG_SOFORT = 0,  // Sofort (direkt nach der Signalkerze)
   EINSTIEG_RETEST = 1   // Retest (erst nach Rücklauf zur Signalkerze)
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

//--- Signal
input int    ATR_Periode           = 14;      // ATR-Periode (M1)
input double ImpulsFaktor          = 1.8;     // Kerzenkörper muss größer sein als x * ATR
input double VolumenFaktor         = 1.5;     // Tick-Volumen muss größer sein als x * Durchschnitt
input int    VolumenKerzen         = 20;      // Anzahl Kerzen für Durchschnittsvolumen
input int    BreakoutKerzen        = 10;      // Ausbruch über Hoch/Tief der letzten N Kerzen
input bool   TrendFilterAktiv      = true;    // Trendfilter (Schluss über/unter EMA) verwenden
input int    EMA_Periode           = 50;      // EMA-Periode (M1) für Trendfilter

//--- Einstieg
input ENUM_EINSTIEG Einstieg       = EINSTIEG_SOFORT; // Einstiegsart (Sofort oder Retest nach Rücklauf)
input double RetestAnteil          = 0.4;     // Retest: Rücklauf in Anteil des Signalkerzen-Körpers (0.2-0.8)
input int    RetestMaxKerzen       = 4;       // Retest: Signal verfällt nach N weiteren M1-Kerzen (1-15)
input double RetestSLPufferATR     = 0.1;     // Retest: SL-Puffer hinter dem Extrem der Signalkerze (x ATR)
input double RetestTP_CRV          = 1.8;     // Retest: TP = x * SL-Abstand (1.0-4.0)

//--- Ausstieg
input double SL_ATR                = 1.0;     // Stop-Loss = x * ATR
input double TP_ATR                = 1.5;     // Take-Profit = x * ATR
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

//--- Schutzfilter
input double MaxSpreadPunkte       = 0;       // Max. Spread in Punkten (0 = automatisch aus TP-Distanz)
input double SpreadAnteilTP        = 0.25;    // Automatik: Kosten (Spread + Kommission) müssen kleiner sein als x * TP-Distanz
input double KommissionProLot      = 0.0;     // Kommission pro Lot, Hin- und Rückweg zusammen, in Kontowährung (ECN)
input string HandelStart           = "08:00"; // Handelsfenster Beginn (Serverzeit, HH:MM)
input string HandelEnde            = "20:00"; // Handelsfenster Ende (Serverzeit, HH:MM)
input double TagesVerlustProzent   = 3.0;     // Tagesverlust-Limit in % vom Tagesbeginn-Equity (0 = aus)
input int    MaxOffenePositionen   = 1;       // Max. offene Positionen pro Symbol
input int    PauseNachVerlusten    = 3;       // Pause nach N Verlusten in Folge (0 = aus)
input int    PauseMinuten          = 30;      // Dauer der Pause (Minuten)
input int    MagicNumber           = 26101801;// Magic Number dieses EAs

//--- Telegram-Fernbedienung (Freigabe per Handy)
input bool   TelegramAktiv         = false;   // Telegram-Fernbedienung einschalten
input string TelegramToken         = "";      // Bot-Token von @BotFather (nie weitergeben)
input string TelegramChatID        = "";      // deine Chat-ID (nur dieser Chat darf steuern)
input int    TelegramAbfrageSek    = 2;       // Abfrageintervall (Sekunden)
input bool   TelegramMeldeSchliessung = true; // Nachricht bei geschlossener Position mit Ergebnis
input string TagesberichtZeit      = "23:05"; // Tagesbericht per Telegram (Serverzeit HH:MM, leer = aus)
input double FernMaxLotObergrenze  = 0.05;    // Per Telegram darf MaxLot höchstens bis hierhin erhöht werden (Sicherheitsgrenze)

//+------------------------------------------------------------------+
//| Konstanten und Typen                                             |
//+------------------------------------------------------------------+
#define PRAEFIX          "SSC_"
#define OBJ_KILL         "SSC_btn_kill"
#define OBJ_PNL_PRAEFIX  "SSC_pnl_"
#define OBJ_PNL_BG       "SSC_pnl_bg"
#define OBJ_PNL_OK       "SSC_pnl_btn_ok"
#define OBJ_PNL_NO       "SSC_pnl_btn_no"
#define OBJ_INFO_BG      "SSC_info_bg"
#define ORDER_KOMMENTAR  "ScalpScout"
#define INFO_ZEILEN      12
#define INFO_BREITE      540
#define INFO_MAXZEICHEN  88
#define PNL_ZEILEN       7

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
   double crv;        // Chance-Risiko-Verhältnis (TP/SL)
   double atr;        // verwendeter ATR-Wert
};

struct SignalZustand
{
   bool     aktiv;    // wartet auf Freigabe
   datetime zeit;     // Erzeugungszeit (TimeLocal)
   Plan     plan;     // berechneter Plan
   double   slFix;    // fester Stop-Loss-Preis (Retest), 0 = ATR-basiert
   double   tpFix;    // fester Take-Profit-Preis (Retest), 0 = ATR-basiert
};

// Wartendes Retest-Signal (nur eines zugleich, ein neues Signal ersetzt es)
struct RetestZustand
{
   bool     aktiv;      // Signal wartet auf den Rücklauf
   int      richtung;   // +1 Long, -1 Short
   datetime kerzeZeit;  // Zeit der Signalkerze (M1, Shift 1)
   double   kOpen;      // Signalkerze: Open
   double   kHigh;      //              High
   double   kLow;       //              Low
   double   kClose;     //              Close
   double   ziel;       // Zielpreis des Rücklaufs
   double   atr;        // ATR zur Signalkerze
   datetime verfall;    // ab dieser M1-Kerzenzeit ist das Signal verfallen
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

// Fern-Einstellungen: Laufzeit-Werte (Start = Inputs, per Telegram änderbar, in GlobalVariables gemerkt)
double        g_risiko         = 1.0;  // Risiko pro Trade in % vom Equity
double        g_maxLot         = 0.01; // Harter Lot-Deckel
double        g_tagesLimitProz = 3.0;  // Tagesverlust-Limit in % (0 = aus); g_tagesLimit ist der Merker "erreicht"
double        g_impulsFaktor   = 1.8;  // Kerzenkörper muss größer sein als x * ATR
double        g_volumenFaktor  = 1.5;  // Tick-Volumen muss größer sein als x * Durchschnitt
int           g_breakoutKerzen = 10;   // Ausbruch über Hoch/Tief der letzten N Kerzen
ENUM_MODUS    g_modusInput;            // Betriebsart laut Input (nach Tester-Regel) - Ziel von /reset
ENUM_EINSTIEG g_einstieg       = EINSTIEG_RETEST; // Einstiegsart (Sofort/Retest)
double        g_retestAnteil   = 0.4;  // Retest: Rücklauf in Anteil des Signalkerzen-Körpers
int           g_retestMaxKerzen = 4;   // Retest: Verfall nach N weiteren M1-Kerzen
double        g_retestTPCRV    = 1.8;  // Retest: TP = x * SL-Abstand
RetestZustand g_rt;                    // wartendes Retest-Signal
int           g_rtErreicht     = 0;    // Zähler seit Start: Rücklauf erreicht
int           g_rtVerfallen    = 0;    //   Signal verfallen (kein Rücklauf rechtzeitig)
int           g_rtAbgebrochen  = 0;    //   abgebrochen (Ausbruch gescheitert)
string        g_fernInfo       = "";   // Liste der aus GlobalVariables geladenen Abweichungen
long          g_cfgAutoMsg     = 0;    // Nachricht mit offener Rückfrage "Vollautomatik" (0 = keine)
datetime      g_cfgAutoBis     = 0;    // Ablauf dieser Rückfrage (TimeLocal)
long          g_cfgSchlMsg     = 0;    // Nachricht mit offener Rückfrage "Alle schließen" (0 = keine)
datetime      g_cfgSchlBis     = 0;    // Ablauf dieser Rückfrage (TimeLocal)

// Diagnose der letzten ausgewerteten M1-Kerze (für /diag und die Chart-Zeile)
bool          g_dgGueltig      = false; // Werte unten sind gültig
bool          g_dgSignalMoeglich = false; // Körper, Volumen, Richtung, Ausbruch und Trend erfüllt
datetime      g_dgZeit         = 0;    // Zeit der ausgewerteten Kerze
double        g_dgAtr          = 0.0;
double        g_dgKoerperX     = 0.0;  // Körper in ATR
double        g_dgVolX         = 0.0;  // Volumen in Vielfachen des Durchschnitts
bool          g_dgKoerperOK    = false;
bool          g_dgVolOK        = false;
bool          g_dgFarbeOK      = false; // Kerze läuft in die geprüfte Richtung
bool          g_dgAusbruchOK   = false;
bool          g_dgTrendOK      = false;
int           g_dgRichtung     = 1;    // geprüfte (nähere) Richtung +1/-1
double        g_dgKostenIst    = 0.0;
double        g_dgKostenMax    = 0.0;
bool          g_dgKostenOK     = false;
string        g_dgFilter       = "";   // Ergebnis der Schutzfilter
string        g_dgErgebnis     = "";   // Endergebnis der Auswertung
int           g_dgKerzen       = 0;    // Zähler seit Start: ausgewertete Kerzen
int           g_dgSignale      = 0;    //   erkannte Signale
int           g_dgTrades       = 0;    //   eröffnete Trades
int           g_dgVerworfen    = 0;    //   nicht gehandelte Signale
string        g_dgGrund[20];           //   Gründe dafür (gekürzt)
int           g_dgGrundN[20];          //   Häufigkeit je Grund
int           g_dgGrundAnz     = 0;

// Weitere Fern-Einstellungen und offene Rückfragen
bool          g_beAktiv        = true; // Break-even aktiv
bool          g_trailingAktiv  = false; // Trailing aktiv
int           g_berichtMin     = -1;   // Uhrzeit Tagesbericht (Minuten ab 00:00, -1 = aus)
datetime      g_berichtTag     = 0;    // Serverzeit-Tag, für den der Bericht schon gesendet wurde
datetime      g_berichtRetry   = 0;    // nach Sendefehler frühestens dann wieder (TimeLocal)
long          g_cfgZuMsg       = 0;    // Rückfrage "Position schließen"
datetime      g_cfgZuBis       = 0;
int           g_cfgZuTicket    = 0;
long          g_cfgHandMsg     = 0;    // Rückfrage "Hand-Trade"
datetime      g_cfgHandBis     = 0;
int           g_cfgHandRicht   = 0;
double        g_cfgHandLot     = 0.0;  // 0 = Lot aus Risiko
long          g_cfgStartMsg    = 0;    // Rückfrage "Kill-Switch-Sperre lösen"
datetime      g_cfgStartBis    = 0;

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
   Print("ScalpScout FEHLER bei ", kontext, ": Code ", err, " (", FehlerText(err), ")");
}

// Minuten seit 00:00 aus "HH:MM"; -1 bei ungültiger Eingabe
int ParseHHMM(string s)
{
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

// Maximal erlaubte Kosten (Spread + Kommission) in Punkten
double MaxSpreadAktuell(double atr)
{
   if(MaxSpreadPunkte > 0.0)
      return MaxSpreadPunkte;
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   double tpDist  = MathMax(TP_ATR * atr, stopLvl);
   return SpreadAnteilTP * tpDist / Point;
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
   Print("ScalpScout Hinweis: ", text);
}

//+------------------------------------------------------------------+
//| Fern-Einstellungen: Hilfsfunktionen und Speicherung              |
//+------------------------------------------------------------------+
// Die Laufzeit-Werte g_risiko, g_maxLot, g_tagesLimitProz, g_startMin/g_endeMin,
// g_impulsFaktor, g_volumenFaktor, g_breakoutKerzen und g_modus starten mit den Inputs.
// Per Telegram geänderte Werte liegen in GlobalVariables (SSC_<konto>_<magic>_<name>)
// und überstehen einen Neustart. Im Strategietester wird nichts gespeichert oder geladen.

string HaekchenText(bool ok)
{
   return ok ? "✓" : "✗";
}

// "HH:MM" aus Minuten seit 00:00
string MinutenText(int m)
{
   return IntegerToString(m / 60, 2, '0') + ":" + IntegerToString(m % 60, 2, '0');
}

// "H:MM" oder "HH:MM" -> Minuten seit 00:00; -1 bei ungültiger Eingabe
int ZeitLesen(string s)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   if(StringLen(s) == 4 && StringGetCharacter(s, 1) == ':')
      s = "0" + s;
   return ParseHHMM(s);
}

// Zahl aus Telegram lesen: Komma oder Punkt, optional "%" am Ende, nur Ziffern und ein Dezimaltrenner
bool ZahlLesen(string s, double &w)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   StringReplace(s, ",", ".");
   int n = StringLen(s);
   if(n > 0 && StringGetCharacter(s, n - 1) == '%')
   {
      s = StringSubstr(s, 0, n - 1);
      StringTrimRight(s);
      n = StringLen(s);
   }
   if(n == 0 || n > 12)
      return false;
   int punkte = 0, ziffern = 0;
   for(int i = 0; i < n; i++)
   {
      ushort c = StringGetCharacter(s, i);
      if(c >= '0' && c <= '9')
         ziffern++;
      else if(c == '.')
         punkte++;
      else
         return false;
   }
   if(ziffern == 0 || punkte > 1)
      return false;
   w = StringToDouble(s);
   return true;
}

double MinLotWert()
{
   double m = MarketInfo(Symbol(), MODE_MINLOT);
   return (m > 0.0) ? m : 0.01;
}

// Höchster per Telegram erlaubter Lot-Deckel: FernMaxLotObergrenze, höchstens Broker-MaxLot
double MaxLotGrenze()
{
   double g = FernMaxLotObergrenze;
   double b = MarketInfo(Symbol(), MODE_MAXLOT);
   if(b > 0.0 && b < g)
      g = b;
   return g;
}

int LotStellenAktuell()
{
   double step = MarketInfo(Symbol(), MODE_LOTSTEP);
   return LotStellen((step > 0.0) ? step : 0.01);
}

string LotText(double lot)
{
   return DoubleToString(lot, LotStellenAktuell());
}

string LimitText(double proz)
{
   return (proz > 0.0) ? DoubleToString(proz, 1) + " %" : "aus";
}

string GeldText(double v)
{
   return ((v >= 0.0) ? "+" : "") + DoubleToString(v, 2) + " " + AccountCurrency();
}

string ModusName(ENUM_MODUS m)
{
   switch(m)
   {
      case MANUELLE_FREIGABE: return "Manuelle Freigabe";
      case VOLLAUTOMATIK:     return "Vollautomatik";
      case NUR_SIGNALE:       return "Nur Signale";
   }
   return "?";
}

string EinstiegName(ENUM_EINSTIEG e)
{
   switch(e)
   {
      case EINSTIEG_SOFORT: return "Sofort";
      case EINSTIEG_RETEST: return "Retest";
   }
   return "?";
}

// Name einer globalen Variable für Fern-Einstellungen (Konto + Magic)
string FernSchluessel(string name)
{
   return "SSC_" + IntegerToString(AccountNumber()) + "_" + IntegerToString(MagicNumber) + "_" + name;
}

void FernSpeichern(string name, double wert)
{
   if(IsTesting())
      return;
   ResetLastError();
   if(GlobalVariableSet(FernSchluessel(name), wert) == 0)
      LogFehler("GlobalVariableSet " + name, GetLastError());
}

void FernLoeschen(string name)
{
   if(IsTesting())
      return;
   string k = FernSchluessel(name);
   if(GlobalVariableCheck(k))
      GlobalVariableDel(k);
}

void FernAlleLoeschen()
{
   FernLoeschen("risiko");
   FernLoeschen("maxlot");
   FernLoeschen("limit");
   FernLoeschen("start");
   FernLoeschen("ende");
   FernLoeschen("impuls");
   FernLoeschen("volumen");
   FernLoeschen("ausbruch");
   FernLoeschen("modus");
   FernLoeschen("be");
   FernLoeschen("trailing");
   FernLoeschen("bericht");
   FernLoeschen("einstieg");
   FernLoeschen("retest");
   FernLoeschen("retestk");
   FernLoeschen("crv");
}

bool FernLesen(string name, double &v)
{
   string k = FernSchluessel(name);
   if(!GlobalVariableCheck(k))
      return false;
   v = GlobalVariableGet(k);
   return true;
}

// Abweichung vom Input? (für "(fern geändert)")
bool FernRisikoAbw()   { return MathAbs(g_risiko - RisikoProzent) > 1e-9; }
bool FernMaxLotAbw()   { return MathAbs(g_maxLot - MaxLot) > 1e-9; }
bool FernLimitAbw()    { return MathAbs(g_tagesLimitProz - TagesVerlustProzent) > 1e-9; }
bool FernZeitAbw()     { return (g_startMin != ParseHHMM(HandelStart) || g_endeMin != ParseHHMM(HandelEnde)); }
bool FernImpulsAbw()   { return MathAbs(g_impulsFaktor - ImpulsFaktor) > 1e-9; }
bool FernVolumenAbw()  { return MathAbs(g_volumenFaktor - VolumenFaktor) > 1e-9; }
bool FernAusbruchAbw() { return g_breakoutKerzen != BreakoutKerzen; }
bool FernModusAbw()    { return g_modus != g_modusInput; }
bool FernBeAbw()       { return g_beAktiv != BE_Aktiv; }
bool FernTrailAbw()    { return g_trailingAktiv != TrailingAktiv; }
bool FernEinstiegAbw() { return g_einstieg != Einstieg; }
bool FernRetestAbw()   { return MathAbs(g_retestAnteil - RetestAnteil) > 1e-9; }
bool FernRetestKerzenAbw() { return g_retestMaxKerzen != RetestMaxKerzen; }
bool FernCrvAbw()      { return MathAbs(g_retestTPCRV - RetestTP_CRV) > 1e-9; }

// Tagesbericht-Uhrzeit laut Input in Minuten (-1 = aus/leer)
int BerichtInputMin()
{
   string s = TagesberichtZeit;
   StringTrimLeft(s);
   StringTrimRight(s);
   return (s == "") ? -1 : ParseHHMM(s);
}
bool FernBerichtAbw()  { return g_berichtMin != BerichtInputMin(); }

string FernMarke(bool abw)
{
   return abw ? " (fern geändert)" : "";
}

void ListeAnfuegen(string &liste, string eintrag)
{
   liste += ((liste == "") ? "" : ", ") + eintrag;
}

// Liste aller Werte, die vom Input abweichen ("" = keine)
string FernAbweichungen()
{
   string r = "";
   if(FernModusAbw())   ListeAnfuegen(r, "Modus " + ModusText());
   if(FernRisikoAbw())  ListeAnfuegen(r, "Risiko " + DoubleToString(g_risiko, 1) + " %");
   if(FernMaxLotAbw())  ListeAnfuegen(r, "MaxLot " + LotText(g_maxLot));
   if(FernLimitAbw())   ListeAnfuegen(r, "Tageslimit " + LimitText(g_tagesLimitProz));
   if(FernZeitAbw())    ListeAnfuegen(r, "Zeit " + MinutenText(g_startMin) + "-" + MinutenText(g_endeMin));
   if(FernImpulsAbw())  ListeAnfuegen(r, "Körper " + DoubleToString(g_impulsFaktor, 2));
   if(FernVolumenAbw()) ListeAnfuegen(r, "Volumen " + DoubleToString(g_volumenFaktor, 2));
   if(FernAusbruchAbw()) ListeAnfuegen(r, "Ausbruch " + IntegerToString(g_breakoutKerzen));
   if(FernBeAbw())      ListeAnfuegen(r, "Break-even " + (g_beAktiv ? "an" : "aus"));
   if(FernTrailAbw())   ListeAnfuegen(r, "Trailing " + (g_trailingAktiv ? "an" : "aus"));
   if(FernBerichtAbw()) ListeAnfuegen(r, "Bericht " + BerichtZeitText(g_berichtMin));
   if(FernEinstiegAbw()) ListeAnfuegen(r, "Einstieg " + EinstiegName(g_einstieg));
   if(FernRetestAbw())  ListeAnfuegen(r, "Retest-Anteil " + DoubleToString(g_retestAnteil, 2));
   if(FernRetestKerzenAbw()) ListeAnfuegen(r, "Retest-Kerzen " + IntegerToString(g_retestMaxKerzen));
   if(FernCrvAbw())     ListeAnfuegen(r, "Retest-CRV " + DoubleToString(g_retestTPCRV, 2));
   return r;
}

// Alle wirksamen Werte in einer Zeile (für /reset)
string WerteText()
{
   return "Modus " + ModusText() + ", Risiko " + DoubleToString(g_risiko, 1) + " %, MaxLot " + LotText(g_maxLot)
          + ", Tageslimit " + LimitText(g_tagesLimitProz) + ", Zeit " + MinutenText(g_startMin) + "-"
          + MinutenText(g_endeMin) + ", Körper " + DoubleToString(g_impulsFaktor, 2) + ", Volumen "
          + DoubleToString(g_volumenFaktor, 2) + ", Ausbruch " + IntegerToString(g_breakoutKerzen)
          + ", Break-even " + (g_beAktiv ? "an" : "aus") + ", Trailing " + (g_trailingAktiv ? "an" : "aus")
          + ", Bericht " + BerichtZeitText(g_berichtMin)
          + ", Einstieg " + EinstiegName(g_einstieg) + ", Retest-Anteil " + DoubleToString(g_retestAnteil, 2)
          + ", Retest-Kerzen " + IntegerToString(g_retestMaxKerzen) + ", Retest-CRV " + DoubleToString(g_retestTPCRV, 2);
}

// Werte aus den Inputs setzen (Start und /reset); Modus nach Tester-Regel steht in g_modusInput
void FernInputsUebernehmen()
{
   g_risiko         = RisikoProzent;
   g_maxLot         = MaxLot;
   g_tagesLimitProz = TagesVerlustProzent;
   g_startMin       = ParseHHMM(HandelStart);
   g_endeMin        = ParseHHMM(HandelEnde);
   g_impulsFaktor   = ImpulsFaktor;
   g_volumenFaktor  = VolumenFaktor;
   g_breakoutKerzen = BreakoutKerzen;
   g_beAktiv        = BE_Aktiv;
   g_trailingAktiv  = TrailingAktiv;
   g_berichtMin     = BerichtInputMin();
   g_einstieg       = Einstieg;
   g_retestAnteil   = RetestAnteil;
   g_retestMaxKerzen = RetestMaxKerzen;
   g_retestTPCRV    = RetestTP_CRV;
   g_modus          = g_modusInput;
}

// Gespeicherte Fern-Einstellungen laden (nur live). Ungültige Werte werden ignoriert -> Input gilt.
void FernLaden()
{
   g_fernInfo = "";
   if(IsTesting())
      return;
   double v = 0.0, v2 = 0.0;

   if(FernLesen("risiko", v))
   {
      if(v >= 0.1 - 1e-9 && v <= 25.0 + 1e-9) g_risiko = v;
      else Print("ScalpScout: gespeicherter Wert 'risiko' ungültig - Input gilt.");
   }
   if(FernLesen("maxlot", v))
   {
      if(v >= MinLotWert() - 1e-9 && v <= MaxLotGrenze() + 1e-9) g_maxLot = LotAbrunden(v);
      else Print("ScalpScout: gespeicherter Wert 'maxlot' ungültig - Input gilt.");
   }
   if(FernLesen("limit", v))
   {
      if(v < 1e-9 || (v >= 1.0 - 1e-9 && v <= 100.0 + 1e-9)) g_tagesLimitProz = (v < 1e-9) ? 0.0 : v;
      else Print("ScalpScout: gespeicherter Wert 'limit' ungültig - Input gilt.");
   }
   if(FernLesen("start", v) && FernLesen("ende", v2))
   {
      if(v >= 0 && v <= 1439 && v2 >= 0 && v2 <= 1439)
      {
         g_startMin = (int)MathRound(v);
         g_endeMin  = (int)MathRound(v2);
      }
      else Print("ScalpScout: gespeichertes Handelsfenster ungültig - Input gilt.");
   }
   if(FernLesen("impuls", v))
   {
      if(v >= 0.5 - 1e-9 && v <= 4.0 + 1e-9) g_impulsFaktor = v;
      else Print("ScalpScout: gespeicherter Wert 'impuls' ungültig - Input gilt.");
   }
   if(FernLesen("volumen", v))
   {
      if(v >= 0.8 - 1e-9 && v <= 4.0 + 1e-9) g_volumenFaktor = v;
      else Print("ScalpScout: gespeicherter Wert 'volumen' ungültig - Input gilt.");
   }
   if(FernLesen("ausbruch", v))
   {
      if(v >= 2.0 - 1e-9 && v <= 50.0 + 1e-9) g_breakoutKerzen = (int)MathRound(v);
      else Print("ScalpScout: gespeicherter Wert 'ausbruch' ungültig - Input gilt.");
   }
   if(FernLesen("be", v))
      g_beAktiv = (v > 0.5);
   if(FernLesen("trailing", v))
      g_trailingAktiv = (v > 0.5);
   if(FernLesen("bericht", v))
   {
      if(v >= -1.0 - 1e-9 && v <= 1439.0 + 1e-9) g_berichtMin = (int)MathRound(v);
      else Print("ScalpScout: gespeicherter Wert 'bericht' ungültig - Input gilt.");
   }
   if(FernLesen("einstieg", v))
   {
      if(MathAbs(v - (double)EINSTIEG_SOFORT) < 0.5)       g_einstieg = EINSTIEG_SOFORT;
      else if(MathAbs(v - (double)EINSTIEG_RETEST) < 0.5)  g_einstieg = EINSTIEG_RETEST;
      else Print("ScalpScout: gespeicherter Wert 'einstieg' ungültig - Input gilt.");
   }
   if(FernLesen("retest", v))
   {
      if(v >= 0.2 - 1e-9 && v <= 0.8 + 1e-9) g_retestAnteil = v;
      else Print("ScalpScout: gespeicherter Wert 'retest' ungültig - Input gilt.");
   }
   if(FernLesen("retestk", v))
   {
      if(v >= 1.0 - 1e-9 && v <= 15.0 + 1e-9) g_retestMaxKerzen = (int)MathRound(v);
      else Print("ScalpScout: gespeicherter Wert 'retestk' ungültig - Input gilt.");
   }
   if(FernLesen("crv", v))
   {
      if(v >= 1.0 - 1e-9 && v <= 4.0 + 1e-9) g_retestTPCRV = v;
      else Print("ScalpScout: gespeicherter Wert 'crv' ungültig - Input gilt.");
   }
   if(FernLesen("berichttag", v))        // kein Einstellwert: Tag des zuletzt gesendeten Berichts
      g_berichtTag = (datetime)(long)v;
   // Vollautomatik wird nie gespeichert: nach einem Neustart gilt dann der Input
   if(FernLesen("modus", v))
   {
      if(MathAbs(v - (double)MANUELLE_FREIGABE) < 0.5)      g_modus = MANUELLE_FREIGABE;
      else if(MathAbs(v - (double)NUR_SIGNALE) < 0.5)       g_modus = NUR_SIGNALE;
      else Print("ScalpScout: gespeicherter Wert 'modus' ungültig - Input gilt.");
   }

   g_fernInfo = FernAbweichungen();
   if(g_fernInfo != "")
      Print("ScalpScout: Fern-Einstellungen aktiv: ", g_fernInfo);
}

// Betriebsart wechseln (sofort wirksam) und merken. Vollautomatik wird nie gespeichert.
void ModusSetzen(ENUM_MODUS neu)
{
   g_modus = neu;
   if(neu != MANUELLE_FREIGABE && g_sig.aktiv)
      SignalVerwerfen("Moduswechsel", "⌛ verworfen (Moduswechsel)");
   if(neu == g_modusInput || neu == VOLLAUTOMATIK)
      FernLoeschen("modus");
   else
      FernSpeichern("modus", (double)neu);
   HinweisSetzen("Modus: " + ModusText() + " (Telegram)");
}

//+------------------------------------------------------------------+
//| Diagnose der letzten ausgewerteten M1-Kerze                      |
//+------------------------------------------------------------------+
void DiagZuruecksetzen()
{
   g_dgGueltig        = false;
   g_dgSignalMoeglich = false;
   g_dgZeit           = 0;
   g_dgErgebnis       = "";
   g_dgFilter         = "";
   g_dgKerzen         = 0;
   g_dgSignale        = 0;
   g_dgTrades         = 0;
   g_dgVerworfen      = 0;
   g_dgGrundAnz       = 0;
   g_rtErreicht       = 0;
   g_rtVerfallen      = 0;
   g_rtAbgebrochen    = 0;
}

// Grund ohne wechselnde Zahlen, damit gleiche Gründe zusammengezählt werden
string GrundKurz(string grund)
{
   if(StringFind(grund, "Lot ") == 0)
      return "Lot unter MinLot (Risiko zu klein)";
   if(StringFind(grund, "MaxLot-Deckel") == 0)
      return "MaxLot unter MinLot";
   if(StringFind(grund, "Nicht genug freie Margin") == 0)
      return "Nicht genug freie Margin";
   int p = StringFind(grund, " (");
   if(p > 0)
      grund = StringSubstr(grund, 0, p);
   return grund;
}

// Ein erkanntes Signal wurde nicht gehandelt: zählen und Grund merken
void DiagVerworfen(string grund)
{
   g_dgVerworfen++;
   string k = GrundKurz(grund);
   for(int i = 0; i < g_dgGrundAnz; i++)
   {
      if(g_dgGrund[i] == k)
      {
         g_dgGrundN[i]++;
         return;
      }
   }
   if(g_dgGrundAnz < 20)
   {
      g_dgGrund[g_dgGrundAnz]  = k;
      g_dgGrundN[g_dgGrundAnz] = 1;
      g_dgGrundAnz++;
   }
}

// Rein lesend: bewertet die zuletzt geschlossene M1-Kerze in beiden Richtungen (gleiche Regeln wie
// SignalErkennen, aber ohne vorzeitigen Abbruch) und merkt die Werte für /diag und die Chart-Zeile.
void DiagKerze()
{
   g_dgGueltig        = false;
   g_dgSignalMoeglich = false;
   g_dgFilter         = "";
   g_dgErgebnis       = "";
   g_dgZeit           = iTime(Symbol(), PERIOD_M1, 1);

   int mindestens = MathMax(MathMax(ATR_Periode, EMA_Periode * 2), VolumenKerzen + g_breakoutKerzen) + 5;
   if(iBars(Symbol(), PERIOD_M1) < mindestens)
   {
      g_dgErgebnis = "kein Signal: zu wenig M1-Kerzen im Chart (" + IntegerToString(mindestens) + " nötig)";
      return;
   }
   double atr = AktuelleATR();
   if(atr <= 0.0)
   {
      g_dgErgebnis = "kein Signal: ATR nicht verfügbar";
      return;
   }
   g_dgAtr = atr;

   double o1      = iOpen(Symbol(), PERIOD_M1, 1);
   double c1      = iClose(Symbol(), PERIOD_M1, 1);
   double koerper = MathAbs(c1 - o1);
   g_dgKoerperX  = koerper / atr;
   g_dgKoerperOK = (koerper > g_impulsFaktor * atr);

   double summe = 0.0;
   for(int i = 2; i <= VolumenKerzen + 1; i++)
      summe += (double)iVolume(Symbol(), PERIOD_M1, i);
   double schnitt = (VolumenKerzen > 0) ? summe / VolumenKerzen : 0.0;
   double vol1    = (double)iVolume(Symbol(), PERIOD_M1, 1);
   g_dgVolX  = (schnitt > 0.0) ? vol1 / schnitt : 0.0;
   g_dgVolOK = (schnitt > 0.0 && vol1 > g_volumenFaktor * schnitt);

   double ema = iMA(Symbol(), PERIOD_M1, EMA_Periode, 0, MODE_EMA, PRICE_CLOSE, 1);
   int hi = iHighest(Symbol(), PERIOD_M1, MODE_HIGH, g_breakoutKerzen, 2);
   int lo = iLowest(Symbol(), PERIOD_M1, MODE_LOW, g_breakoutKerzen, 2);
   bool farbeL = (c1 > o1);
   bool farbeS = (c1 < o1);
   bool ausL   = (hi >= 0 && c1 > iHigh(Symbol(), PERIOD_M1, hi));
   bool ausS   = (lo >= 0 && c1 < iLow(Symbol(), PERIOD_M1, lo));
   bool trL    = (!TrendFilterAktiv || c1 > ema);
   bool trS    = (!TrendFilterAktiv || c1 < ema);
   int  pktL   = (farbeL ? 1 : 0) + (ausL ? 1 : 0) + (trL ? 1 : 0);
   int  pktS   = (farbeS ? 1 : 0) + (ausS ? 1 : 0) + (trS ? 1 : 0);

   // die Richtung zeigen, die weniger weit vom Signal entfernt ist (bei Gleichstand die Kerzenfarbe)
   int r = 1;
   if(pktS > pktL || (pktS == pktL && farbeS))
      r = -1;
   g_dgRichtung   = r;
   g_dgFarbeOK    = (r > 0) ? farbeL : farbeS;
   g_dgAusbruchOK = (r > 0) ? ausL : ausS;
   g_dgTrendOK    = (r > 0) ? trL : trS;

   g_dgKostenIst = SpreadPunkte() + KommissionPunkte();
   g_dgKostenMax = MaxSpreadAktuell(atr);
   g_dgKostenOK  = (g_dgKostenIst <= g_dgKostenMax);

   string grund = "";
   g_dgFilter = HandelErlaubt(grund, atr) ? "alle frei" : grund;

   string txt = (r > 0) ? "LONG" : "SHORT";
   g_dgSignalMoeglich = (g_dgKoerperOK && g_dgVolOK && g_dgFarbeOK && g_dgAusbruchOK && g_dgTrendOK);
   if(!g_dgKoerperOK)
      g_dgErgebnis = "kein Signal: Kerzenkörper zu klein";
   else if(!g_dgVolOK)
      g_dgErgebnis = "kein Signal: Volumen zu klein";
   else if(!g_dgFarbeOK)
      g_dgErgebnis = "kein Signal: Kerze läuft nicht in Richtung " + txt;
   else if(!g_dgAusbruchOK)
      g_dgErgebnis = "kein Signal: kein Ausbruch (" + txt + ")";
   else if(!g_dgTrendOK)
      g_dgErgebnis = "kein Signal: Trendfilter/EMA (" + txt + ")";
   g_dgGueltig = true;
}

// Chart-Zeile "Letzte Kerze: Körper 1.1/1.8 ✗ | Vol 1.6/1.5 ✓ | Ausbr ✗ | Trend ✓"
string DiagInfoText(color &clr)
{
   if(!g_dgGueltig)
   {
      clr = clrSilver;
      return (g_dgZeit == 0) ? "Letzte Kerze: noch nicht ausgewertet" : "Letzte Kerze: " + g_dgErgebnis;
   }
   clr = g_dgSignalMoeglich ? clrLime : clrSilver;
   return "Letzte Kerze: Körper " + DoubleToString(g_dgKoerperX, 1) + "/" + DoubleToString(g_impulsFaktor, 1)
          + " " + HaekchenText(g_dgKoerperOK)
          + " | Vol " + DoubleToString(g_dgVolX, 1) + "/" + DoubleToString(g_volumenFaktor, 1)
          + " " + HaekchenText(g_dgVolOK)
          + " | Ausbr " + HaekchenText(g_dgAusbruchOK)
          + " | Trend " + HaekchenText(g_dgTrendOK);
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
      Print("ScalpScout: neuer Handelstag, Start-Equity ", DoubleToString(g_tagEquity, 2));
   }
   // Tageslimit einrasten (gilt bis zum nächsten Tag)
   if(!g_tagesLimit && g_tagesLimitProz > 0.0 && g_tagEquity > 0.0)
   {
      double verlustProz = (g_tagEquity - AccountEquity()) / g_tagEquity * 100.0;
      if(verlustProz >= g_tagesLimitProz)
      {
         g_tagesLimit = true;
         Print("ScalpScout: Tagesverlust-Limit erreicht (", DoubleToString(verlustProz, 2),
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

// Prüft alle Schutzfilter. true = Handel erlaubt, sonst Grund in 'grund'
// manuell = Hand-Trade per Telegram: Zeitfenster und Spread-Limit werden ignoriert
bool HandelErlaubt(string &grund, double atr, bool manuell = false)
{
   grund = "";
   VerlustSerieAktualisieren();

   if(g_gestoppt)
   {
      grund = "Gestoppt (Kill-Switch) - per Telegram /start oder EA neu starten";
      return false;
   }
   if(g_tgPause)
   {
      grund = "Pausiert per Telegram (/start hebt auf)";
      return false;
   }
   if((g_modus != NUR_SIGNALE || manuell) && !IsTesting() && (!IsTradeAllowed() || !IsExpertEnabled()))
   {
      grund = "Algo-Trading/AutoTrading ist aus";
      return false;
   }
   if(!manuell && !ZeitfensterOK())
   {
      grund = "Außerhalb Handelszeit (" + MinutenText(g_startMin) + "-" + MinutenText(g_endeMin) + ")";
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
   if(!manuell && kosten > maxSp)
   {
      grund = "Kosten zu hoch (" + KostenText(sp, ko) + " > " + DoubleToString(maxSp, 1) + " Pkt)";
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Plan berechnen: Preise, SL/TP, Lot                               |
//+------------------------------------------------------------------+
// lotVorgabe > 0: feste Lotgröße statt Risiko-Berechnung (Hand-Trade, Deckel = FernMaxLotObergrenze)
// slFix/tpFix > 0: feste SL-/TP-Preise (Retest) statt ATR-Abstand; StopLevel wird geprüft, sonst false
bool BerechnePlan(int richtung, double atr, Plan &p, string &grund, double lotVorgabe = 0.0,
                  double slFix = 0.0, double tpFix = 0.0)
{
   grund = "";
   RefreshRates();

   if(atr <= 0.0)
   {
      grund = "ATR nicht verfügbar";
      return false;
   }

   p.richtung  = richtung;
   p.atr       = atr;
   p.preis     = (richtung > 0) ? Ask : Bid;
   p.spreadPkt = SpreadPunkte();
   p.kommPkt   = KommissionPunkte();

   double spread  = Ask - Bid;
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;

   // Mindestabstände: SL wird vom Gegenkurs gemessen -> StopLevel + Spread
   double slDist = MathMax(SL_ATR * atr, stopLvl + spread);
   double tpDist = MathMax(TP_ATR * atr, stopLvl);

   if(richtung > 0)
   {
      p.sl = NormalizeDouble(p.preis - slDist, Digits);
      p.tp = NormalizeDouble(p.preis + tpDist, Digits);
   }
   else
   {
      p.sl = NormalizeDouble(p.preis + slDist, Digits);
      p.tp = NormalizeDouble(p.preis - tpDist, Digits);
   }
   // Feste Preise (Retest): StopLevel gegen den Gegenkurs prüfen (Long: Bid, Short: Ask)
   if(slFix > 0.0)
   {
      double sf = NormalizeDouble(slFix, Digits);
      double gr = (richtung > 0) ? NormalizeDouble(Bid - stopLvl, Digits) : NormalizeDouble(Ask + stopLvl, Digits);
      if((richtung > 0 && sf > gr + Point / 2.0) || (richtung < 0 && sf < gr - Point / 2.0))
      {
         grund = "Retest: SL verletzt StopLevel (SL " + DoubleToString(sf, Digits) + ", Grenze "
                 + DoubleToString(gr, Digits) + ", StopLevel " + DoubleToString(stopLvl / Point, 0) + " Pkt)";
         return false;
      }
      p.sl = sf;
   }
   if(tpFix > 0.0)
   {
      double tf = NormalizeDouble(tpFix, Digits);
      double gt = (richtung > 0) ? NormalizeDouble(Bid + stopLvl, Digits) : NormalizeDouble(Ask - stopLvl, Digits);
      if((richtung > 0 && tf < gt - Point / 2.0) || (richtung < 0 && tf > gt + Point / 2.0))
      {
         grund = "Retest: TP verletzt StopLevel (TP " + DoubleToString(tf, Digits) + ", Grenze "
                 + DoubleToString(gt, Digits) + ", StopLevel " + DoubleToString(stopLvl / Point, 0) + " Pkt)";
         return false;
      }
      p.tp = tf;
   }
   p.slDist = MathAbs(p.preis - p.sl);
   p.tpDist = MathAbs(p.preis - p.tp);
   if(p.slDist <= 0.0)
   {
      grund = "SL-Abstand ungültig";
      return false;
   }
   p.crv = p.tpDist / p.slDist;

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
   double lotRoh = (lotVorgabe > 0.0) ? lotVorgabe : risikoGeld / verlustProLot;
   double lot    = LotAbrunden(lotRoh);

   if(lot < minLot - 1e-9)
   {
      grund = "Lot " + DoubleToString(lotRoh, 4) + " < MinLot " + DoubleToString(minLot, 2)
              + ": Risiko " + DoubleToString(g_risiko, 1) + " % zu klein, kein Trade";
      return false;
   }
   if(lotVorgabe <= 0.0 && lot > g_maxLot)
      lot = LotAbrunden(g_maxLot);
   if(lotVorgabe > 0.0 && lot > FernMaxLotObergrenze)
      lot = LotAbrunden(FernMaxLotObergrenze);
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
bool OrderOeffnen(int richtung, double atr, string &grund, double lotVorgabe = 0.0,
                  double slFix = 0.0, double tpFix = 0.0)
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
      if(!BerechnePlan(richtung, atr, p, grund, lotVorgabe, slFix, tpFix))
         return false;

      ResetLastError();
      int ticket = OrderSend(Symbol(), cmd, p.lot, p.preis, slip, p.sl, p.tp,
                             ORDER_KOMMENTAR, MagicNumber, 0, clr);
      if(ticket > 0)
      {
         Print("ScalpScout: Order eröffnet #", ticket, " ", (richtung > 0 ? "BUY " : "SELL "),
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
   if(!g_beAktiv && !g_trailingAktiv)
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
         if(g_trailingAktiv && gewinn >= TrailingStartATR * atr)
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
         if(g_trailingAktiv && gewinn >= TrailingStartATR * atr)
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
            Print("ScalpScout: SL #", OrderTicket(), " nachgezogen auf ", DoubleToString(neu, Digits));
      }
   }
}

//+------------------------------------------------------------------+
//| Kill-Switch: alle eigenen Positionen auf diesem Symbol schließen |
//+------------------------------------------------------------------+
// Rückgabe über geschlossen/fehler; die Bestätigung (MessageBox bzw. Telegram-Knopf) liegt beim Aufrufer
void AlleSchliessen(int &geschlossen, int &fehler)
{
   geschlossen = 0;
   fehler = 0;
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
   SignalVerwerfen("Kill-Switch", "🛑 verworfen (Kill-Switch)");
   RetestLoeschen("Kill-Switch");
   PanelLoeschen();
   g_sig.aktiv = false;
   HinweisSetzen("Kill-Switch: " + IntegerToString(geschlossen) + " Position(en) geschlossen, "
                 + IntegerToString(fehler) + " Fehler. Neue Trades gesperrt.");
   Alert("ScalpScout ", Symbol(), ": Kill-Switch - ", geschlossen, " geschlossen, ", fehler, " Fehler");
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

string ModusText()
{
   return ModusName(g_modus);
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

   InfoZeile(0, "ScalpScout | " + Symbol() + " | Magic " + IntegerToString(MagicNumber), clrWhite);
   InfoZeile(1, "Modus: " + ModusText() + (IsTesting() ? " (Tester)" : "") + " | Risiko "
                + DoubleToString(g_risiko, 1) + " % | MaxLot " + LotText(g_maxLot),
             (FernModusAbw() || FernRisikoAbw() || FernMaxLotAbw()) ? clrGold : clrWhite);
   InfoZeile(2, "Kosten: " + KostenText(sp, ko) + " / max " + DoubleToString(maxSp, 1) + " Pkt",
             (sp + ko > maxSp) ? clrOrangeRed : clrLime);
   InfoZeile(3, "ATR(" + IntegerToString(ATR_Periode) + ", M1): " + DoubleToString(atr, Digits)
                + " (" + DoubleToString(atr / Point, 0) + " Pkt)", clrWhite);
   InfoZeile(4, "Serverzeit: " + TimeToString(TimeCurrent(), TIME_MINUTES)
                + " (Handel " + MinutenText(g_startMin) + "-" + MinutenText(g_endeMin) + ")",
             ZeitfensterOK() ? clrLime : clrOrange);
   InfoZeile(5, "Tagesergebnis: " + DoubleToString(diff, 2) + " " + AccountCurrency()
                + " (" + DoubleToString(proz, 2) + " %)", (diff >= 0.0) ? clrLime : clrOrangeRed);
   InfoZeile(6, g_tagesLimit ? "Verlustlimit: ERREICHT (" + LimitText(g_tagesLimitProz) + ")"
                             : "Verlustlimit: ok (max " + LimitText(g_tagesLimitProz) + ")",
             g_tagesLimit ? clrOrangeRed : clrLime);
   InfoZeile(7, frei ? "Status: bereit" : "Blockiert: " + grund, frei ? clrLime : clrOrange);
   color tgFarbe = clrSilver;
   string tgText = TgInfoText(tgFarbe);
   InfoZeile(8, tgText, tgFarbe);
   color dgFarbe = clrSilver;
   string dgText = DiagInfoText(dgFarbe);
   InfoZeile(9, dgText, dgFarbe);
   color rtFarbe = clrSilver;
   string rtText = RetestInfoText(rtFarbe);
   InfoZeile(10, rtText, rtFarbe);
   string h = (g_hinweis == "") ? "Hinweis: -" :
              "Hinweis (" + TimeToString(g_hinweisZeit, TIME_MINUTES) + "): " + g_hinweis;
   InfoZeile(11, h, (g_hinweis == "") ? clrSilver : clrGold);
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
      case 5: return "Kosten: " + KostenText(p.spreadPkt, p.kommPkt) + " Pkt | CRV 1:" + DoubleToString(p.crv, 2);
      case 6:
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
   RechteckSetzen(OBJ_PNL_BG, x, y, 340, 190, C'22,28,40', clrDimGray);
   for(int i = 0; i < PNL_ZEILEN; i++)
      LabelSetzen(OBJ_PNL_PRAEFIX + "z" + IntegerToString(i), x + 10, y + 8 + i * 18,
                  PanelZeileText(i), (i == 0) ? titel : clrWhite, (i == 0) ? 10 : 9);
   KnopfSetzen(OBJ_PNL_OK, x + 10,  y + 190 - 38, 150, 28, "[+] Ausführen", clrForestGreen, clrWhite);
   KnopfSetzen(OBJ_PNL_NO, x + 180, y + 190 - 38, 150, 28, "[–] Verwerfen", clrFireBrick, clrWhite);
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
      Print("ScalpScout: Signal verworfen - ", grund);
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
   double slFix    = g_sig.slFix;
   double tpFix    = g_sig.tpFix;
   long   msgId    = g_sigMsgId;
   string kopf     = g_tgKopf;
   g_sig.aktiv = false;      // gegen Doppelklick
   PanelLoeschen();

   string grund = "";
   bool   ok    = false;
   if(!HandelErlaubt(grund, atr))
   {
      HinweisSetzen("Nicht ausgeführt: " + grund);
      DiagVerworfen(grund);
      ergebnis = grund;
   }
   else if(!OrderOeffnen(richtung, atr, grund, 0.0, slFix, tpFix))
   {
      HinweisSetzen("Order fehlgeschlagen: " + grund);
      DiagVerworfen(grund);
      ergebnis = grund;
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
   Print("ScalpScout: ", text);
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
         Print("ScalpScout Telegram FEHLER 4060: URL nicht erlaubt. In MT4 Extras > Optionen > Expert Advisors ",
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
      Print("ScalpScout Telegram: ", methode, " abgelehnt (HTTP ", code, ") ", beschr);
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
   string body = "{\"chat_id\":\"" + JsonEscape(g_tgChat) + "\",\"text\":\"" + JsonEscape(html)
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
                 + ",\"text\":\"" + JsonEscape(html) + "\",\"parse_mode\":\"HTML\""
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
        + "Einstieg: " + DoubleToString(p.preis, Digits) + "\n"
        + "SL: " + DoubleToString(p.sl, Digits) + " (" + DoubleToString(p.slDist / Point, 0) + " Pkt)\n"
        + "TP: " + DoubleToString(p.tp, Digits) + " (" + DoubleToString(p.tpDist / Point, 0) + " Pkt)\n"
        + "Lot: " + DoubleToString(p.lot, ls) + "\n"
        + "Kosten: " + KostenText(p.spreadPkt, p.kommPkt) + " Pkt\n"
        + "CRV 1:" + DoubleToString(p.crv, 2);
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
   return "<b>ScalpScout " + HtmlEscape(Symbol()) + "</b> (Magic " + IntegerToString(MagicNumber) + ")\n"
        + "Modus: " + ModusText() + FernMarke(FernModusAbw()) + "\n"
        + "Risiko: " + DoubleToString(g_risiko, 1) + " %" + FernMarke(FernRisikoAbw()) + "\n"
        + "MaxLot: " + LotText(g_maxLot) + FernMarke(FernMaxLotAbw()) + " (Obergrenze " + LotText(FernMaxLotObergrenze) + ")\n"
        + "Tageslimit: " + LimitText(g_tagesLimitProz) + FernMarke(FernLimitAbw()) + "\n"
        + "Handelsfenster: " + MinutenText(g_startMin) + "-" + MinutenText(g_endeMin) + " Serverzeit"
        + FernMarke(FernZeitAbw()) + "\n"
        + "Signal: Körper &gt; " + DoubleToString(g_impulsFaktor, 2) + "×ATR" + FernMarke(FernImpulsAbw()) + "\n"
        + "Signal: Volumen &gt; " + DoubleToString(g_volumenFaktor, 2) + "×Ø" + FernMarke(FernVolumenAbw()) + "\n"
        + "Signal: Ausbruch über " + IntegerToString(g_breakoutKerzen) + " Kerzen" + FernMarke(FernAusbruchAbw())
        + ", Trendfilter " + (TrendFilterAktiv ? "an (EMA " + IntegerToString(EMA_Periode) + ")" : "aus") + "\n"
        + "Einstieg: " + EinstiegName(g_einstieg) + FernMarke(FernEinstiegAbw()) + "\n"
        + "Retest: Rücklauf " + DoubleToString(g_retestAnteil, 2) + "×Körper" + FernMarke(FernRetestAbw())
        + ", max " + IntegerToString(g_retestMaxKerzen) + " Kerzen" + FernMarke(FernRetestKerzenAbw())
        + ", SL-Puffer " + DoubleToString(RetestSLPufferATR, 2) + "×ATR, TP " + DoubleToString(g_retestTPCRV, 2)
        + "×SL" + FernMarke(FernCrvAbw()) + "\n"
        + (g_rt.aktiv ? "Retest wartet: " + RetestWartetText() + "\n" : "")
        + "Break-even: " + (g_beAktiv ? "an" : "aus") + FernMarke(FernBeAbw()) + ", Trailing: "
        + (g_trailingAktiv ? "an" : "aus") + FernMarke(FernTrailAbw()) + "\n"
        + "Tagesbericht: " + BerichtZeitText(g_berichtMin) + FernMarke(FernBerichtAbw()) + "\n"
        + "Konto: Kontostand " + DoubleToString(AccountBalance(), 2) + ", Equity " + DoubleToString(AccountEquity(), 2)
        + ", freie Margin " + DoubleToString(AccountFreeMargin(), 2) + " " + AccountCurrency() + "\n"
        + "Kosten: " + KostenText(sp, ko) + " / max " + DoubleToString(maxSp, 1) + " Pkt\n"
        + "Tagesergebnis: " + DoubleToString(diff, 2) + " " + AccountCurrency() + " (" + DoubleToString(proz, 2) + " %)\n"
        + "Offene Positionen: " + IntegerToString(ZaehlePositionen()) + " ("
        + DoubleToString(OffenerGewinn(), 2) + " " + AccountCurrency() + ")\n"
        + status;
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

// Befehlsübersicht mit aktuellen Werten
string TgHilfeText()
{
   return "<b>ScalpScout Befehle</b> (" + HtmlEscape(Symbol()) + ", Magic " + IntegerToString(MagicNumber) + ")\n"
        + "/status - Zustand, Konto und alle Einstellungen\n"
        + "/diag - Auswertung der letzten Kerze und Zähler seit Start\n"
        + "/modus manuell|signale|auto - Betriebsart, jetzt: " + ModusText()
        + " (auto nur nach Bestätigung per Knopf)\n"
        + "/risiko X - Risiko je Trade in % (0.1-25), jetzt " + DoubleToString(g_risiko, 1) + "\n"
        + "/maxlot X - Lot-Deckel (" + LotText(MinLotWert()) + " bis " + LotText(MaxLotGrenze()) + "), jetzt "
        + LotText(g_maxLot) + "\n"
        + "/limit X|aus - Tagesverlust-Limit in % (1-100), jetzt " + LimitText(g_tagesLimitProz) + "\n"
        + "/zeit HH:MM-HH:MM - Handelsfenster in Serverzeit, jetzt " + MinutenText(g_startMin) + "-"
        + MinutenText(g_endeMin) + "\n"
        + "/koerper X - Kerzenkörper-Faktor (0.5-4.0), jetzt " + DoubleToString(g_impulsFaktor, 2) + "\n"
        + "/volumen X - Volumen-Faktor (0.8-4.0), jetzt " + DoubleToString(g_volumenFaktor, 2) + "\n"
        + "/ausbruch N - Ausbruch über N Kerzen (2-50), jetzt " + IntegerToString(g_breakoutKerzen) + "\n"
        + "/einstieg retest|sofort - Einstiegsart, jetzt " + EinstiegName(g_einstieg) + "\n"
        + "/retest X - Retest: Rücklauf in Anteil des Signalkerzen-Körpers (0.2-0.8), jetzt "
        + DoubleToString(g_retestAnteil, 2) + "\n"
        + "/retestkerzen N - Retest verfällt nach N Kerzen (1-15), jetzt " + IntegerToString(g_retestMaxKerzen) + "\n"
        + "/crv X - Retest: TP = x × SL-Abstand (1.0-4.0), jetzt " + DoubleToString(g_retestTPCRV, 2) + "\n"
        + "/be an|aus - Break-even, jetzt " + (g_beAktiv ? "an" : "aus") + "\n"
        + "/trailing an|aus - Trailing-Stop, jetzt " + (g_trailingAktiv ? "an" : "aus") + "\n"
        + "/bericht [HH:MM|aus] - Tagesbericht sofort bzw. Uhrzeit setzen, jetzt " + BerichtZeitText(g_berichtMin) + "\n"
        + "/kauf [lot] und /verkauf [lot] - Hand-Trade mit Vorschau und Bestätigung (30 s)\n"
        + "/zu ticket - eine Position schließen (mit Bestätigung)\n"
        + "/sl ticket preis|be und /tp ticket preis - Stop-Loss bzw. Take-Profit ändern\n"
        + "/positionen - offene Positionen\n"
        + "/heute - heute geschlossene Trades\n"
        + "/schliessen - alle Positionen schließen (mit Bestätigung)\n"
        + "/stop und /start - Signale pausieren bzw. freigeben (/start löst auch die Kill-Switch-Sperre, mit Bestätigung)\n"
        + "/reset - Fern-Einstellungen löschen, Inputs gelten wieder\n"
        + "Dezimaltrenner: Komma oder Punkt.";
}

// Ergebnis der letzten Kerzen-Auswertung und Zähler seit Start
string TgDiagText()
{
   string s = "<b>Diagnose " + HtmlEscape(Symbol()) + "</b>\n";
   if(g_dgZeit == 0)
      s += "Noch keine Kerze ausgewertet - die erste Auswertung kommt mit der nächsten neuen M1-Kerze.\n";
   else if(!g_dgGueltig)
      s += "Kerze " + TimeToString(g_dgZeit, TIME_DATE | TIME_MINUTES) + " (Serverzeit)\n" + HtmlEscape(g_dgErgebnis) + "\n";
   else
   {
      string r = (g_dgRichtung > 0) ? "LONG" : "SHORT";
      s += "Kerze " + TimeToString(g_dgZeit, TIME_DATE | TIME_MINUTES) + " (Serverzeit), Richtung geprüft: " + r + "\n"
         + "Körper: " + DoubleToString(g_dgKoerperX, 2) + "×ATR (Soll &gt; " + DoubleToString(g_impulsFaktor, 2) + ") "
         + HaekchenText(g_dgKoerperOK) + "\n"
         + "Volumen: " + DoubleToString(g_dgVolX, 2) + "×Ø (Soll &gt; " + DoubleToString(g_volumenFaktor, 2) + ") "
         + HaekchenText(g_dgVolOK) + "\n"
         + "Kerze in Richtung " + r + ": " + HaekchenText(g_dgFarbeOK) + "\n"
         + "Ausbruch (" + IntegerToString(g_breakoutKerzen) + " Kerzen): " + HaekchenText(g_dgAusbruchOK) + "\n"
         + "Trend/EMA: " + (TrendFilterAktiv ? HaekchenText(g_dgTrendOK) : "✓ (Filter aus)") + "\n"
         + "Kosten: " + DoubleToString(g_dgKostenIst, 1) + " / max " + DoubleToString(g_dgKostenMax, 1) + " Pkt "
         + HaekchenText(g_dgKostenOK) + "\n"
         + "Filter: " + HtmlEscape(g_dgFilter) + "\n";
   }
   if(g_dgErgebnis != "" && g_dgGueltig)
      s += "<b>Ergebnis: " + HtmlEscape(g_dgErgebnis) + "</b>\n";
   s += "Seit Start: " + IntegerToString(g_dgKerzen) + " Kerzen, " + IntegerToString(g_dgSignale) + " Signale, "
      + IntegerToString(g_dgTrades) + " Trades, " + IntegerToString(g_dgVerworfen) + " verworfen";
   int best = -1;
   for(int i = 0; i < g_dgGrundAnz; i++)
   {
      if(best < 0 || g_dgGrundN[i] > g_dgGrundN[best])
         best = i;
   }
   if(best >= 0)
      s += "\nHäufigster Grund: " + HtmlEscape(g_dgGrund[best]) + " (" + IntegerToString(g_dgGrundN[best]) + "×)";
   s += "\nEinstieg: " + EinstiegName(g_einstieg);
   if(g_einstieg == EINSTIEG_RETEST)
      s += " (Rücklauf " + DoubleToString(g_retestAnteil, 2) + "×Körper, max " + IntegerToString(g_retestMaxKerzen)
         + " Kerzen, SL-Puffer " + DoubleToString(RetestSLPufferATR, 2) + "×ATR, TP " + DoubleToString(g_retestTPCRV, 2) + "×SL)";
   if(g_rt.aktiv)
      s += "\nRetest wartet: " + RetestWartetText() + ", Abbruch bei "
         + ((g_rt.richtung > 0) ? "Bid unter " + DoubleToString(g_rt.kLow, Digits)
                                : "Bid über " + DoubleToString(g_rt.kHigh, Digits));
   else
      s += "\nRetest wartet: kein Signal";
   s += "\nRetest seit Start: " + IntegerToString(g_rtErreicht) + " erreicht, " + IntegerToString(g_rtVerfallen)
      + " verfallen, " + IntegerToString(g_rtAbgebrochen) + " abgebrochen (Ausbruch gescheitert)";
   return s;
}

// Offene eigene Positionen (Symbol + Magic)
string TgPositionenText()
{
   string zeilen = "";
   int    n      = 0;
   double summe  = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber || OrderType() > OP_SELL)
         continue;
      double gw = OrderProfit() + OrderSwap() + OrderCommission();
      summe += gw;
      n++;
      if(n <= 25)
         zeilen += "#" + IntegerToString(OrderTicket()) + " " + (OrderType() == OP_BUY ? "BUY " : "SELL ")
                   + LotText(OrderLots()) + " @" + DoubleToString(OrderOpenPrice(), Digits)
                   + " SL " + (OrderStopLoss() > 0.0 ? DoubleToString(OrderStopLoss(), Digits) : "-")
                   + " TP " + (OrderTakeProfit() > 0.0 ? DoubleToString(OrderTakeProfit(), Digits) : "-")
                   + " | " + GeldText(gw) + "\n";
   }
   if(n == 0)
      return "Keine offenen Positionen (" + HtmlEscape(Symbol()) + ", Magic " + IntegerToString(MagicNumber) + ").";
   return "<b>Offene Positionen " + HtmlEscape(Symbol()) + "</b>\n" + zeilen + "Summe: " + GeldText(summe);
}

// Heute (Serverzeit-Tag) geschlossene Trades dieses EAs aus der Kontohistorie
string TgHeuteText()
{
   datetime tag0 = (datetime)((long)TimeCurrent() / 86400 * 86400);
   int    n = 0, gew = 0, verl = 0, tBest = 0, tSchlecht = 0;
   double summe = 0.0, best = 0.0, schlecht = 0.0;
   for(int i = OrdersHistoryTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol() || OrderType() > OP_SELL)
         continue;
      if(OrderCloseTime() < tag0)
         continue;
      double gw = OrderProfit() + OrderSwap() + OrderCommission();
      if(n == 0 || gw > best)
      {
         best  = gw;
         tBest = OrderTicket();
      }
      if(n == 0 || gw < schlecht)
      {
         schlecht   = gw;
         tSchlecht  = OrderTicket();
      }
      n++;
      summe += gw;
      if(gw > 0.0)
         gew++;
      else if(gw < 0.0)
         verl++;
   }
   if(n == 0)
      return "Heute noch keine geschlossenen Trades (" + HtmlEscape(Symbol()) + ", Magic " + IntegerToString(MagicNumber)
             + "). Hinweis: Die Kontohistorie muss im Terminal geladen sein.";
   return "<b>Heute geschlossen " + HtmlEscape(Symbol()) + "</b>\n"
        + IntegerToString(n) + " Trades: " + IntegerToString(gew) + " Gewinner, " + IntegerToString(verl) + " Verlierer\n"
        + "Summe: " + GeldText(summe) + "\n"
        + "Bester: #" + IntegerToString(tBest) + " " + GeldText(best) + "\n"
        + "Schlechtester: #" + IntegerToString(tSchlecht) + " " + GeldText(schlecht);
}

// Tastatur mit zwei Knöpfen für Bestätigungen
string TgTastaturCfg(string textJa, string dataJa, string textNein, string dataNein)
{
   return "{\"inline_keyboard\":[[{\"text\":\"" + JsonEscape(textJa) + "\",\"callback_data\":\"" + dataJa + "\"},"
          + "{\"text\":\"" + JsonEscape(textNein) + "\",\"callback_data\":\"" + dataNein + "\"}]]}";
}

// Offene Bestätigungs-Anfragen, deren 60 Sekunden um sind: Nachricht ändern, Knöpfe entfernen
void TgCfgAblaufPruefen()
{
   if(g_cfgAutoMsg > 0 && TimeLocal() > g_cfgAutoBis)
   {
      long m = g_cfgAutoMsg;
      g_cfgAutoMsg = 0;
      TgNachrichtBearbeiten(m, "⌛ Bestätigung abgelaufen (60 s) - Modus unverändert.");
   }
   if(g_cfgSchlMsg > 0 && TimeLocal() > g_cfgSchlBis)
   {
      long m = g_cfgSchlMsg;
      g_cfgSchlMsg = 0;
      TgNachrichtBearbeiten(m, "⌛ Bestätigung abgelaufen (60 s) - nichts geschlossen.");
   }
   if(g_cfgZuMsg > 0 && TimeLocal() > g_cfgZuBis)
   {
      long m = g_cfgZuMsg;
      g_cfgZuMsg = 0;
      TgNachrichtBearbeiten(m, "⌛ Bestätigung abgelaufen (60 s) - Position bleibt offen.");
   }
   if(g_cfgHandMsg > 0 && TimeLocal() > g_cfgHandBis)
   {
      long m = g_cfgHandMsg;
      g_cfgHandMsg = 0;
      TgNachrichtBearbeiten(m, "⌛ Bestätigung abgelaufen (30 s) - kein Trade eröffnet.");
   }
   if(g_cfgStartMsg > 0 && TimeLocal() > g_cfgStartBis)
   {
      long m = g_cfgStartMsg;
      g_cfgStartMsg = 0;
      TgNachrichtBearbeiten(m, "⌛ Bestätigung abgelaufen (60 s) - Sperre bleibt.");
   }
}

// Knopfdruck "cfg_..." (Bestätigung Vollautomatik / Alle schließen). msgId = Nachricht mit den Knöpfen.
void TgCfgCallback(string cbId, string data, long msgId)
{
   if(data == "cfg_auto_ja" || data == "cfg_auto_nein")
   {
      if(g_cfgAutoMsg <= 0 || msgId != g_cfgAutoMsg)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         if(msgId > 0)
            TgNachrichtBearbeiten(msgId, "⌛ Anfrage nicht mehr gültig.");
         return;
      }
      g_cfgAutoMsg = 0;
      if(TimeLocal() > g_cfgAutoBis)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         TgNachrichtBearbeiten(msgId, "⌛ Bestätigung abgelaufen (60 s) - Modus unverändert.");
         return;
      }
      if(data == "cfg_auto_ja")
      {
         ModusSetzen(VOLLAUTOMATIK);
         Print("ScalpScout Fern: Modus → Vollautomatik (per Telegram bestätigt)");
         TgCallbackAntwort(cbId, "Vollautomatik an");
         TgNachrichtBearbeiten(msgId, "✅ Vollautomatik eingeschaltet. Wechsel zurück: /modus manuell oder /modus signale. "
                                      + "Nach einem Neustart gilt wieder der Input-Modus.");
      }
      else
      {
         TgCallbackAntwort(cbId, "abgebrochen");
         TgNachrichtBearbeiten(msgId, "❌ Abgebrochen - Modus unverändert (" + ModusText() + ").");
      }
      UiAktualisieren();
      return;
   }

   if(data == "cfg_schl_ja" || data == "cfg_schl_nein")
   {
      if(g_cfgSchlMsg <= 0 || msgId != g_cfgSchlMsg)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         if(msgId > 0)
            TgNachrichtBearbeiten(msgId, "⌛ Anfrage nicht mehr gültig.");
         return;
      }
      g_cfgSchlMsg = 0;
      if(TimeLocal() > g_cfgSchlBis)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         TgNachrichtBearbeiten(msgId, "⌛ Bestätigung abgelaufen (60 s) - nichts geschlossen.");
         return;
      }
      if(data == "cfg_schl_ja")
      {
         TgCallbackAntwort(cbId, "schließe ...");
         Print("ScalpScout Fern: Alle schließen (per Telegram bestätigt)");
         int gz = 0, fe = 0;
         AlleSchliessen(gz, fe);
         TgNachrichtBearbeiten(msgId, "✅ Alle schließen ausgeführt: " + IntegerToString(gz) + " geschlossen, "
                                      + IntegerToString(fe) + " Fehler. Neue Trades sind gesperrt - mit /start wieder freigeben.");
      }
      else
      {
         TgCallbackAntwort(cbId, "abgebrochen");
         TgNachrichtBearbeiten(msgId, "❌ Abgebrochen - nichts geschlossen.");
      }
      UiAktualisieren();
      return;
   }
   if(StringFind(data, "cfg_zu_") == 0)
   {
      string rest = StringSubstr(data, 7);
      int    us   = StringFind(rest, "_");
      int    tk   = (us > 0) ? (int)StringToInteger(StringSubstr(rest, 0, us)) : 0;
      string ans  = (us > 0) ? StringSubstr(rest, us + 1) : "";
      if(g_cfgZuMsg <= 0 || msgId != g_cfgZuMsg || tk != g_cfgZuTicket || (ans != "ja" && ans != "nein"))
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         if(msgId > 0)
            TgNachrichtBearbeiten(msgId, "⌛ Anfrage nicht mehr gültig.");
         return;
      }
      g_cfgZuMsg = 0;
      if(TimeLocal() > g_cfgZuBis)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         TgNachrichtBearbeiten(msgId, "⌛ Bestätigung abgelaufen (60 s) - Position bleibt offen.");
         return;
      }
      if(ans == "ja")
      {
         TgCallbackAntwort(cbId, "schließe ...");
         string fe = "";
         if(PositionSchliessen(tk, fe))
            TgNachrichtBearbeiten(msgId, "✅ Position #" + IntegerToString(tk) + " geschlossen.");
         else
            TgNachrichtBearbeiten(msgId, "⚠️ #" + IntegerToString(tk) + " nicht geschlossen: " + HtmlEscape(fe));
      }
      else
      {
         TgCallbackAntwort(cbId, "abgebrochen");
         TgNachrichtBearbeiten(msgId, "❌ Abgebrochen - Position #" + IntegerToString(tk) + " bleibt offen.");
      }
      UiAktualisieren();
      return;
   }

   if(data == "cfg_hand_ja" || data == "cfg_hand_nein")
   {
      if(g_cfgHandMsg <= 0 || msgId != g_cfgHandMsg)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         if(msgId > 0)
            TgNachrichtBearbeiten(msgId, "⌛ Anfrage nicht mehr gültig.");
         return;
      }
      g_cfgHandMsg = 0;
      if(TimeLocal() > g_cfgHandBis)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         TgNachrichtBearbeiten(msgId, "⌛ Bestätigung abgelaufen (30 s) - kein Trade eröffnet.");
         return;
      }
      if(data == "cfg_hand_ja")
      {
         TgCallbackAntwort(cbId, "sende Order ...");
         Print("ScalpScout Fern: Hand-Trade ", (g_cfgHandRicht > 0 ? "KAUF" : "VERKAUF"), " (per Telegram bestätigt)");
         TgNachrichtBearbeiten(msgId, TgHandAusfuehren());
      }
      else
      {
         TgCallbackAntwort(cbId, "abgebrochen");
         TgNachrichtBearbeiten(msgId, "❌ Abgebrochen - kein Trade eröffnet.");
      }
      UiAktualisieren();
      return;
   }

   if(data == "cfg_start_ja" || data == "cfg_start_nein")
   {
      if(g_cfgStartMsg <= 0 || msgId != g_cfgStartMsg)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         if(msgId > 0)
            TgNachrichtBearbeiten(msgId, "⌛ Anfrage nicht mehr gültig.");
         return;
      }
      g_cfgStartMsg = 0;
      if(TimeLocal() > g_cfgStartBis)
      {
         TgCallbackAntwort(cbId, "abgelaufen");
         TgNachrichtBearbeiten(msgId, "⌛ Bestätigung abgelaufen (60 s) - Sperre bleibt.");
         return;
      }
      if(data == "cfg_start_ja")
      {
         g_gestoppt = false;
         g_tgPause  = false;
         HinweisSetzen("Kill-Switch-Sperre per Telegram gelöst");
         Print("ScalpScout Fern: Kill-Switch-Sperre gelöst (per Telegram bestätigt)");
         TgCallbackAntwort(cbId, "Sperre gelöst");
         TgNachrichtBearbeiten(msgId, "✅ Kill-Switch-Sperre gelöst, neue Trades sind wieder erlaubt.");
      }
      else
      {
         TgCallbackAntwort(cbId, "abgebrochen");
         TgNachrichtBearbeiten(msgId, "❌ Abgebrochen - Sperre bleibt, bis /start bestätigt wird.");
      }
      UiAktualisieren();
      return;
   }
   TgCallbackAntwort(cbId, "unbekannt");
}

// Änderung melden: Journal + Telegram + Oberfläche
void TgGeaendert(string name, string alt, string neu)
{
   string z = name + ": " + alt + " → " + neu;
   Print("ScalpScout Fern: ", z, " (per Telegram)");
   TgNachrichtSenden("✅ " + HtmlEscape(z), "");
   UiAktualisieren();
}

// Zahl prüfen (Bereich mn..mx). Bei Fehler Meldung mit erlaubtem Bereich, Rückgabe false.
bool TgBereichOK(string cmd, string arg, double mn, double mx, int dez, string einheit, double &w)
{
   if(ZahlLesen(arg, w) && w >= mn - 1e-9 && w <= mx + 1e-9)
   {
      w = MathMax(mn, MathMin(mx, w));
      return true;
   }
   TgNachrichtSenden("⚠️ " + cmd + ": " + ((arg == "") ? "Wert fehlt" : "ungültiger Wert '" + HtmlEscape(arg) + "'")
                     + ". Erlaubt: " + DoubleToString(mn, dez) + " bis " + DoubleToString(mx, dez) + einheit + ".", "");
   return false;
}

// Einstellbefehle /risiko /maxlot /limit /zeit /koerper /volumen /ausbruch /einstieg /retest /retestkerzen /crv.
// true = Befehl erkannt.
bool TgEinstellung(string cmd, string arg)
{
   double w = 0.0;
   string alt;

   if(cmd == "/risiko")
   {
      if(!TgBereichOK(cmd, arg, 0.1, 25.0, 1, " %", w))
         return true;
      w   = NormalizeDouble(w, 2);
      alt = DoubleToString(g_risiko, 1) + " %";
      g_risiko = w;
      FernSpeichern("risiko", g_risiko);
      TgGeaendert("Risiko", alt, DoubleToString(g_risiko, 1) + " %");
      return true;
   }
   if(cmd == "/maxlot")
   {
      double mn = MinLotWert();
      double mx = MaxLotGrenze();
      if(mx < mn - 1e-9)
      {
         TgNachrichtSenden("⚠️ /maxlot: Obergrenze (" + LotText(mx) + ") liegt unter MinLot (" + LotText(mn)
                           + ") - nicht änderbar.", "");
         return true;
      }
      if(!TgBereichOK(cmd, arg, mn, mx, LotStellenAktuell(), " Lot", w))
         return true;
      double l = LotAbrunden(w);
      if(l < mn - 1e-9)
         l = mn;
      alt = LotText(g_maxLot) + " Lot";
      g_maxLot = l;
      FernSpeichern("maxlot", g_maxLot);
      TgGeaendert("MaxLot", alt, LotText(g_maxLot) + " Lot");
      return true;
   }
   if(cmd == "/limit")
   {
      if(arg == "aus" || arg == "off" || arg == "0")
         w = 0.0;
      else if(!TgBereichOK(cmd, arg, 1.0, 100.0, 0, " % (oder 'aus')", w))
         return true;
      w   = NormalizeDouble(w, 2);
      alt = LimitText(g_tagesLimitProz);
      g_tagesLimitProz = w;
      FernSpeichern("limit", g_tagesLimitProz);
      g_tagesLimit = false;       // mit neuem Limit neu bewerten (rastet bei Überschreitung sofort wieder ein)
      TagPruefen();
      TgGeaendert("Tageslimit", alt, LimitText(g_tagesLimitProz)
                  + (g_tagesLimit ? " (heute schon erreicht - Sperre bleibt)" : ""));
      return true;
   }
   if(cmd == "/zeit")
   {
      int sp = StringFind(arg, "-");
      int a = -1, b = -1;
      if(sp > 0)
      {
         a = ZeitLesen(StringSubstr(arg, 0, sp));
         b = ZeitLesen(StringSubstr(arg, sp + 1));
      }
      if(a < 0 || b < 0)
      {
         TgNachrichtSenden("⚠️ /zeit: Format HH:MM-HH:MM erwartet (Serverzeit), z. B. /zeit 08:00-20:00. "
                           + "Gleiche Start- und Endzeit = durchgehend.", "");
         return true;
      }
      alt = MinutenText(g_startMin) + "-" + MinutenText(g_endeMin);
      g_startMin = a;
      g_endeMin  = b;
      FernSpeichern("start", a);
      FernSpeichern("ende", b);
      TgGeaendert("Handelsfenster", alt, MinutenText(a) + "-" + MinutenText(b) + " Serverzeit");
      return true;
   }
   if(cmd == "/koerper" || cmd == "/körper")
   {
      if(!TgBereichOK(cmd, arg, 0.5, 4.0, 1, " (×ATR)", w))
         return true;
      w   = NormalizeDouble(w, 2);
      alt = DoubleToString(g_impulsFaktor, 2) + "×ATR";
      g_impulsFaktor = w;
      FernSpeichern("impuls", g_impulsFaktor);
      TgGeaendert("Körper-Faktor", alt, DoubleToString(g_impulsFaktor, 2) + "×ATR");
      return true;
   }
   if(cmd == "/volumen")
   {
      if(!TgBereichOK(cmd, arg, 0.8, 4.0, 1, " (×Durchschnitt)", w))
         return true;
      w   = NormalizeDouble(w, 2);
      alt = DoubleToString(g_volumenFaktor, 2) + "×Ø";
      g_volumenFaktor = w;
      FernSpeichern("volumen", g_volumenFaktor);
      TgGeaendert("Volumen-Faktor", alt, DoubleToString(g_volumenFaktor, 2) + "×Ø");
      return true;
   }
   if(cmd == "/ausbruch")
   {
      if(!TgBereichOK(cmd, arg, 2.0, 50.0, 0, " Kerzen (ganze Zahl)", w))
         return true;
      if(MathAbs(w - MathRound(w)) > 1e-9)
      {
         TgNachrichtSenden("⚠️ /ausbruch: ganze Zahl von 2 bis 50 erwartet.", "");
         return true;
      }
      alt = IntegerToString(g_breakoutKerzen) + " Kerzen";
      g_breakoutKerzen = (int)MathRound(w);
      FernSpeichern("ausbruch", g_breakoutKerzen);
      TgGeaendert("Ausbruch", alt, IntegerToString(g_breakoutKerzen) + " Kerzen");
      return true;
   }
   if(cmd == "/einstieg")
   {
      ENUM_EINSTIEG neu = g_einstieg;
      if(arg == "retest")
         neu = EINSTIEG_RETEST;
      else if(arg == "sofort")
         neu = EINSTIEG_SOFORT;
      else
      {
         TgNachrichtSenden("⚠️ /einstieg: retest oder sofort erwartet. Aktuell: " + EinstiegName(g_einstieg) + ".", "");
         return true;
      }
      if(neu == g_einstieg)
      {
         TgNachrichtSenden("Einstiegsart ist bereits: " + EinstiegName(g_einstieg), "");
         return true;
      }
      alt = EinstiegName(g_einstieg);
      g_einstieg = neu;
      FernSpeichern("einstieg", (double)g_einstieg);
      if(g_einstieg != EINSTIEG_RETEST)
         RetestLoeschen("Einstiegsart auf Sofort gestellt");
      TgGeaendert("Einstieg", alt, EinstiegName(g_einstieg));
      return true;
   }
   if(cmd == "/retest")
   {
      if(!TgBereichOK(cmd, arg, 0.2, 0.8, 2, " (Anteil des Signalkerzen-Körpers)", w))
         return true;
      w   = NormalizeDouble(w, 2);
      alt = DoubleToString(g_retestAnteil, 2);
      g_retestAnteil = w;
      FernSpeichern("retest", g_retestAnteil);
      TgGeaendert("Retest-Anteil", alt, DoubleToString(g_retestAnteil, 2) + " (gilt ab dem nächsten Signal)");
      return true;
   }
   if(cmd == "/retestkerzen")
   {
      if(!TgBereichOK(cmd, arg, 1.0, 15.0, 0, " Kerzen (ganze Zahl)", w))
         return true;
      if(MathAbs(w - MathRound(w)) > 1e-9)
      {
         TgNachrichtSenden("⚠️ /retestkerzen: ganze Zahl von 1 bis 15 erwartet.", "");
         return true;
      }
      alt = IntegerToString(g_retestMaxKerzen) + " Kerzen";
      g_retestMaxKerzen = (int)MathRound(w);
      FernSpeichern("retestk", g_retestMaxKerzen);
      TgGeaendert("Retest-Kerzen", alt, IntegerToString(g_retestMaxKerzen) + " Kerzen (gilt ab dem nächsten Signal)");
      return true;
   }
   if(cmd == "/crv")
   {
      if(!TgBereichOK(cmd, arg, 1.0, 4.0, 1, " (×SL-Abstand, nur Retest-TP)", w))
         return true;
      w   = NormalizeDouble(w, 2);
      alt = DoubleToString(g_retestTPCRV, 2);
      g_retestTPCRV = w;
      FernSpeichern("crv", g_retestTPCRV);
      TgGeaendert("Retest-CRV", alt, DoubleToString(g_retestTPCRV, 2));
      return true;
   }
   return false;
}

// /modus manuell | signale | auto
void TgModusBefehl(string arg)
{
   if(arg == "manuell" || arg == "freigabe")
   {
      if(g_modus == MANUELLE_FREIGABE)
      {
         TgNachrichtSenden("Modus ist bereits: " + ModusText(), "");
         return;
      }
      string alt = ModusText();
      ModusSetzen(MANUELLE_FREIGABE);
      TgGeaendert("Modus", alt, ModusText());
   }
   else if(arg == "signale" || arg == "signal")
   {
      if(g_modus == NUR_SIGNALE)
      {
         TgNachrichtSenden("Modus ist bereits: " + ModusText(), "");
         return;
      }
      string alt = ModusText();
      ModusSetzen(NUR_SIGNALE);
      TgGeaendert("Modus", alt, ModusText());
   }
   else if(arg == "auto" || arg == "vollautomatik" || arg == "automatik")
   {
      if(g_modus == VOLLAUTOMATIK)
      {
         TgNachrichtSenden("Modus ist bereits: " + ModusText(), "");
         return;
      }
      if(g_cfgAutoMsg > 0)      // frühere offene Anfrage ersetzen
         TgNachrichtBearbeiten(g_cfgAutoMsg, "⌛ ersetzt durch neue Anfrage.");
      g_cfgAutoMsg = TgNachrichtSenden("⚠️ <b>Vollautomatik</b> einschalten?\nDer EA eröffnet dann Trades selbst, ohne Freigabe "
                                       + "(Risiko " + DoubleToString(g_risiko, 1) + " %, MaxLot " + LotText(g_maxLot)
                                       + ").\nBestätigung gilt 60 Sekunden.",
                                       TgTastaturCfg("✅ Vollautomatik einschalten", "cfg_auto_ja",
                                                     "❌ Abbrechen", "cfg_auto_nein"));
      g_cfgAutoBis = TimeLocal() + 60;
   }
   else
      TgNachrichtSenden("⚠️ /modus: manuell, signale oder auto erwartet. Aktuell: " + ModusText() + ".", "");
}

// /schliessen: erst Rückfrage per Knöpfe (die Ausführung kommt aus TgCfgCallback)
void TgSchliessenAnfrage()
{
   int n = ZaehlePositionen();
   if(n == 0)
   {
      TgNachrichtSenden("Keine offenen Positionen - nichts zu schließen.", "");
      return;
   }
   if(g_cfgSchlMsg > 0)
      TgNachrichtBearbeiten(g_cfgSchlMsg, "⌛ ersetzt durch neue Anfrage.");
   g_cfgSchlMsg = TgNachrichtSenden("⚠️ <b>Alle " + IntegerToString(n) + " Position(en)</b> auf " + HtmlEscape(Symbol())
                                    + " jetzt schließen? Aktuell " + GeldText(OffenerGewinn())
                                    + ".\nDanach sind neue Trades gesperrt - mit /start wieder freigeben.\n"
                                      + "Bestätigung gilt 60 Sekunden.",
                                    TgTastaturCfg("✅ Alle schließen", "cfg_schl_ja", "❌ Abbrechen", "cfg_schl_nein"));
   g_cfgSchlBis = TimeLocal() + 60;
}

// /reset: Fern-Einstellungen löschen, Inputs gelten wieder
void TgReset()
{
   string abw = FernAbweichungen();
   FernAlleLoeschen();
   ENUM_MODUS alt = g_modus;
   FernInputsUebernehmen();
   if(g_einstieg != EINSTIEG_RETEST)
      RetestLoeschen("Reset");
   if(g_berichtMin >= 0 && TimeHour(TimeCurrent()) * 60 + TimeMinute(TimeCurrent()) >= g_berichtMin)
      g_berichtTag = (datetime)((long)TimeCurrent() / 86400 * 86400);   // heute nicht nachträglich senden
   if(alt != g_modus && g_modus != MANUELLE_FREIGABE && g_sig.aktiv)
      SignalVerwerfen("Reset", "⌛ verworfen (Reset)");
   g_tagesLimit = false;        // mit dem Input-Limit neu bewerten
   TagPruefen();
   g_fernInfo = "";
   HinweisSetzen("Fern-Einstellungen zurückgesetzt");
   Print("ScalpScout Fern: Reset, Inputs aktiv (", WerteText(), ")");
   TgNachrichtSenden("♻️ Fern-Einstellungen gelöscht, die Inputs gelten wieder.\n"
                     + ((abw == "") ? "Es gab keine Fern-Änderungen.\n" : "Zurückgesetzt wurden: " + HtmlEscape(abw) + "\n")
                     + "Jetzt aktiv: " + HtmlEscape(WerteText()), "");
   UiAktualisieren();
}

//+------------------------------------------------------------------+
//| Fernsteuerung Teil 2: Einzelpositionen, Hand-Trades, Bericht     |
//+------------------------------------------------------------------+
// Ticket aus Text lesen (ganze positive Zahl)
bool TicketLesen(string s, int &ticket)
{
   double w = 0.0;
   if(!ZahlLesen(s, w) || w < 1.0 || w > 2147483000.0 || MathAbs(w - MathRound(w)) > 1e-9)
      return false;
   ticket = (int)MathRound(w);
   return true;
}

// Wählt das Ticket aus, wenn es eine offene Position dieses EAs ist (Symbol + Magic)
bool EigenePositionWaehlen(int ticket)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET))
      return false;
   return (OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber && OrderType() <= OP_SELL
           && OrderCloseTime() == 0);
}

// Eine Position schließen (3 Versuche), ohne MessageBox und ohne Sperre neuer Trades
bool PositionSchliessen(int ticket, string &fehler)
{
   fehler = "";
   if(!EigenePositionWaehlen(ticket))
   {
      fehler = "Ticket nicht (mehr) offen";
      return false;
   }
   int    typ   = OrderType();
   double lots  = OrderLots();
   int    slip  = SlippagePunkte();
   int    err   = 0;
   for(int v = 1; v <= 3; v++)
   {
      RefreshRates();
      double preis = (typ == OP_BUY) ? Bid : Ask;
      ResetLastError();
      if(OrderClose(ticket, lots, preis, slip, clrOrange))
      {
         Print("ScalpScout: Position #", ticket, " geschlossen (per Telegram)");
         return true;
      }
      err = GetLastError();
      LogFehler("OrderClose #" + IntegerToString(ticket) + " (Versuch " + IntegerToString(v) + ")", err);
      if(!IsTesting())
         Sleep(200);
      if(!OrderSelect(ticket, SELECT_BY_TICKET) || OrderCloseTime() > 0)
         break;
   }
   fehler = FehlerText(err) + " (" + IntegerToString(err) + ")";
   return false;
}

// /zu <ticket>: Rückfrage mit Knöpfen (60 s)
void TgZuAnfrage(string arg)
{
   int ticket = 0;
   if(!TicketLesen(arg, ticket))
   {
      TgNachrichtSenden("⚠️ /zu: Ticketnummer erwartet, z. B. /zu 12345678 (siehe /positionen).", "");
      return;
   }
   if(!EigenePositionWaehlen(ticket))
   {
      TgNachrichtSenden("⚠️ /zu: #" + IntegerToString(ticket) + " ist keine offene Position dieses EAs (Symbol, Magic).", "");
      return;
   }
   double gw = OrderProfit() + OrderSwap() + OrderCommission();
   string txt = "#" + IntegerToString(ticket) + " " + (OrderType() == OP_BUY ? "BUY " : "SELL ") + LotText(OrderLots())
                + " @" + DoubleToString(OrderOpenPrice(), Digits) + " | " + GeldText(gw);
   if(g_cfgZuMsg > 0)
      TgNachrichtBearbeiten(g_cfgZuMsg, "⌛ ersetzt durch neue Anfrage.");
   g_cfgZuTicket = ticket;
   g_cfgZuMsg = TgNachrichtSenden("⚠️ Position schließen?\n" + HtmlEscape(txt) + "\nBestätigung gilt 60 Sekunden.",
                                  TgTastaturCfg("✅ Schließen", "cfg_zu_" + IntegerToString(ticket) + "_ja",
                                                "❌ Abbrechen", "cfg_zu_" + IntegerToString(ticket) + "_nein"));
   g_cfgZuBis = TimeLocal() + 60;
}

// /sl und /tp: <ticket> <preis>   bzw.   /sl <ticket> be
void TgSlTpBefehl(string cmd, string arg)
{
   bool istSL = (cmd == "/sl");
   int sp = StringFind(arg, " ");
   string a1 = arg, a2 = "";
   if(sp > 0)
   {
      a1 = StringSubstr(arg, 0, sp);
      a2 = StringSubstr(arg, sp + 1);
      StringTrimLeft(a2);
      StringTrimRight(a2);
   }
   int ticket = 0;
   if(!TicketLesen(a1, ticket) || a2 == "")
   {
      TgNachrichtSenden("⚠️ " + cmd + ": Format " + cmd + " &lt;ticket&gt; &lt;preis&gt;" + (istSL ? " oder /sl &lt;ticket&gt; be" : "")
                        + ". Tickets siehe /positionen.", "");
      return;
   }
   if(!EigenePositionWaehlen(ticket))
   {
      TgNachrichtSenden("⚠️ " + cmd + ": #" + IntegerToString(ticket) + " ist keine offene Position dieses EAs (Symbol, Magic).", "");
      return;
   }
   int    typ    = OrderType();
   double offen  = OrderOpenPrice();
   double slAlt  = OrderStopLoss();
   double tpAlt  = OrderTakeProfit();
   double preis  = 0.0;
   if(istSL && a2 == "be")
      preis = NormalizeDouble(offen + ((typ == OP_BUY) ? 1 : -1) * BE_PufferPunkte * Point, Digits);
   else if(ZahlLesen(a2, preis) && preis > 0.0)
      preis = NormalizeDouble(preis, Digits);
   else
   {
      TgNachrichtSenden("⚠️ " + cmd + ": ungültiger Preis '" + HtmlEscape(a2) + "'.", "");
      return;
   }

   // richtige Seite und Mindestabstand (StopLevel) zum aktuellen Kurs
   RefreshRates();
   double stopLvl = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   double grenze;
   bool   ok;
   string regel;
   if(typ == OP_BUY)
   {
      if(istSL) { grenze = NormalizeDouble(Bid - stopLvl, Digits); ok = (preis <= grenze); regel = "höchstens " + DoubleToString(grenze, Digits); }
      else      { grenze = NormalizeDouble(Bid + stopLvl, Digits); ok = (preis >= grenze); regel = "mindestens " + DoubleToString(grenze, Digits); }
   }
   else
   {
      if(istSL) { grenze = NormalizeDouble(Ask + stopLvl, Digits); ok = (preis >= grenze); regel = "mindestens " + DoubleToString(grenze, Digits); }
      else      { grenze = NormalizeDouble(Ask - stopLvl, Digits); ok = (preis <= grenze); regel = "höchstens " + DoubleToString(grenze, Digits); }
   }
   if(!ok)
   {
      TgNachrichtSenden("⚠️ " + cmd + " #" + IntegerToString(ticket) + ": " + DoubleToString(preis, Digits) + " nicht erlaubt. "
                        + (typ == OP_BUY ? "BUY" : "SELL") + "-" + (istSL ? "SL" : "TP") + " muss " + regel
                        + " liegen (Kurs " + DoubleToString(typ == OP_BUY ? Bid : Ask, Digits) + ", StopLevel "
                        + DoubleToString(stopLvl / Point, 0) + " Pkt)"
                        + ((istSL && a2 == "be") ? " - die Position ist noch nicht weit genug im Gewinn." : "."), "");
      return;
   }

   ResetLastError();
   double neuSL = istSL ? preis : slAlt;
   double neuTP = istSL ? tpAlt : preis;
   if(!OrderModify(ticket, offen, neuSL, neuTP, 0, clrDodgerBlue))
   {
      int err = GetLastError();
      LogFehler("OrderModify #" + IntegerToString(ticket), err);
      TgNachrichtSenden("⚠️ " + cmd + " #" + IntegerToString(ticket) + " fehlgeschlagen: " + HtmlEscape(FehlerText(err))
                        + " (" + IntegerToString(err) + ")", "");
      return;
   }
   double alt = istSL ? slAlt : tpAlt;
   TgGeaendert((istSL ? "SL" : "TP") + " #" + IntegerToString(ticket),
               (alt > 0.0) ? DoubleToString(alt, Digits) : "-", DoubleToString(preis, Digits));
}

// /kauf [lot] und /verkauf [lot]: Vorschau mit Knöpfen (30 s), Ausführung erst nach ✅
void TgHandTradeAnfrage(int richtung, string arg)
{
   string cmd = (richtung > 0) ? "/kauf" : "/verkauf";
   double lot = 0.0;                      // 0 = Lot aus Risiko %
   if(arg != "")
   {
      double mn = MinLotWert(), mx = MaxLotGrenze();
      if(mx < mn - 1e-9)
      {
         TgNachrichtSenden("⚠️ " + cmd + ": Obergrenze (" + LotText(mx) + ") liegt unter MinLot (" + LotText(mn) + ").", "");
         return;
      }
      if(!TgBereichOK(cmd, arg, mn, mx, LotStellenAktuell(), " Lot", lot))
         return;
      lot = LotAbrunden(lot);
      if(lot < mn - 1e-9)
         lot = mn;
   }
   RefreshRates();
   double atr = AktuelleATR();
   string grund = "";
   if(!HandelErlaubt(grund, atr, true))
   {
      TgNachrichtSenden("⚠️ " + cmd + " nicht möglich: " + HtmlEscape(grund), "");
      return;
   }
   Plan p;
   if(!BerechnePlan(richtung, atr, p, grund, lot))
   {
      TgNachrichtSenden("⚠️ " + cmd + " nicht möglich: " + HtmlEscape(grund), "");
      return;
   }
   double maxSp = MaxSpreadAktuell(atr);
   string kosten = "Kosten: " + KostenText(p.spreadPkt, p.kommPkt) + " Pkt (Limit " + DoubleToString(maxSp, 1) + ")"
                   + ((p.spreadPkt + p.kommPkt > maxSp) ? " - über dem Limit, wird bei Hand-Trades ignoriert" : "");
   if(g_cfgHandMsg > 0)
      TgNachrichtBearbeiten(g_cfgHandMsg, "⌛ ersetzt durch neue Anfrage.");
   g_cfgHandRicht = richtung;
   g_cfgHandLot   = lot;
   g_cfgHandMsg = TgNachrichtSenden("⚠️ <b>Hand-Trade " + HtmlEscape(Symbol()) + " " + ((richtung > 0) ? "🟢 KAUF" : "🔴 VERKAUF")
                                    + "</b>\nEinstieg ca.: " + DoubleToString(p.preis, Digits) + "\n"
                                    + "SL: " + DoubleToString(p.sl, Digits) + " (" + DoubleToString(p.slDist / Point, 0) + " Pkt)\n"
                                    + "TP: " + DoubleToString(p.tp, Digits) + " (" + DoubleToString(p.tpDist / Point, 0) + " Pkt)\n"
                                    + "Lot: " + LotText(p.lot) + ((lot > 0.0) ? " (vorgegeben)" : " (Risiko " + DoubleToString(g_risiko, 1) + " %)") + "\n"
                                    + kosten + "\nBestätigung gilt 30 Sekunden.",
                                    TgTastaturCfg("✅ Ausführen", "cfg_hand_ja", "❌ Abbrechen", "cfg_hand_nein"));
   g_cfgHandBis = TimeLocal() + 30;
}

// Hand-Trade nach Bestätigung: Filter (ohne Zeitfenster/Spread) erneut prüfen, Order senden
string TgHandAusfuehren()
{
   RefreshRates();
   double atr = AktuelleATR();
   string grund = "";
   int r = g_cfgHandRicht;
   if(!HandelErlaubt(grund, atr, true))
   {
      DiagVerworfen(grund);
      return "⚠️ Nicht ausgeführt: " + HtmlEscape(grund);
   }
   if(!OrderOeffnen(r, atr, grund, g_cfgHandLot))
   {
      DiagVerworfen(grund);
      return "⚠️ Order fehlgeschlagen: " + HtmlEscape(grund);
   }
   HinweisSetzen("Hand-Trade " + (r > 0 ? "KAUF" : "VERKAUF") + " #" + IntegerToString(g_orderTicket));
   return "✅ Ausgeführt: " + (r > 0 ? "BUY" : "SELL") + " #" + IntegerToString(g_orderTicket) + " @"
          + DoubleToString(g_orderPreis, Digits);
}

// /be und /trailing: an | aus
void TgSchalter(string cmd, string arg)
{
   bool an;
   if(arg == "an" || arg == "ein" || arg == "on" || arg == "1")
      an = true;
   else if(arg == "aus" || arg == "off" || arg == "0")
      an = false;
   else
   {
      TgNachrichtSenden("⚠️ " + cmd + ": an oder aus erwartet. Aktuell: "
                        + ((cmd == "/be" ? g_beAktiv : g_trailingAktiv) ? "an" : "aus") + ".", "");
      return;
   }
   if(cmd == "/be")
   {
      string alt = g_beAktiv ? "an" : "aus";
      g_beAktiv = an;
      FernSpeichern("be", an ? 1.0 : 0.0);
      TgGeaendert("Break-even", alt, an ? "an" : "aus");
   }
   else
   {
      string alt = g_trailingAktiv ? "an" : "aus";
      g_trailingAktiv = an;
      FernSpeichern("trailing", an ? 1.0 : 0.0);
      TgGeaendert("Trailing", alt, an ? "an" : "aus");
   }
}

string BerichtZeitText(int m)
{
   return (m >= 0) ? MinutenText(m) + " Serverzeit" : "aus";
}

string TgBerichtText()
{
   string abw = FernAbweichungen();
   return "<b>Tagesbericht " + HtmlEscape(Symbol()) + " " + TimeToString(TimeCurrent(), TIME_DATE) + "</b>\n"
        + TgHeuteText() + "\n"
        + "Kontostand " + DoubleToString(AccountBalance(), 2) + ", Equity " + DoubleToString(AccountEquity(), 2) + " "
        + AccountCurrency() + "\n"
        + "Offene Positionen: " + IntegerToString(ZaehlePositionen()) + " (" + GeldText(OffenerGewinn()) + ")\n"
        + "Fern-Einstellungen: " + ((abw == "") ? "keine (Inputs aktiv)" : HtmlEscape(abw));
}

// /bericht ohne Argument = sofort senden; /bericht HH:MM setzt die Uhrzeit; /bericht aus schaltet ab
void TgBerichtBefehl(string arg)
{
   if(arg == "")
   {
      TgNachrichtSenden(TgBerichtText(), "");
      return;
   }
   int m = -1;
   if(arg != "aus" && arg != "off")
   {
      m = ZeitLesen(arg);
      if(m < 0)
      {
         TgNachrichtSenden("⚠️ /bericht: HH:MM (Serverzeit) oder aus erwartet. Ohne Angabe wird der Bericht sofort gesendet.", "");
         return;
      }
   }
   string alt = BerichtZeitText(g_berichtMin);
   g_berichtMin = m;
   FernSpeichern("bericht", (double)m);
   if(m >= 0)      // heute schon nach der neuen Uhrzeit: erst morgen
   {
      datetime t = TimeCurrent();
      if(TimeHour(t) * 60 + TimeMinute(t) >= m)
         g_berichtTag = (datetime)((long)t / 86400 * 86400);
      else
         g_berichtTag = 0;
   }
   TgGeaendert("Tagesbericht", alt, BerichtZeitText(g_berichtMin));
}

// In OnTimer: Tagesbericht einmal pro Serverzeit-Tag ab der eingestellten Uhrzeit senden
void TagesberichtPruefen()
{
   if(g_berichtMin < 0 || !TgBereit() || TimeLocal() < g_berichtRetry)
      return;
   datetime t     = TimeCurrent();
   datetime heute = (datetime)((long)t / 86400 * 86400);
   if(g_berichtTag == heute || TimeHour(t) * 60 + TimeMinute(t) < g_berichtMin)
      return;
   if(TgNachrichtSenden(TgBerichtText(), "") > 0)
   {
      g_berichtTag = heute;
      if(!IsTesting())
         GlobalVariableSet(FernSchluessel("berichttag"), (double)heute);
   }
   else
      g_berichtRetry = TimeLocal() + 60;
}

// /start bei gesetzter Kill-Switch-Sperre: Rückfrage per Knöpfe (60 s)
void TgStartAnfrage()
{
   if(g_cfgStartMsg > 0)
      TgNachrichtBearbeiten(g_cfgStartMsg, "⌛ ersetzt durch neue Anfrage.");
   g_cfgStartMsg = TgNachrichtSenden("▶️ Pause aufgehoben.\n⚠️ Der Kill-Switch hat neue Trades gesperrt. Sperre jetzt lösen?\n"
                                     + "Bestätigung gilt 60 Sekunden.",
                                     TgTastaturCfg("✅ Sperre lösen", "cfg_start_ja", "❌ Abbrechen", "cfg_start_nein"));
   g_cfgStartBis = TimeLocal() + 60;
}

// Textbefehle aus dem Chat (nur vom berechtigten Chat, Prüfung in TgUpdateBehandeln)
void TgBefehl(string text)
{
   string t = text;
   StringTrimLeft(t);
   StringTrimRight(t);
   if(StringGetCharacter(t, 0) != '/')
      return;
   string cmd = t;
   string arg = "";
   int sp = StringFind(t, " ");
   if(sp > 0)
   {
      cmd = StringSubstr(t, 0, sp);
      arg = StringSubstr(t, sp + 1);
   }
   StringToLower(cmd);
   StringToLower(arg);
   StringTrimLeft(arg);
   StringTrimRight(arg);
   int at = StringFind(cmd, "@");      // "/status@meinbot" aus Gruppen
   if(at > 0)
      cmd = StringSubstr(cmd, 0, at);

   if(cmd == "/hilfe" || cmd == "/help")
      TgNachrichtSenden(TgHilfeText(), "");
   else if(cmd == "/status")
      TgNachrichtSenden(TgStatusText(), "");
   else if(cmd == "/diag")
      TgNachrichtSenden(TgDiagText(), "");
   else if(cmd == "/stop")
   {
      g_tgPause = true;
      HinweisSetzen("Pausiert per Telegram");
      TgNachrichtSenden("⏸ Pausiert: neue Signale werden blockiert. /start hebt die Pause auf.", "");
   }
   else if(cmd == "/start")
   {
      g_tgPause = false;
      HinweisSetzen("Pause per Telegram aufgehoben");
      if(g_gestoppt)
         TgStartAnfrage();
      else
         TgNachrichtSenden("▶️ Pause aufgehoben: neue Signale sind wieder erlaubt. Befehle: /hilfe", "");
   }
   else if(cmd == "/modus")
      TgModusBefehl(arg);
   else if(cmd == "/positionen")
      TgNachrichtSenden(TgPositionenText(), "");
   else if(cmd == "/heute")
      TgNachrichtSenden(TgHeuteText(), "");
   else if(cmd == "/schliessen" || cmd == "/schließen")
      TgSchliessenAnfrage();
   else if(cmd == "/reset")
      TgReset();
   else if(cmd == "/zu")
      TgZuAnfrage(arg);
   else if(cmd == "/sl" || cmd == "/tp")
      TgSlTpBefehl(cmd, arg);
   else if(cmd == "/kauf")
      TgHandTradeAnfrage(1, arg);
   else if(cmd == "/verkauf")
      TgHandTradeAnfrage(-1, arg);
   else if(cmd == "/be" || cmd == "/trailing")
      TgSchalter(cmd, arg);
   else if(cmd == "/bericht")
      TgBerichtBefehl(arg);
   else if(!TgEinstellung(cmd, arg))
      TgNachrichtSenden("Unbekannter Befehl " + HtmlEscape(cmd) + ". Alle Befehle: /hilfe", "");
   UiAktualisieren();
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
         Print("ScalpScout Telegram: Knopfdruck aus fremdem Chat ignoriert.");
         return;
      }

      if(StringFind(data, "cfg_") == 0)      // Einstellungs-Rückfragen (Vollautomatik, Alle schließen)
      {
         long mid = 0;
         int  pmm = StringFind(seg, "\"message\":{", pc);
         if(pmm >= 0)
            JsonZahl(seg, "message_id", pmm, mid);
         TgCfgCallback(cbId, data, mid);
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
         Print("ScalpScout Telegram: Nachricht aus fremdem Chat ignoriert.");
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
      Print("ScalpScout Telegram: Token oder Chat-ID fehlt - Telegram bleibt aus.");
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
   g_cfgAutoMsg = 0;
   g_cfgSchlMsg = 0;
   g_cfgZuMsg = 0;
   g_cfgHandMsg = 0;
   g_cfgStartMsg = 0;
   string gruss = "ScalpScout auf <b>" + HtmlEscape(Symbol()) + "</b> gestartet (Modus " + ModusText() + ")\nBefehle: /hilfe";
   if(g_fernInfo != "")
      gruss += "\nFern-Einstellungen aktiv: " + HtmlEscape(g_fernInfo);
   TgNachrichtSenden(gruss, "");
}

//+------------------------------------------------------------------+
//| Retest-Einstieg: Signal merken, Rücklauf abwarten, ausführen     |
//+------------------------------------------------------------------+
// Verbleibende M1-Kerzen bis zum Verfall (zeitbasiert ab dem Beginn der Kerze, in der das Signal entstand)
int RetestRestKerzen()
{
   int rest = (int)(((long)g_rt.verfall - (long)iTime(Symbol(), PERIOD_M1, 0)) / 60);
   return (rest < 0) ? 0 : rest;
}

// "LONG bis 1.12345 (noch 3 Kerzen)"
string RetestWartetText()
{
   int rest = RetestRestKerzen();
   return ((g_rt.richtung > 0) ? "LONG" : "SHORT") + " bis " + DoubleToString(g_rt.ziel, Digits)
          + " (noch " + IntegerToString(rest) + ((rest == 1) ? " Kerze)" : " Kerzen)");
}

// Chart-Zeile zum Einstieg
string RetestInfoText(color &clr)
{
   if(g_rt.aktiv)
   {
      clr = clrAqua;
      return "Retest wartet: " + RetestWartetText();
   }
   clr = clrSilver;
   if(g_einstieg == EINSTIEG_RETEST)
      return "Einstieg: Retest (Rücklauf " + DoubleToString(g_retestAnteil, 2) + ", max " + IntegerToString(g_retestMaxKerzen)
             + " Kerzen, CRV " + DoubleToString(g_retestTPCRV, 2) + ") - kein Signal wartet";
   return "Einstieg: Sofort (direkt nach der Signalkerze)";
}

// Wartendes Retest-Signal ohne Zählung entfernen (Moduswechsel der Einstiegsart, Reset, Kill-Switch, Ersetzen)
void RetestLoeschen(string grund)
{
   if(!g_rt.aktiv)
      return;
   g_rt.aktiv = false;
   Print("ScalpScout: wartendes Retest-Signal gelöscht - ", grund);
}

// Neues Signal auf der geschlossenen Kerze (Shift 1) als wartendes Retest-Signal merken
void RetestMerken(int sig, double atr)
{
   g_rt.aktiv     = true;
   g_rt.richtung  = sig;
   g_rt.kerzeZeit = iTime(Symbol(), PERIOD_M1, 1);
   g_rt.kOpen     = iOpen(Symbol(), PERIOD_M1, 1);
   g_rt.kHigh     = iHigh(Symbol(), PERIOD_M1, 1);
   g_rt.kLow      = iLow(Symbol(), PERIOD_M1, 1);
   g_rt.kClose    = iClose(Symbol(), PERIOD_M1, 1);
   g_rt.atr       = atr;
   // Zielpreis: Long = Close - Anteil * Körper, Short = Close + Anteil * Körper
   double koerper = MathAbs(g_rt.kClose - g_rt.kOpen);
   g_rt.ziel      = NormalizeDouble(g_rt.kClose - sig * g_retestAnteil * koerper, Digits);
   // Die laufende Kerze zählt als erste der N weiteren Kerzen
   g_rt.verfall   = (datetime)((long)iTime(Symbol(), PERIOD_M1, 0) + (long)g_retestMaxKerzen * 60);
   Print("ScalpScout: Retest-Signal ", (sig > 0 ? "LONG" : "SHORT"), " gemerkt - Signalkerze ",
         TimeToString(g_rt.kerzeZeit, TIME_DATE | TIME_MINUTES), " O ", DoubleToString(g_rt.kOpen, Digits),
         " H ", DoubleToString(g_rt.kHigh, Digits), " L ", DoubleToString(g_rt.kLow, Digits),
         " C ", DoubleToString(g_rt.kClose, Digits), ", Ziel ", DoubleToString(g_rt.ziel, Digits),
         ", Verfall nach ", g_retestMaxKerzen, " Kerzen");
}

// Rücklauf erreicht: Filter erneut prüfen, feste SL/TP-Preise bilden, je nach Modus ausführen/melden/zur Freigabe zeigen
void RetestAusloesen()
{
   int    richtung = g_rt.richtung;
   double atr      = g_rt.atr;
   double kHigh    = g_rt.kHigh;
   double kLow     = g_rt.kLow;
   string txt      = (richtung > 0) ? "LONG" : "SHORT";
   g_rt.aktiv = false;                 // zuerst löschen: nie doppelt ausführen
   g_rtErreicht++;
   g_dgRichtung = richtung;

   RefreshRates();
   string grund = "";
   if(!HandelErlaubt(grund, atr))
   {
      g_dgErgebnis = "Retest " + txt + " erreicht, aber blockiert: " + grund;
      DiagVerworfen(grund);
      HinweisSetzen("Retest " + txt + " blockiert: " + grund);
      return;
   }

   // SL hinter dem Extrem der Signalkerze, TP = CRV x SL-Abstand ab dem tatsächlichen Einstiegskurs
   double puffer = RetestSLPufferATR * atr;
   double sl, tp, einstieg;
   if(richtung > 0)
   {
      einstieg = Ask;
      sl = NormalizeDouble(kLow - puffer, Digits);
      tp = NormalizeDouble(einstieg + g_retestTPCRV * (einstieg - sl), Digits);
   }
   else
   {
      einstieg = Bid;
      sl = NormalizeDouble(kHigh + puffer + (Ask - Bid), Digits);
      tp = NormalizeDouble(einstieg - g_retestTPCRV * (sl - einstieg), Digits);
   }
   if((richtung > 0 && sl >= einstieg) || (richtung < 0 && sl <= einstieg) || tp <= 0.0)
   {
      grund = "Retest: SL liegt auf der falschen Seite des Einstiegs";
      g_dgErgebnis = "Retest " + txt + " erreicht, aber ohne Trade: " + grund;
      DiagVerworfen(grund);
      HinweisSetzen("Retest " + txt + " ohne Trade: " + grund);
      return;
   }

   Plan p;
   if(!BerechnePlan(richtung, atr, p, grund, 0.0, sl, tp))
   {
      g_dgErgebnis = "Retest " + txt + " erreicht, aber ohne Trade: " + grund;
      DiagVerworfen(grund);
      HinweisSetzen("Retest " + txt + " ohne Trade: " + grund);
      return;
   }
   g_dgErgebnis = "Retest " + txt + " erreicht";

   string meldung = "ScalpScout " + Symbol() + " " + txt + " (Retest) @" + DoubleToString(p.preis, Digits)
                    + " SL " + DoubleToString(p.sl, Digits) + " TP " + DoubleToString(p.tp, Digits)
                    + " Lot " + DoubleToString(p.lot, 2) + " " + KostenText(p.spreadPkt, p.kommPkt)
                    + " CRV 1:" + DoubleToString(p.crv, 2);

   switch(g_modus)
   {
      case NUR_SIGNALE:
         Melden(meldung + " (nur Signal)");
         HinweisSetzen("Retest " + txt + " gemeldet (kein Trade)");
         TgNachrichtSenden(TgSignalText(p) + "\n🔁 Retest erreicht - nur Signal, kein Trade", "");
         break;

      case VOLLAUTOMATIK:
         if(OrderOeffnen(richtung, atr, grund, 0.0, sl, tp))
         {
            Melden(meldung + " - ausgeführt");
            HinweisSetzen("Auto-Trade " + txt + " (Retest) eröffnet");
            TgNachrichtSenden(TgSignalText(p) + "\n✅ automatisch ausgeführt (Retest): #" + IntegerToString(g_orderTicket)
                              + " @" + DoubleToString(g_orderPreis, Digits), "");
         }
         else
         {
            g_dgErgebnis = "Retest " + txt + " erreicht, Order fehlgeschlagen: " + grund;
            DiagVerworfen(grund);
            HinweisSetzen("Auto-Trade " + txt + " (Retest) fehlgeschlagen: " + grund);
         }
         break;

      case MANUELLE_FREIGABE:
         if(g_sig.aktiv)
            SignalVerwerfen("durch neues Signal ersetzt", "⌛ ersetzt durch neues Signal");
         g_sig.aktiv = true;
         g_sig.zeit  = TimeLocal();
         g_sig.plan  = p;
         g_sig.slFix = sl;
         g_sig.tpFix = tp;
         g_sigId     = TgNeueSignalId();
         g_sigMsgId  = 0;
         g_tgKopf    = TgSignalKopf(p);
         PanelZeigen();
         Melden(meldung + " - Freigabe im Chart nötig (" + IntegerToString(SignalGueltigSek) + " s)");
         g_sigMsgId  = TgNachrichtSenden(TgSignalText(p) + "\n🔁 Retest erreicht\n⏱ gültig " + IntegerToString(SignalGueltigSek) + " s",
                                         TgTastatur(g_sigId));
         break;
   }
}

// Bei jedem Tick: Verfall, gescheiterter Ausbruch und Erreichen des Zielpreises prüfen
void RetestPruefen()
{
   if(!g_rt.aktiv)
      return;
   if(g_einstieg != EINSTIEG_RETEST)
   {
      RetestLoeschen("Einstiegsart nicht mehr Retest");
      return;
   }

   // Verfall (zuerst: in der Kerze, in der das Signal verfällt, wird nicht mehr eingestiegen)
   if(iTime(Symbol(), PERIOD_M1, 0) >= g_rt.verfall)
   {
      g_rtVerfallen++;
      g_rt.aktiv = false;
      DiagVerworfen("Retest verfallen (kein Rücklauf innerhalb " + IntegerToString(g_retestMaxKerzen) + " Kerzen)");
      HinweisSetzen("Retest " + ((g_rt.richtung > 0) ? "LONG" : "SHORT") + " verfallen (kein Rücklauf)");
      return;
   }

   RefreshRates();

   // Ausbruch gescheitert: Kurs (Bid, wie im Chart) durchbricht das Extrem der Signalkerze auf der Gegenseite
   if((g_rt.richtung > 0 && Bid < g_rt.kLow) || (g_rt.richtung < 0 && Bid > g_rt.kHigh))
   {
      g_rtAbgebrochen++;
      g_rt.aktiv = false;
      DiagVerworfen("Retest abgebrochen (Ausbruch gescheitert)");
      HinweisSetzen("Retest " + ((g_rt.richtung > 0) ? "LONG" : "SHORT") + " abgebrochen (Ausbruch gescheitert)");
      return;
   }

   // Rücklauf erreicht: Long kauft zum Ask, Short verkauft zum Bid
   if((g_rt.richtung > 0 && Ask <= g_rt.ziel) || (g_rt.richtung < 0 && Bid >= g_rt.ziel))
      RetestAusloesen();
}

//+------------------------------------------------------------------+
//| Signal-Logik auf geschlossener M1-Kerze (Shift 1)                |
//+------------------------------------------------------------------+
// Rückgabe: +1 Long, -1 Short, 0 kein Signal
int SignalErkennen(double &atr)
{
   atr = 0.0;
   int mindestens = MathMax(MathMax(ATR_Periode, EMA_Periode * 2), VolumenKerzen + g_breakoutKerzen) + 5;
   if(iBars(Symbol(), PERIOD_M1) < mindestens)
      return 0;

   atr = AktuelleATR();
   if(atr <= 0.0)
      return 0;

   double o1 = iOpen(Symbol(), PERIOD_M1, 1);
   double c1 = iClose(Symbol(), PERIOD_M1, 1);
   double koerper = MathAbs(c1 - o1);
   if(koerper <= g_impulsFaktor * atr)
      return 0;

   // Volumen: Kerze 1 gegen Durchschnitt der Kerzen davor (Shift 2 .. VolumenKerzen+1)
   double summe = 0.0;
   for(int i = 2; i <= VolumenKerzen + 1; i++)
      summe += (double)iVolume(Symbol(), PERIOD_M1, i);
   double schnitt = (VolumenKerzen > 0) ? summe / VolumenKerzen : 0.0;
   double vol1    = (double)iVolume(Symbol(), PERIOD_M1, 1);
   if(schnitt <= 0.0 || vol1 <= g_volumenFaktor * schnitt)
      return 0;

   double ema = iMA(Symbol(), PERIOD_M1, EMA_Periode, 0, MODE_EMA, PRICE_CLOSE, 1);

   if(c1 > o1)   // bullische Kerze -> Long prüfen
   {
      int hi = iHighest(Symbol(), PERIOD_M1, MODE_HIGH, g_breakoutKerzen, 2);
      if(hi < 0) return 0;
      if(c1 <= iHigh(Symbol(), PERIOD_M1, hi)) return 0;
      if(TrendFilterAktiv && c1 <= ema) return 0;
      return 1;
   }
   if(c1 < o1)   // bärische Kerze -> Short prüfen
   {
      int lo = iLowest(Symbol(), PERIOD_M1, MODE_LOW, g_breakoutKerzen, 2);
      if(lo < 0) return 0;
      if(c1 >= iLow(Symbol(), PERIOD_M1, lo)) return 0;
      if(TrendFilterAktiv && c1 >= ema) return 0;
      return -1;
   }
   return 0;
}

void NeueKerzeAuswerten()
{
   DiagKerze();               // rein lesend: Werte der Kerze für /diag und Chart-Zeile merken
   g_dgKerzen++;

   double atr;
   int sig = SignalErkennen(atr);
   if(sig == 0)
   {
      if(g_dgErgebnis == "")
         g_dgErgebnis = "kein Signal";
      return;
   }

   string txt = (sig > 0) ? "LONG" : "SHORT";
   string grund;
   g_dgSignale++;
   g_dgRichtung = sig;

   if(g_rt.aktiv)      // ein neues Signal ersetzt ein wartendes Retest-Signal
   {
      DiagVerworfen("Retest durch neues Signal ersetzt");
      RetestLoeschen("durch neues Signal ersetzt");
   }

   if(!HandelErlaubt(grund, atr))
   {
      g_dgErgebnis = "Signal " + txt + " erkannt, aber blockiert: " + grund;
      DiagVerworfen(grund);
      HinweisSetzen("Signal " + txt + " blockiert: " + grund);
      return;
   }

   if(g_einstieg == EINSTIEG_RETEST)
   {
      // Nicht sofort handeln: Signal merken und auf den Rücklauf warten (Ausführung in RetestPruefen)
      RetestMerken(sig, atr);
      g_dgErgebnis = "Signal " + txt + " erkannt, Retest wartet bis " + DoubleToString(g_rt.ziel, Digits);
      HinweisSetzen("Retest-Signal " + txt + " wartet bis " + DoubleToString(g_rt.ziel, Digits));
      return;
   }

   Plan p;
   if(!BerechnePlan(sig, atr, p, grund))
   {
      g_dgErgebnis = "Signal " + txt + " erkannt, aber ohne Trade: " + grund;
      DiagVerworfen(grund);
      HinweisSetzen("Signal " + txt + " ohne Trade: " + grund);
      return;
   }
   g_dgErgebnis = "Signal " + txt;

   string meldung = "ScalpScout " + Symbol() + " " + txt + " @" + DoubleToString(p.preis, Digits)
                    + " SL " + DoubleToString(p.sl, Digits) + " TP " + DoubleToString(p.tp, Digits)
                    + " Lot " + DoubleToString(p.lot, 2) + " " + KostenText(p.spreadPkt, p.kommPkt)
                    + " CRV 1:" + DoubleToString(p.crv, 2);

   switch(g_modus)
   {
      case NUR_SIGNALE:
         Melden(meldung + " (nur Signal)");
         HinweisSetzen("Signal " + txt + " gemeldet (kein Trade)");
         TgNachrichtSenden(TgSignalText(p) + "\nnur Signal, kein Trade", "");
         break;

      case VOLLAUTOMATIK:
         if(OrderOeffnen(sig, atr, grund))
         {
            Melden(meldung + " - ausgeführt");
            HinweisSetzen("Auto-Trade " + txt + " eröffnet");
            TgNachrichtSenden(TgSignalText(p) + "\n✅ automatisch ausgeführt: #" + IntegerToString(g_orderTicket)
                              + " @" + DoubleToString(g_orderPreis, Digits), "");
         }
         else
         {
            g_dgErgebnis = "Signal " + txt + " erkannt, Order fehlgeschlagen: " + grund;
            DiagVerworfen(grund);
            HinweisSetzen("Auto-Trade " + txt + " fehlgeschlagen: " + grund);
         }
         break;

      case MANUELLE_FREIGABE:
         if(g_sig.aktiv)
            SignalVerwerfen("durch neues Signal ersetzt", "⌛ ersetzt durch neues Signal");
         g_sig.aktiv = true;
         g_sig.zeit  = TimeLocal();
         g_sig.plan  = p;
         g_sig.slFix = 0.0;
         g_sig.tpFix = 0.0;
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
      Alert("ScalpScout: HandelStart/HandelEnde müssen das Format HH:MM haben (z. B. 08:00).");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(ATR_Periode < 1 || EMA_Periode < 1 || VolumenKerzen < 1 || BreakoutKerzen < 1 ||
      ImpulsFaktor <= 0.0 || VolumenFaktor <= 0.0 || SL_ATR <= 0.0 || TP_ATR <= 0.0 ||
      RisikoProzent <= 0.0 || MaxLot <= 0.0 || FernMaxLotObergrenze <= 0.0 || MaxOffenePositionen < 1 || SignalGueltigSek < 1 ||
      KommissionProLot < 0.0)
   {
      Alert("ScalpScout: Ungültige Eingabewerte (Perioden, Faktoren, Risiko, MaxLot müssen > 0 sein, Kommission nicht negativ).");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(RetestAnteil < 0.2 || RetestAnteil > 0.8 || RetestMaxKerzen < 1 || RetestMaxKerzen > 15 ||
      RetestSLPufferATR < 0.0 || RetestTP_CRV < 1.0 || RetestTP_CRV > 4.0)
   {
      Alert("ScalpScout: Retest-Eingaben ungültig (RetestAnteil 0.2-0.8, RetestMaxKerzen 1-15, RetestSLPufferATR >= 0, RetestTP_CRV 1.0-4.0).");
      return INIT_PARAMETERS_INCORRECT;
   }

   string bz = TagesberichtZeit;
   StringTrimLeft(bz);
   StringTrimRight(bz);
   if(bz != "" && ParseHHMM(bz) < 0)
   {
      Alert("ScalpScout: TagesberichtZeit muss das Format HH:MM haben oder leer sein.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(Period() != PERIOD_M1)
      Print("ScalpScout WARNUNG: EA ist für den M1-Chart gedacht (aktuell: ", Period(), " Min.). Auswertung läuft trotzdem auf M1.");

   // Wirksame Betriebsart
   g_modus = Modus;
   if(IsTesting() && Modus == MANUELLE_FREIGABE)
   {
      g_modus = VOLLAUTOMATIK;
      Print("ScalpScout: Strategietester erkannt - Modus MANUELLE_FREIGABE wird wie VOLLAUTOMATIK behandelt.");
   }
   g_modusInput = g_modus;
   g_ui = (!IsTesting() || IsVisualMode());

   // Laufzeit-Werte: erst aus den Inputs, dann (live) die per Telegram gespeicherten Änderungen
   g_berichtTag   = 0;
   g_berichtRetry = 0;
   FernInputsUebernehmen();
   FernLaden();
   DiagZuruecksetzen();

   g_sig.aktiv = false;
   g_sig.slFix = 0.0;
   g_sig.tpFix = 0.0;
   g_rt.aktiv  = false;
   g_gestoppt  = false;
   g_hinweis   = "";
   g_histAnzahl = -1;
   g_sigId     = 0;
   g_sigMsgId  = 0;
   g_tgKopf    = "";
   g_tgPause   = false;

   // Tagesstart (live aus globalen Variablen wiederherstellen)
   g_gvTag    = "SSC_" + IntegerToString(AccountNumber()) + "_" + IntegerToString(MagicNumber) + "_tag";
   g_gvEquity = "SSC_" + IntegerToString(AccountNumber()) + "_" + IntegerToString(MagicNumber) + "_eq";
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
      UiAktualisieren();
   }
   if(!IsTesting())
      EventSetTimer(1);

   Print("ScalpScout gestartet: ", Symbol(), ", Modus ", ModusText(), ", Einstieg ", EinstiegName(g_einstieg),
         ", MaxLot ", DoubleToString(g_maxLot, 2),
         ", Risiko ", DoubleToString(g_risiko, 1), " %, Digits ", Digits, ", Point ", DoubleToString(Point, Digits));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PRAEFIX);
   Comment("");
   ChartRedraw(0);
   Print("ScalpScout beendet (Grund ", reason, ").");
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
   RetestPruefen();           // wartendes Retest-Signal: Verfall, Abbruch oder Einstieg

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
   TgCfgAblaufPruefen();
   TagesberichtPruefen();
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
      int antwort = MessageBox("Alle Positionen von ScalpScout (Magic " + IntegerToString(MagicNumber)
                               + ") auf " + Symbol() + " jetzt schließen?\n\nDanach sind neue Trades gesperrt, bis der EA neu gestartet wird.",
                               "ScalpScout - ALLES SCHLIESSEN", MB_YESNO | MB_ICONWARNING);
      if(antwort == IDYES)
      {
         int geschlossen = 0, fehler = 0;
         AlleSchliessen(geschlossen, fehler);
      }
      UiAktualisieren();
   }
}
//+------------------------------------------------------------------+
