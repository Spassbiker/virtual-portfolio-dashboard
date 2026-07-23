"""Regelbasierte Depot-Engine (Aktien-Sleeve, 10.000€-Budget).

Berechnet aus Chart-, Fundamental- und KI-Sentiment-Daten ein Zielportfolio und
führt die Handelsphasen aus (Verkauf → Sektor-Abbau → Rebalancing → Neukäufe).

Zwei Betriebsmodi:
  * --recommend / --dry-run : berechnet Score/Sentiment/Veto und die Trades, die
    das System vorschlagen WÜRDE, schreibt sie nach data/trade_recommendations.json
    und lässt depot_status.json unangetastet. Die finale Kauf-/Verkaufsentscheidung
    bleibt beim autonomen Agenten.
  * (ohne Argument)          : schreibt das Ergebnis live nach depot_status.json.

Struktur: reine Scoring-/Helfer-Funktionen oben, dann die Handelsphasen als
eigene Funktionen, orchestriert von main(). Eingabedaten (Chart/Funda/Sentiment/
DAX) werden in load_inputs() geladen — Netzwerk- und Datei-Zugriffe passieren
NICHT mehr beim Import, sondern erst beim Aufruf von main().
"""

import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (
    DEPOT as depot_path,
    CHART,
    FUNDA,
    SENT as sentiment_path,
    NEWS as news_path,
    EARNINGS as earnings_path,
    TRADES as recommend_path,
    load_json,
    save_json,
)
from consistency import data_consistency
import ticker_map

# ==========================================
# KONSTANTEN
# ==========================================

SENTIMENT_MIN, SENTIMENT_MAX = -3, 3
DEFAULT_CONFIDENCE = 0.7
REVIEW_FLAG_THRESHOLD = -2  # rohes Sentiment auf Bestand ab hier -> review_flag

# --- EVENT-MATERIALITÄT (#2) ---
# Nicht jede News wiegt gleich schwer. Ein Zahlen-/Guidance-/M&A-Ereignis ist
# ein harter, kursrelevanter Katalysator; ein Analysten-Kommentar oder
# "Sonstiges" ist weicher und öfter schon eingepreist. Der Faktor multipliziert
# das (bereits confidence-gewichtete) Sentiment, dämpft also weiche Signale,
# ohne harte zu übertreiben. "Keine" → 0, weil dann ohnehin kein Ereignis da ist.
# Fehlt/unbekannt die Kategorie, greift Default 1.0 (kein Effekt = altes Verhalten).
MATERIALITY_WEIGHTS = {
    "Zahlen": 1.0,
    "Guidance": 1.0,
    "M&A": 1.0,
    "Analyst": 0.8,
    "Sonstiges": 0.7,
    "Keine": 0.0,
}
DEFAULT_MATERIALITY = 1.0
# --- RECENCY-DECAY (#2) ---
# News altert. Der objektive Zeit-Decay ergänzt die (subjektive) LLM-Confidence:
# Faktor = 0.5 ** (Alter_der_frischesten_Schlagzeile_in_Tagen / HALF_LIFE), auf
# [FLOOR, 1.0] geklemmt. Halbwertszeit 5 Tage, Boden 0.5 — eine Woche alte News
# wirkt noch halb, nagelt das Signal aber nicht auf 0 (die Engine läuft täglich,
# frische News sollen dominieren, ältere ausklingen). Fehlt ein Datum, kein Effekt.
RECENCY_HALF_LIFE_DAYS = 5.0
RECENCY_FLOOR = 0.5
# --- EARNINGS/GUIDANCE (#1) ---
# Forward-looking Signal aus den letzten Quartals-/Jahreszahlen + Ausblick,
# vom LLM als earnings_score (-3..+3 × confidence) geliefert. Eigener Summand
# im total_score, aber mit EARNINGS_WEIGHT gedämpft: Es soll ergänzen, nicht das
# (news-basierte) Sentiment und den Chart überstimmen. Fehlt die Datei → 0.
EARNINGS_WEIGHT = 0.8

# --- SCORING-SYSTEM ---
# Kauf-Schwelle: ADAPTIV. Fixer Floor = BUY_FLOOR, effektive Schwelle ist
# max(BUY_FLOOR, 80er-Perzentil aller aktiven Kandidatenscores). Das hebt
# die Latte in starken Märkten automatisch (mehr Auswahl → wähle die besten),
# ohne in schwachen Märkten alle Käufe zu blockieren.
BUY_FLOOR = 6
BUY_PERCENTILE = 0.80       # nur die Top-20% werden Kauf-Kandidaten
# Fallback wenn Kandidatenmenge zu klein für sinnvolles Perzentil ist.
BUY_FALLBACK_THRESHOLD = 8
BUY_MIN_CANDIDATES = 10     # unter dieser Anzahl greift der Fallback
# Score below this triggers Verkauf für bestehende Positionen
SELL_THRESHOLD = 4
# Rebalancing-Schwelle: nur Halten-Positionen unter diesem festen Wert werden
# zur Kapitalbeschaffung verkauft. Absichtlich NICHT die adaptive Kaufschwelle —
# sonst würden in starken Märkten (adaptive Schwelle hoch) alle "guten aber
# nicht Top-Kandidaten" abgeräumt.
REBALANCE_THRESHOLD = 8
# Watch-Modus: neu aufgenommene Papiere (Opportunity-Scan) haben oft noch
# keine belastbare Chart-Historie (SMA200/RSI/MACD). Sie werden NICHT gekauft,
# bleiben aber im Universum stehen, bis genug Daten da sind.
WATCH_MIN_CLOSES = 200          # SMA200 braucht 200 Tage
WATCH_MARKERS = ("watch-kandidat", "opportunity-scan")
# Zweistufiger Stop-Loss (marktbereinigt):
#  1) ABSOLUTER HARD-STOP: fällt eine Position absolut um mehr als X unter den
#     Kaufkurs, wird IMMER verkauft — Katastrophenschutz, auch wenn der ganze
#     Markt fällt. Der Hauptjob des Stops bleibt Kapitalschutz.
#  2) RELATIVER STOP: greift nur, wenn die Position im Minus ist UND ihre
#     beta-bereinigte Underperformance ggü. dem DAX (Alpha) unter -REL_STOP_PCT
#     liegt. So wird man bei breiten Marktdips NICHT rausgekegelt, aber echte
#     unternehmensspezifische Schwäche früher erkannt.
ABS_HARD_STOP_PCT = -0.20   # absoluter Notausgang (Katastrophenschutz)
REL_STOP_PCT = -0.12        # beta-bereinigte Underperformance vs. DAX
#  3) DYNAMISCHER VOLA-STOP (Phase-3-Bonus, nachgeholt 2026-07-23): fixe -20%
#     sind für ruhige Titel viel zu weit — Lockheed lief -17% ohne dass ein
#     Stop griff. Distanz = DYN_STOP_VOL_MULT × Tagesvola × sqrt(Horizont),
#     gemessen als Rückgang vom Trailing-Anker (stop_ref_kurs = Positionshoch),
#     geklemmt auf [DYN_STOP_MIN, DYN_STOP_MAX]. Ein 1%-Vola-Titel stoppt so
#     schon bei ~-9% vom Hoch, ein 2%-Titel bei ~-18%; ohne Vola-Daten inaktiv.
DYN_STOP_VOL_MULT = 2.0
DYN_STOP_HORIZON_DAYS = 20
DYN_STOP_MIN, DYN_STOP_MAX = 0.06, 0.18
# Cash-Management: Mindest-Barreserve nie unterschreiten, und keine Mini-Käufe
# (Gebühren-Drag). Bei 5 € Gebühr wären 100 € Order = 5 % Reibung.
# Der Puffer ist DYNAMISCH: max(25€ Boden, 2% des Gesamtvermögens). Vorher war
# das Depot mit 25€ Rest-Cash faktisch vollinvestiert — jedes Kaufsignal
# erzwang einen Verkauf (Zwangs-Churn mit Gebühren/Steuern).
MIN_CASH_RESERVE = 25.0
CASH_RESERVE_PCT = 0.02
MIN_ORDER_VALUE = 100.0
# Klumpenrisiko-Hardcap: risk_report.py WARNT schon ab 30% Sektoranteil, aber
# blockiert nichts. Hier greift die Kaufsperre erst später (60%) und kappt/
# blockiert NEUE Käufe, die einen Sektor darüber treiben würden — bestehende
# Positionen werden dadurch nicht verkauft, das ist reines Wachstums-Limit.
MAX_SEKTOR_PCT_HARD = 0.60
# SOFT-CAP mit Zähnen: risk_report.py warnt ab 30%, tat aber nie etwas. Diese
# Schwelle führt ein BESTEHENDES Sektor-Übergewicht aktiv zurück (Phase 1b),
# indem die schwächsten Positionen des Sektors verkauft werden, bis er wieder
# <= Cap liegt. Bewusster Risiko-Override der Kaufen/Halten-Signale.
SEKTOR_SOFT_CAP = 0.30
# Hysterese: Abbau (Ganzverkäufe sind grob) startet ERST bei spürbarer
# Überschreitung, sonst würde ein Sektor bei 30.1% eine ganze Gewinnerposition
# kosten. Ausgelöst wird ab Cap+Toleranz, reduziert wird dann bis auf den Cap.
SEKTOR_CAP_TOLERANCE = 0.03
# EINZELPOSITIONS-CAP: keine einzelne Aktie über 20% des Portfoliowerts
# (2026-07-23: Nvidia 19.5%, Top-5 = 74% — Konzentrationsrisiko hatte bis dahin
# nur ein Sektor-, aber kein Positions-Limit). Rückführung per TEILverkauf
# (nicht Ganzverkauf — die Position ist per Definition ein Gewinner) mit
# Hysterese analog Sektor-Abbau: Eingriff ab Cap+Toleranz, Ziel = Cap.
# Die Kaufphase kappt Budgets ebenfalls auf den Cap (Wachstums-Limit).
MAX_POS_PCT = 0.20
POS_CAP_TOLERANCE = 0.02

# Positionsgröße: 1000€ Basis + 100€ je Punkt über Schwellwert, max 2500€.
BUDGET_BASE = 1000.0
BUDGET_PER_POINT = 100.0
BUDGET_MAX = 2500.0

# Phase 3: Volatilitäts-Sizing (Risk-Parity statt Euro-Parity je Trade).
# Referenz-Tagesvolatilität ~2 %; ruhigere Titel bekommen mehr, wildere weniger
# Budget. Multiplikator in [0.6, 1.4] gekappt, damit das Score-Ranking führend
# bleibt und keine Extremwerte die Positionsgröße dominieren.
REF_VOL_PCT = 2.0
VOL_MULT_MIN, VOL_MULT_MAX = 0.6, 1.4

# MARKT-REFERENZ (DAX) + AUTO-BETA für den relativen Stop-Loss.
# DAX als Benchmark. Beta wird pro Position automatisch aus ~1 Jahr
# Tagesrenditen geschätzt (Regression Aktie vs. DAX). Ohne verlässliche Daten
# fällt Beta auf 1.0 zurück ("im ersten Schritt 1:1, aber automatisch anpassend").
DAX_SYMBOL = "^GDAXI"
BETA_MIN, BETA_MAX, BETA_DEFAULT = 0.3, 2.5, 1.0

fee_per_trade = 5.00
CAP_GAINS_TAX = 0.26375   # Kapitalertragsteuer + Soli, nur auf Gewinne

# Marker-Texte, die eine Fundamental-Analyse als Platzhalter (keine echten
# Kennzahlen) ausweisen — solche Einträge dürfen den Score nicht aufblähen.
_FUNDA_PLACEHOLDER_MARKERS = ("vervollständigung", "ergänzt zur", "platzhalter")

# ==========================================
# EINGABEDATEN (in load_inputs() befüllt — beim Import None/leer)
# ==========================================
chart_data: dict = {}
funda_data: dict = {}
# KI-Sentiment (Stufe 1 + 2), vom Portfoliomanager-Agent erzeugt.
# Optional: fehlt die Datei, läuft alles rein deterministisch weiter.
# Vertrag (siehe docs/SENTIMENT_STAGE.md):
#   { "generated_at": "...",
#     "scores": { "<ISIN>": {"sentiment_score": int(-3..3), "veto": bool,
#                            "confidence": float(0..1), "event_kategorie": str,
#                            "begruendung": str} } }
# confidence/event_kategorie sind optional mit Default — ältere Dateien ohne
# diese Felder rechnen unverändert weiter (Default-Confidence 0.7 = weder
# gedämpft noch verstärkt, entspricht dem alten Verhalten näherungsweise).
sentiment_data: dict = {"scores": {}}
# Rohe Schlagzeilen (für den objektiven Recency-Decay, #2). Optional.
news_data: dict = {"items": {}}
# Earnings-/Guidance-Signal (#1). Optional — fehlt die Datei, bleibt der
# Earnings-Summand 0 und die Engine rechnet wie bisher.
earnings_data: dict = {"scores": {}}
isin_to_name: dict = {}
sector_map: dict = {}   # ISIN -> Sektor (aus Chartanalyse), für den Sektor-Cap.
dax_now = None
dax_closes: list = []
_beta_cache: dict = {}


def load_inputs():
    """Lädt Chart-/Funda-/Sentiment-Daten und die DAX-Referenz in die
    Modul-Globals. Kapselt alle Netzwerk-/Datei-Lesezugriffe der Engine."""
    global chart_data, funda_data, sentiment_data, news_data, earnings_data
    global isin_to_name, sector_map, dax_now, dax_closes
    chart_data = load_json(CHART, {})
    funda_data = load_json(FUNDA, {})
    sentiment_data = load_json(sentiment_path, {"scores": {}})
    news_data = load_json(news_path, {"items": {}})
    earnings_data = load_json(earnings_path, {"scores": {}})

    isin_to_name = {}
    sector_map = {}
    for data_set in [chart_data, funda_data]:
        for sector, items in data_set.get("sektoren", {}).items():
            for item in items:
                if item.get("isin") and item.get("isin") not in isin_to_name:
                    isin_to_name[item["isin"]] = item.get("wertpapier", "Unbekannt").replace(" (Teil 2)", "")
                if item.get("isin"):
                    sector_map.setdefault(item["isin"], sector)

    dax_now, dax_closes = ticker_map.fetch_index(DAX_SYMBOL)


# ==========================================
# SENTIMENT
# ==========================================

def get_sentiment(isin):
    """Returns (score, veto, begruendung, confidence, event_kategorie) — geklemmt und defensiv."""
    entry = sentiment_data.get("scores", {}).get(isin)
    if not entry:
        return 0, False, "", DEFAULT_CONFIDENCE, "Keine"
    try:
        s = int(round(float(entry.get("sentiment_score", 0))))
    except (TypeError, ValueError):
        s = 0
    s = max(SENTIMENT_MIN, min(SENTIMENT_MAX, s))
    try:
        conf = float(entry.get("confidence", DEFAULT_CONFIDENCE))
    except (TypeError, ValueError):
        conf = DEFAULT_CONFIDENCE
    conf = max(0.0, min(1.0, conf))
    kategorie = entry.get("event_kategorie") or "Sonstiges"
    return s, bool(entry.get("veto", False)), entry.get("begruendung", ""), conf, kategorie


def materiality_factor(kategorie):
    """Gewicht der Event-Kategorie (#2). Harte Katalysatoren (Zahlen/Guidance/
    M&A) voll, weiche (Analyst/Sonstiges) gedämpft. Unbekannt → 1.0."""
    return MATERIALITY_WEIGHTS.get(kategorie, DEFAULT_MATERIALITY)


def _newest_headline_age_days(isin):
    """Alter (in Tagen) der frischesten Schlagzeile zu dieser ISIN aus
    news_raw.json. None, wenn keine datierte Schlagzeile vorliegt."""
    entry = (news_data.get("items") or {}).get(isin)
    if not entry:
        return None
    heute = datetime.now().date()
    juengstes = None
    for h in entry.get("headlines", []):
        raw = (h.get("published") or "").strip()
        if not raw:
            continue
        d = None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = datetime.strptime(raw[:len(fmt) + 2], fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            try:
                d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
        if d > heute:            # fehlerhaft in der Zukunft → ignorieren
            continue
        if juengstes is None or d > juengstes:
            juengstes = d
    if juengstes is None:
        return None
    return max(0, (heute - juengstes).days)


def recency_factor(isin):
    """Objektiver Zeit-Decay (#2): 0.5**(Alter/HALF_LIFE), geklemmt auf
    [FLOOR, 1.0]. Kein datiertes Signal → 1.0 (kein Effekt)."""
    age = _newest_headline_age_days(isin)
    if age is None:
        return 1.0
    factor = 0.5 ** (age / RECENCY_HALF_LIFE_DAYS)
    return round(max(RECENCY_FLOOR, min(1.0, factor)), 3)


# ==========================================
# EARNINGS / GUIDANCE (#1)
# ==========================================

def get_earnings(isin):
    """Returns (score, confidence, guidance_richtung, horizon, begruendung) —
    geklemmt und defensiv. Fehlt die Datei/ISIN, neutral (0)."""
    entry = earnings_data.get("scores", {}).get(isin)
    if not entry:
        return 0, DEFAULT_CONFIDENCE, "keine", "", ""
    try:
        s = int(round(float(entry.get("earnings_score", 0))))
    except (TypeError, ValueError):
        s = 0
    s = max(SENTIMENT_MIN, min(SENTIMENT_MAX, s))
    try:
        conf = float(entry.get("confidence", DEFAULT_CONFIDENCE))
    except (TypeError, ValueError):
        conf = DEFAULT_CONFIDENCE
    conf = max(0.0, min(1.0, conf))
    richtung = entry.get("guidance_richtung") or "keine"
    horizon = entry.get("horizon") or ""
    return s, conf, richtung, horizon, entry.get("begruendung", "")


# ==========================================
# SCORING
# ==========================================

def get_chart_item(isin):
    if not isin:
        return None
    for sector, items in chart_data.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") == isin:
                return item
    return None


def get_funda_item(isin):
    if not isin:
        return None
    for sector, items in funda_data.get("sektoren", {}).items():
        for item in items:
            if item.get("isin") == isin:
                return item
    return None


def compute_chart_score(isin):
    """Chart-Score aus technischen Indikatoren (max ~15, min ~-13)."""
    item = get_chart_item(isin)
    if not item:
        return 0, []
    score = 0
    details = []

    emp = (item.get("empfehlung") or "").lower()
    if "kaufen" in emp:
        score += 3; details.append("Empf.+3")
    elif "verkauf" in emp:
        score -= 5; details.append("Empf.-5")

    trend = (item.get("trend") or "").lower()
    if "aufwärts" in trend and "leicht" not in trend:
        score += 2; details.append("Trend+2")
    elif "leicht" in trend and "aufwärts" in trend:
        score += 1; details.append("Trend+1")
    elif "leicht" in trend and "abwärts" in trend:
        score -= 1; details.append("Trend-1")
    elif "abwärts" in trend:
        score -= 3; details.append("Trend-3")

    rsi = item.get("rsi_14")
    if rsi is not None:
        if rsi < 30:
            score += 3; details.append(f"RSI+3({rsi:.0f})")
        elif rsi < 50:
            score += 2; details.append(f"RSI+2({rsi:.0f})")
        elif rsi < 65:
            score += 1; details.append(f"RSI+1({rsi:.0f})")
        elif rsi > 75:
            score -= 2; details.append(f"RSI-2({rsi:.0f})")

    macd = item.get("macd", "")
    if macd == "Positiv":
        score += 2; details.append("MACD+2")
    elif macd == "Neutral":
        score += 1; details.append("MACD+1")
    elif macd == "Negativ":
        score -= 1; details.append("MACD-1")

    kurs = item.get("aktueller_kurs") or 0
    sma50 = item.get("sma_50") or 0
    sma200 = item.get("sma_200") or 0
    if kurs > 0 and sma50 > 0 and kurs > sma50:
        score += 1; details.append("SMA50+1")
    if kurs > 0 and sma200 > 0 and kurs > sma200:
        score += 1; details.append("SMA200+1")

    # 12-1-Monats-Momentum (Return t-252 bis t-21, letzter Monat ausgeklammert
    # gegen Kurzfrist-Reversal). None = zu kurze Historie, wird neutral gewertet.
    mom = item.get("momentum_12_1")
    if mom is not None:
        if mom > 20:
            score += 3; details.append(f"Mom+3({mom:.0f}%)")
        elif mom > 5:
            score += 2; details.append(f"Mom+2({mom:.0f}%)")
        elif mom > 0:
            score += 1; details.append(f"Mom+1({mom:.0f}%)")
        elif mom > -10:
            score -= 1; details.append(f"Mom-1({mom:.0f}%)")
        else:
            score -= 2; details.append(f"Mom-2({mom:.0f}%)")

    return score, details


def is_funda_placeholder(item):
    b = (item.get("begruendung") or "").lower()
    return any(m in b for m in _FUNDA_PLACEHOLDER_MARKERS)


def compute_funda_score(isin):
    """Fundamental-Score (max ~17, min ~-14)."""
    item = get_funda_item(isin)
    if not item:
        return 0, []
    # Platzhalter-Fundamentaldaten neutral werten (keine erfundenen Kennzahlen
    # ins Scoring einfließen lassen).
    if is_funda_placeholder(item):
        return 0, ["Funda=Platzhalter→0"]
    score = 0
    details = []

    emp = (item.get("empfehlung") or "").lower()
    if emp and emp != "n/a":
        if "kaufen" in emp:
            score += 3; details.append("Empf.+3")
        elif "verkauf" in emp:
            score -= 5; details.append("Empf.-5")

    bew = (item.get("bewertung") or "").lower()
    if "attraktiv" in bew:
        score += 2; details.append("Bew.+2")
    elif "neutral" in bew:
        score += 1; details.append("Bew.+1")
    elif "unattraktiv" in bew:
        score -= 1; details.append("Bew.-1")

    risiko = (item.get("risiko") or "").lower()
    if "niedrig" in risiko:
        score += 2; details.append("Risiko+2")
    elif "mittel" in risiko:
        score += 1; details.append("Risiko+1")
    elif "hoch" in risiko:
        score -= 1; details.append("Risiko-1")

    gw = item.get("gewinnwachstum_yoy")
    if gw is not None:
        if gw > 20:
            score += 2; details.append(f"GW+2({gw:.0f}%)")
        elif gw > 5:
            score += 1; details.append(f"GW+1({gw:.0f}%)")
        elif gw < 0:
            score -= 1; details.append(f"GW-1({gw:.0f}%)")

    # Deterministische Yahoo-Kennzahlen (Phase 2) — ergänzen die LLM-Bewertung
    # um kapitalstruktur-/wachstumsneutrale Signale. None = nicht verfügbar,
    # wird neutral gewertet statt erfunden.
    peg = item.get("peg_ratio")
    if peg is not None:
        if 0 < peg < 1:
            score += 2; details.append(f"PEG+2({peg:.2f})")
        elif peg < 1.5:
            score += 1; details.append(f"PEG+1({peg:.2f})")
        elif peg > 3:
            score -= 1; details.append(f"PEG-1({peg:.2f})")

    roe = item.get("roe")
    if roe is not None:
        if roe > 20:
            score += 2; details.append(f"ROE+2({roe:.0f}%)")
        elif roe > 10:
            score += 1; details.append(f"ROE+1({roe:.0f}%)")
        elif roe < 0:
            score -= 2; details.append(f"ROE-2({roe:.0f}%)")

    ev_ebitda = item.get("ev_ebitda")
    if ev_ebitda is not None:
        if ev_ebitda < 0:
            score -= 2; details.append(f"EV/EBITDA-2(neg.)")
        elif ev_ebitda < 8:
            score += 2; details.append(f"EV/EBITDA+2({ev_ebitda:.1f})")
        elif ev_ebitda < 12:
            score += 1; details.append(f"EV/EBITDA+1({ev_ebitda:.1f})")
        elif ev_ebitda > 20:
            score -= 1; details.append(f"EV/EBITDA-1({ev_ebitda:.1f})")

    # Piotroski F-Score (Phase 4): Bilanzqualität, 0-9. Hoch = solide/
    # sich verbessernd, niedrig = Warnsignal/Value-Falle. None = neutral.
    piotroski = item.get("piotroski")
    if piotroski is not None:
        if piotroski >= 7:
            score += 2; details.append(f"Piotroski+2(F{piotroski})")
        elif piotroski >= 5:
            score += 1; details.append(f"Piotroski+1(F{piotroski})")
        elif piotroski <= 2:
            score -= 2; details.append(f"Piotroski-2(F{piotroski})")

    return score, details


def total_score(isin):
    cs, cd = compute_chart_score(isin)
    fs, fd = compute_funda_score(isin)
    ss, _, _, confidence, kategorie = get_sentiment(isin)
    # Sentiment-Gewichtung, drei Achsen (#2):
    #  - confidence: wie belastbar ist das Urteil (LLM, subjektiv)
    #  - materiality: wie hart ist die Event-Kategorie (Zahlen/Guidance/M&A > Analyst/Sonstiges)
    #  - recency: objektiver Zeit-Decay aus dem Datum der frischesten Schlagzeile
    mat = materiality_factor(kategorie)
    rec = recency_factor(isin)
    ss_weighted = round(ss * confidence * mat * rec)
    sd = ([f"KI-Sentiment{'+' if ss >= 0 else ''}{ss}×conf{confidence:.1f}"
           f"×mat{mat:.2f}({kategorie})×rec{rec:.2f}={ss_weighted:+d}"]
          if ss != 0 else [])

    # Earnings/Guidance-Signal (#1): eigener, forward-looking Summand, gedämpft.
    es, es_conf, es_richtung, _, _ = get_earnings(isin)
    es_weighted = round(es * es_conf * EARNINGS_WEIGHT)
    ed = ([f"Earnings{'+' if es >= 0 else ''}{es}×conf{es_conf:.1f}"
           f"×{EARNINGS_WEIGHT:g}({es_richtung})={es_weighted:+d}"]
          if es != 0 else [])

    # Sanity-Check gegen halluzinierte/veraltete Indikatoren — dieselbe Logik
    # wie im Dashboard (dataConsistency()). Bei Inkonsistenz wird der
    # Chart-Score wie in der Anzeige halbiert, statt die Warnung zu ignorieren.
    warnings = data_consistency(get_chart_item(isin), get_funda_item(isin))
    if warnings:
        cs_adj = cs * 0.5
        cd = cd + [f"⚠️Inkonsistent→Chart×0.5({cs}→{cs_adj:g})"]
        cs = cs_adj

    return cs + fs + ss_weighted + es_weighted, cs, cd, fs, fd, ss, sd + ed


def score_reason(isin):
    ts, cs, cd, fs, fd, ss, sd = total_score(isin)
    c_item = get_chart_item(isin)
    f_item = get_funda_item(isin)
    c_text = c_item.get("begruendung", "") if c_item else ""
    f_text = f_item.get("begruendung", "") if f_item else ""
    _, _, s_text, _, _ = get_sentiment(isin)
    es, _, _, _, e_text = get_earnings(isin)
    reason = (
        f"Score={ts} (Chart={cs}: {', '.join(cd)}; Funda={fs}: {', '.join(fd)}"
    )
    if ss != 0:
        reason += f"; KI-Sentiment={ss}"
    if es != 0:
        reason += f"; Earnings={es}"
    reason += f") | Chart: {c_text} | Funda: {f_text}"
    if s_text:
        reason += f" | KI: {s_text}"
    if es != 0 and e_text:
        reason += f" | Earnings: {e_text}"
    return reason


# ==========================================
# POSITIONSGRÖSSE
# ==========================================

def budget_for_score(ts, buy_threshold):
    """Positionsgröße proportional zum Score: 1000€ Basis + 100€ je Punkt über Schwellwert, max 2500€."""
    bonus = max(0, ts - buy_threshold) * BUDGET_PER_POINT
    return min(BUDGET_MAX, BUDGET_BASE + bonus)


def vol_size_multiplier(isin):
    """Inverser Volatilitäts-Faktor auf Basis der 20-Tage-Vola (compute_indicators).
    Fehlt die Vola, bleibt es bei 1.0 (kein Effekt)."""
    item = get_chart_item(isin)
    vol = item.get("volatility_20d") if item else None
    if not vol or vol <= 0:
        return 1.0
    return round(max(VOL_MULT_MIN, min(VOL_MULT_MAX, REF_VOL_PCT / vol)), 3)


def dyn_stop_distance(isin):
    """Volatilitätsskalierte Trailing-Stop-Distanz (positiv, z.B. 0.12 = -12%).
    None, wenn keine 20-Tage-Vola vorliegt (Stop dann inaktiv)."""
    item = get_chart_item(isin)
    vol = item.get("volatility_20d") if item else None
    if not vol or vol <= 0:
        return None
    dist = DYN_STOP_VOL_MULT * (vol / 100.0) * math.sqrt(DYN_STOP_HORIZON_DAYS)
    return round(max(DYN_STOP_MIN, min(DYN_STOP_MAX, dist)), 4)


def is_watch_candidate(isin, chart_item, funda_item):
    """Kandidat noch nicht kaufbar (nicht genug Historie / Marker-Text).

    Zwei Signale zählen:
    1. Explizite Watch-Markierung im Fundamental- oder Chart-Text
       (Opportunity-Scan hinterlässt sie beim Einfügen).
    2. Chart-Indikatoren noch nicht belastbar: kein SMA200 vorhanden ODER
       kein `indicators_source` gesetzt (noch nie durch compute_indicators
       gelaufen). Dann fehlt die halbe Chart-Score-Basis.
    """
    for it in (chart_item, funda_item):
        if it and any(m in ((it.get("begruendung") or "").lower()) for m in WATCH_MARKERS):
            return True
    if chart_item is not None:
        if chart_item.get("sma_200") in (None, 0):
            return True
        if not chart_item.get("indicators_source"):
            return True
    return False


def compute_adaptive_buy_threshold(scores):
    """Adaptive Kaufschwelle aus den aktuellen Kandidatenscores.

    scores = Liste aller Nicht-Verkaufen-Nicht-Watch-Scores. Ergebnis ist
    max(BUY_FLOOR, 80er-Perzentil). Fallback auf BUY_FALLBACK_THRESHOLD,
    wenn zu wenige Datenpunkte für sinnvolles Perzentil vorliegen.
    """
    active = [s for s in scores if s is not None]
    if len(active) < BUY_MIN_CANDIDATES:
        return BUY_FALLBACK_THRESHOLD
    ordered = sorted(active)
    # 80. Perzentil ~ oberste 20 %
    idx = int(len(ordered) * BUY_PERCENTILE)
    idx = min(idx, len(ordered) - 1)
    return max(BUY_FLOOR, ordered[idx])


# ==========================================
# SEKTOR-/CASH-LIMITS
# ==========================================

def sector_value(positions, sektor):
    return sum(p.get("boersenwert", 0) or 0 for p in positions
               if sector_map.get(p.get("isin")) == sektor)


def capped_budget(budget, isin, positions):
    """Kappt das Kaufbudget, falls es einen Sektor über SEKTOR_SOFT_CAP triebe.

    Muss zum Sektor-Abbau (Phase 1b) passen: würde die Kaufphase noch bis zum
    alten 60%-Hardcap zukaufen, würde sie das gerade zurückgeführte Übergewicht
    sofort wieder aufbauen (Rotation statt Entzerrung). Daher dieselbe 30%-Grenze
    wie der Abbau. Löst sek_val + x = CAP * (portfolio_value + x) nach x auf.
    Positionen ohne Sektor-Zuordnung sind vom Cap ausgenommen."""
    sektor = sector_map.get(isin)
    if not sektor:
        return budget
    portfolio_value = sum(p.get("boersenwert", 0) or 0 for p in positions)
    # Bootstrap-Guard: bei (fast) leerem Portfolio wäre JEDER Erstkauf >30%
    # "Sektoranteil" — die Formel liefe auf allowed=0 und die Engine könnte ein
    # leergelaufenes Depot nie wieder aufbauen. Cap greift erst, wenn schon
    # nennenswert investiert ist.
    if portfolio_value < BUDGET_BASE:
        return budget
    sek_val = sector_value(positions, sektor)
    if portfolio_value + budget <= 0:
        return budget
    projected_pct = (sek_val + budget) / (portfolio_value + budget)
    if projected_pct <= SEKTOR_SOFT_CAP:
        return budget
    allowed = (SEKTOR_SOFT_CAP * portfolio_value - sek_val) / (1 - SEKTOR_SOFT_CAP)
    return max(0.0, min(budget, allowed))


def cash_reserve(state):
    """Dynamische Mindest-Barreserve: 2% des Gesamtvermögens, mind. 25€."""
    total = state.current_cash + sum(p.get("boersenwert", 0) or 0 for p in state.positions)
    return max(MIN_CASH_RESERVE, CASH_RESERVE_PCT * total)


def position_capped_budget(budget, positions):
    """Kappt ein Kaufbudget auf den Einzelpositions-Cap: die NEUE Position darf
    nach dem Kauf höchstens MAX_POS_PCT des Portfolios ausmachen.
    Löst x / (P + x) = CAP nach x auf. Gleicher Bootstrap-Guard wie beim
    Sektor-Cap (leeres Depot muss wieder kaufen können)."""
    portfolio_value = sum(p.get("boersenwert", 0) or 0 for p in positions)
    if portfolio_value < BUDGET_BASE:
        return budget
    allowed = MAX_POS_PCT * portfolio_value / (1 - MAX_POS_PCT)
    return max(0.0, min(budget, allowed))


def get_live_price(isin):
    """EUR live price via the shared ticker map, guarded against wrong instruments.

    Returns None for ISINs without a reliable EUR listing (they must not become
    buy candidates) or when the price is implausible vs. the chart SMA50.
    """
    price, _src = ticker_map.eur_price(isin)
    if price is None:
        return None
    c_item = get_chart_item(isin) or {}
    if not ticker_map.plausible(price, c_item.get('sma_50')):
        return None
    return price


# ==========================================
# AUTO-BETA (relativer Stop-Loss vs. DAX)
# ==========================================

def _daily_returns(closes):
    out = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            out.append((closes[i] - prev) / prev)
    return out


def get_beta(isin):
    """Auto-Beta der Position ggü. DAX via Kovarianz/Varianz der Tagesrenditen.
    Geklemmt auf [BETA_MIN, BETA_MAX]; Fallback BETA_DEFAULT (1.0) bei zu wenig
    oder unzuverlässigen Daten."""
    if isin in _beta_cache:
        return _beta_cache[isin]
    beta = BETA_DEFAULT
    try:
        if dax_closes and len(dax_closes) >= 61:
            closes, _latest, _src = ticker_map.eur_history(isin)
            if closes and len(closes) >= 61:
                n = min(len(closes), len(dax_closes))
                s = _daily_returns(closes[-n:])
                d = _daily_returns(dax_closes[-n:])
                m = min(len(s), len(d))
                if m >= 60:
                    s, d = s[-m:], d[-m:]
                    md = sum(d) / m
                    var = sum((x - md) ** 2 for x in d)   # Summe; /m kürzt sich
                    if var > 0:
                        ms = sum(s) / m
                        cov = sum((s[i] - ms) * (d[i] - md) for i in range(m))
                        beta = max(BETA_MIN, min(BETA_MAX, cov / var))
    except Exception:
        beta = BETA_DEFAULT
    _beta_cache[isin] = round(beta, 3)
    return _beta_cache[isin]


# ==========================================
# TRANSAKTIONS-DATENSÄTZE
# ==========================================

def _today_iso():
    return datetime.now().strftime("%Y-%m-%d")


def _make_sell_record(p, price, notiz, begruendung, units=None):
    """Berechne Netto-Erlös (nach Gebühr & Steuer) und baue Verkaufs-Transaktion.

    Steuer greift nur bei tatsächlichem Gewinn (Brutto-Verlust ist steuerfrei).
    Der zurückgegebene `net_cash` gehört auf `current_cash` addiert, `tx`
    kommt in die Transaktionshistorie. `units` erlaubt TEILverkauf (z.B.
    Positions-Cap-Trim); der Einstand wird dann anteilig gerechnet — die
    Position selbst muss der Aufrufer anpassen.
    """
    stueck = p["stueck"]
    units = stueck if units is None else min(units, stueck)
    invest_share = (p["investiert"] * units / stueck) if stueck else p["investiert"]
    revenue = (units * price) - fee_per_trade
    gv_brutto = revenue - invest_share
    steuern = round(gv_brutto * CAP_GAINS_TAX, 2) if gv_brutto > 0 else 0.0
    net_cash = revenue - steuern
    tx = {
        "datum": _today_iso(),
        "typ": "Verkauf",
        "isin": p.get("isin"),
        "wertpapier": p.get("wertpapier", p.get("isin")),
        "stueck": units,
        "kurs": price,
        "gebuehr": fee_per_trade,
        "steuern": steuern,
        "gewinn_verlust": round(gv_brutto, 2),
        "gesamt": round(net_cash, 2),
        "notiz": notiz,
        "begruendung": begruendung,
    }
    return tx, net_cash


def _make_buy_record(isin, stock, units, price, ts, begruendung):
    """Baue Kauf-Transaktion. Rückgabewert `total_cost` gehört von `current_cash` abgezogen."""
    total_cost = units * price + fee_per_trade
    tx = {
        "datum": _today_iso(),
        "typ": "Kauf",
        "isin": isin,
        "wertpapier": stock,
        "stueck": units,
        "kurs": price,
        "gebuehr": fee_per_trade,
        "steuern": 0.0,
        "gewinn_verlust": 0.0,
        "gesamt": round(total_cost, 2),
        "notiz": f"Neukauf (Score={ts})",
        "begruendung": begruendung,
    }
    return tx, total_cost


# ==========================================
# LAUF-ZUSTAND
# ==========================================

@dataclass
class RunState:
    """Veränderlicher Zustand eines Engine-Laufs, den die Phasen fortschreiben."""
    current_cash: float
    positions: list
    transactions: list
    initial_tx_count: int
    summary: list = field(default_factory=list)
    live_prices: dict = field(default_factory=dict)
    sold_isins: set = field(default_factory=set)  # in diesem Lauf verkauft -> kein Rückkauf
    buy_threshold: int = 0
    target_isins_scored: list = field(default_factory=list)
    target_isins: list = field(default_factory=list)


# ==========================================
# PLANUNGSPHASE: ZIELPORTFOLIO MIT SCORING
# Kauf-Kandidaten: Score >= adaptivem BUY_THRESHOLD,
# kein explizites "Verkaufen" in chart UND funda, nicht Watch.
# ==========================================

def phase_plan(state):
    """Sammelt aktive Scores, bestimmt die adaptive Kaufschwelle und die
    (live-bepreisten) Kauf-Kandidaten. Schreibt Ziel-Listen in `state`."""
    all_isins = set()
    for data_set in [chart_data, funda_data]:
        for sector, items in data_set.get("sektoren", {}).items():
            for item in items:
                if item.get("isin"):
                    all_isins.add(item["isin"])

    # Schritt 1: alle aktiven Scores sammeln (Watch/Verkauf/Veto aussortieren).
    # Watch-Kandidaten wandern in eine Merkliste — sie werden nicht gekauft,
    # bleiben aber sichtbar für Reporting/Dashboard.
    active_scores = []
    watch_list = []
    for isin in all_isins:
        c_item = get_chart_item(isin)
        f_item = get_funda_item(isin)
        if not c_item or not f_item:
            continue
        c_emp = (c_item.get("empfehlung") or "").lower()
        f_emp = (f_item.get("empfehlung") or "").lower()
        if "verkauf" in c_emp or "verkauf" in f_emp:
            continue
        # Stufe 2: KI-Veto blockiert Neukäufe (kann nie welche erzeugen).
        _, veto, veto_reason, _, _ = get_sentiment(isin)
        if veto:
            state.summary.append(f"KI-Veto: Kauf von {c_item.get('wertpapier', isin)} ({isin}) blockiert. {veto_reason}")
            continue
        if is_watch_candidate(isin, c_item, f_item):
            ts_watch = total_score(isin)[0]
            watch_list.append((isin, ts_watch))
            continue
        ts = total_score(isin)[0]
        active_scores.append((isin, ts))

    # Schritt 2: adaptive Schwelle aus den aktiven Scores bestimmen.
    buy_threshold = compute_adaptive_buy_threshold([ts for _, ts in active_scores])
    state.buy_threshold = buy_threshold

    # Schritt 3: Kandidaten oberhalb der adaptiven Schwelle selektieren.
    scored_candidates = [(isin, ts) for isin, ts in active_scores if ts >= buy_threshold]
    scored_candidates.sort(key=lambda x: -x[1])

    if watch_list:
        watch_list.sort(key=lambda x: -x[1])
        watch_names = [f"{isin_to_name.get(i, i)}({t})" for i, t in watch_list[:5]]
        state.summary.append(f"Watch-Modus: {len(watch_list)} Kandidat(en) noch nicht kaufbar "
                             f"(fehlende Historie). Top: {', '.join(watch_names)}.")
    state.summary.append(f"Adaptive Kaufschwelle: {buy_threshold} "
                         f"(Floor {BUY_FLOOR}, {int(BUY_PERCENTILE*100)}er-Perzentil "
                         f"aus {len(active_scores)} aktiven Kandidaten).")

    target_isins_scored = []
    for isin, ts in scored_candidates:
        price = get_live_price(isin)
        if price:
            state.live_prices[isin] = price
            target_isins_scored.append((isin, ts))

    state.target_isins_scored = target_isins_scored
    state.target_isins = [isin for isin, _ in target_isins_scored]


# ==========================================
# 1. STRATEGISCHER VERKAUF
# Auslöser: empfehlung=Verkaufen ODER Score < SELL_THRESHOLD
# ==========================================

def phase_strategic_sell(state):
    positions_to_keep = []
    for p in state.positions:
        isin = p.get("isin")
        stock = p.get("wertpapier", isin)

        c_item = get_chart_item(isin)
        f_item = get_funda_item(isin)
        c_emp = (c_item.get("empfehlung") or "").lower() if c_item else ""
        f_emp = (f_item.get("empfehlung") or "").lower() if f_item else ""
        ts = total_score(isin)[0]

        current_price = state.live_prices.get(isin) or get_live_price(isin) or p.get("boersenkurs", 0)
        if current_price:
            state.live_prices[isin] = current_price

        kaufkurs = p.get("kaufkurs", 0) or 0
        drawdown = ((current_price - kaufkurs) / kaufkurs) if (kaufkurs and current_price) else 0.0

        # Marktbereinigung: Alpha = relativer Drawdown SEIT DEM ANKER minus die
        # beta-erwartete DAX-Bewegung seit demselben Anker. Kurs- und DAX-Anker
        # (stop_ref_kurs, dax_ref) werden IMMER gemeinsam gesetzt, damit beide
        # denselben Zeithorizont haben (sonst würde ein Alt-Verlust fälschlich als
        # Alpha gewertet). Neukäufe verankern beim Kauf, Altpositionen beim ersten
        # Lauf auf heute (relative Uhr startet dann bei 0).
        beta = get_beta(isin)
        dax_ref = p.get("dax_ref")
        ref_kurs = p.get("stop_ref_kurs")
        rel_dd = None
        r_dax = None
        alpha = None
        if dax_ref and ref_kurs and dax_now and current_price:
            rel_dd = (current_price - ref_kurs) / ref_kurs
            r_dax = (dax_now - dax_ref) / dax_ref
            alpha = rel_dd - beta * r_dax

        sell = False
        sell_reason = ""
        if "verkauf" in c_emp or "verkauf" in f_emp:
            sell = True
            sell_reason = f"Explizites Verkaufen-Signal (Score={ts})"
        elif drawdown <= ABS_HARD_STOP_PCT:
            sell = True
            sell_reason = f"Absoluter Hard-Stop ({drawdown*100:.1f}% ≤ {ABS_HARD_STOP_PCT*100:.0f}%)"
        elif alpha is not None and rel_dd < 0 and alpha <= REL_STOP_PCT:
            sell = True
            sell_reason = (f"Relativer Stop: {alpha*100:.1f}% Underperformance vs. DAX "
                           f"(β={beta:.2f}, seit Anker: Kurs {rel_dd*100:+.1f}% / "
                           f"DAX {r_dax*100:+.1f}%) ≤ {REL_STOP_PCT*100:.0f}%")
        elif (rel_dd is not None and (dyn_dist := dyn_stop_distance(isin)) is not None
              and rel_dd <= -dyn_dist):
            sell = True
            sell_reason = (f"Dynamischer Vola-Stop: {rel_dd*100:.1f}% vom Anker "
                           f"{ref_kurs:.2f} ≤ -{dyn_dist*100:.1f}% "
                           f"(2×Vola-Distanz, Vola {get_chart_item(isin).get('volatility_20d')}%/Tag)")
        elif ts < SELL_THRESHOLD:
            sell = True
            sell_reason = f"Score unter Schwellwert ({ts} < {SELL_THRESHOLD})"

        if sell:
            begruendung = sell_reason + " | " + score_reason(isin)
            tx, net_cash = _make_sell_record(p, current_price,
                                             notiz=f"Strategischer Verkauf ({sell_reason})",
                                             begruendung=begruendung)
            state.current_cash += net_cash
            state.sold_isins.add(isin)
            state.summary.append(f"Strategischer Verkauf: {p['stueck']}x {stock} ({isin}) zu {current_price:.2f} EUR. {sell_reason}.")
            state.transactions.append(tx)
        else:
            p["boersenkurs"] = current_price
            p["boersenwert"] = round(p["stueck"] * p["boersenkurs"], 2)
            p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
            p["score"] = ts
            p["beta"] = beta
            # Review-Flag: starkes Negativ-Sentiment auf BESTEHENDER Position ist
            # kein Verkaufsgrund (das entscheidet weiter der harte Score / Stop),
            # aber sichtbar machen statt stillschweigend zu ignorieren.
            sent_score, _, sent_reason, _, sent_kategorie = get_sentiment(isin)
            if sent_score <= REVIEW_FLAG_THRESHOLD:
                p["review_flag"] = True
                p["review_grund"] = f"KI-Sentiment {sent_score} ({sent_kategorie}): {sent_reason}"
            else:
                p.pop("review_flag", None)
                p.pop("review_grund", None)
            # Anker-Paar (Kurs + DAX) gemeinsam auf heute setzen, falls (noch) nicht
            # vorhanden — Altpositionen ohne Kaufdatum: relative Uhr startet bei 0.
            if dax_now and current_price and (not p.get("dax_ref") or not p.get("stop_ref_kurs")):
                p["dax_ref"] = round(dax_now, 2)
                p["stop_ref_kurs"] = round(current_price, 4)
            # TRAILING-STOP: macht die Position ein neues Hoch, wandert das Anker-Paar
            # (Höchststand-Referenz) mit nach oben. Der relative Stop misst den
            # beta-bereinigten Rückgang dann vom PEAK statt vom Einstieg — aufgelaufene
            # Gewinne werden so mitgesichert. Anker nur nach oben (Ratchet), nie zurück,
            # daher werden Gewinne nie wieder komplett hergegeben, bevor der Stop greift.
            elif dax_now and current_price and current_price > (p.get("stop_ref_kurs") or 0):
                p["stop_ref_kurs"] = round(current_price, 4)
                p["dax_ref"] = round(dax_now, 2)
            positions_to_keep.append(p)

    state.positions = positions_to_keep


# ==========================================
# 1b. SEKTOR-ABBAU (Klumpenrisiko aktiv zurückführen)
# capped_budget() bremst nur NEUE Käufe (Wachstums-Limit). Diese Phase reduziert
# ein bereits bestehendes Übergewicht: überschreitet ein Sektor SEKTOR_SOFT_CAP,
# werden die schwächsten Positionen (niedrigster Score zuerst) dieses Sektors
# ganz verkauft, bis der Sektor wieder <= Cap liegt. Freigesetzter Cash bleibt
# als Puffer oder finanziert Nicht-Sektor-Käufe in der Kaufphase.
# ==========================================

def _sector_pct(pos, sektor):
    tot = sum(p.get("boersenwert", 0) or 0 for p in pos)
    return (sector_value(pos, sektor) / tot) if tot > 0 else 0.0


def phase_sector_reduction(state):
    sektoren_im_depot = sorted({sector_map.get(p.get("isin")) for p in state.positions
                                if sector_map.get(p.get("isin"))})
    for sektor in sektoren_im_depot:
        # Hysterese: nur eingreifen, wenn der Sektor spürbar (Cap+Toleranz) über dem
        # Limit liegt. Danach bis auf den reinen Cap zurückführen.
        if _sector_pct(state.positions, sektor) <= SEKTOR_SOFT_CAP + SEKTOR_CAP_TOLERANCE:
            continue
        kandidaten = sorted(
            [p for p in state.positions if sector_map.get(p.get("isin")) == sektor],
            key=lambda p: (p.get("score", 0),
                           p["gewinn_verlust"] / p["investiert"] if p.get("investiert") else 0),
        )
        for p in kandidaten:
            pct_before = _sector_pct(state.positions, sektor)
            if pct_before <= SEKTOR_SOFT_CAP:
                break
            isin = p.get("isin")
            price = p.get("boersenkurs") or get_live_price(isin) or 0
            if not price:
                continue
            begruendung = (f"Sektor-Abbau: {sektor} bei {pct_before*100:.1f}% "
                           f"(> {SEKTOR_SOFT_CAP*100:.0f}%-Cap) | " + score_reason(isin))
            tx, net_cash = _make_sell_record(
                p, price,
                notiz=f"Sektor-Abbau ({sektor} über {SEKTOR_SOFT_CAP*100:.0f}%-Cap)",
                begruendung=begruendung)
            state.current_cash += net_cash
            state.sold_isins.add(isin)
            state.summary.append(f"Sektor-Abbau: {p['stueck']}x {p.get('wertpapier', isin)} "
                                 f"({isin}) zu {price:.2f} EUR verkauft — {sektor} war "
                                 f"{pct_before*100:.1f}% (Cap {SEKTOR_SOFT_CAP*100:.0f}%, "
                                 f"Score={p.get('score', 0)}).")
            state.transactions.append(tx)
            state.positions.remove(p)


# ==========================================
# 1c. EINZELPOSITIONS-TRIM (Konzentrationsrisiko auf Positionsebene)
# Überschreitet eine Position MAX_POS_PCT + Toleranz, wird sie per TEILverkauf
# auf den Cap zurückgestutzt. Kein Ganzverkauf: die Position ist typischerweise
# ein Gewinner — nur das Übergewicht wird abgeschöpft (Rebalancing-Gewinnmitnahme).
# ==========================================

def phase_position_trim(state):
    # Erreichbarkeits-Guard: mit n Positionen ist die kleinste erreichbare
    # Maximal-Quote 1/n. Bei n < 5 wäre der 20%-Cap unerreichbar und die
    # Schleife würde das Depot in eine Verkaufsspirale trimmen (jeder Verkauf
    # senkt den Nenner und hebt die Quote der übrigen). Dann kein Eingriff —
    # ein ausgedünntes Depot (z.B. nach Massen-Stop-out) wird erst wieder
    # aufgebaut, bevor Konzentrations-Feintuning sinnvoll ist.
    if len(state.positions) < math.ceil(1 / MAX_POS_PCT):
        return
    # Jede Position wird pro Lauf höchstens EINMAL getrimmt (größte zuerst).
    # Kein while-Loop: Trims verkleinern den Depotwert und hebeln die Quoten
    # der übrigen Positionen — Rest-Überschreitungen innerhalb der Toleranz
    # fängt der nächste Tageslauf, statt hier zu spiralen.
    for p in sorted(state.positions, key=lambda q: -(q.get("boersenwert", 0) or 0)):
        tot = sum(q.get("boersenwert", 0) or 0 for q in state.positions)
        if tot <= 0:
            return
        pct_before = (p.get("boersenwert", 0) or 0) / tot
        if pct_before <= MAX_POS_PCT + POS_CAP_TOLERANCE:
            continue
        isin = p.get("isin")
        price = p.get("boersenkurs") or state.live_prices.get(isin) or 0
        if not price or p.get("stueck", 0) <= 1:
            continue
        # Stückzahl, damit die Position nach Verkauf genau auf dem Cap landet:
        # (wert - u*price) / (tot - u*price) = CAP  ->  u = (wert - CAP*tot) / (price*(1-CAP))
        need = (p["boersenwert"] - MAX_POS_PCT * tot) / (price * (1 - MAX_POS_PCT))
        units = min(max(1, math.ceil(need)), p["stueck"] - 1)
        grund = (f"Positions-Cap: {p.get('wertpapier', isin)} bei {pct_before*100:.1f}% "
                 f"(> {MAX_POS_PCT*100:.0f}%-Cap) — Teilverkauf {units} Stück")
        tx, net_cash = _make_sell_record(
            p, price,
            notiz=f"Positions-Trim ({pct_before*100:.1f}% > {MAX_POS_PCT*100:.0f}%-Cap)",
            begruendung=grund + " | " + score_reason(isin),
            units=units)
        state.current_cash += net_cash
        state.transactions.append(tx)
        remaining = p["stueck"] - units
        p["investiert"] = round(p["investiert"] * remaining / p["stueck"], 2)
        p["stueck"] = remaining
        p["boersenwert"] = round(remaining * price, 2)
        p["gewinn_verlust"] = round(p["boersenwert"] - p["investiert"], 2)
        state.summary.append(f"Positions-Trim: {units}x {p.get('wertpapier', isin)} ({isin}) "
                             f"zu {price:.2f} EUR verkauft — Position war {pct_before*100:.1f}% "
                             f"(Cap {MAX_POS_PCT*100:.0f}%).")


# ==========================================
# 2. ERMITTELN DES KAPITALBEDARFS
# Positionsgröße ist score-abhängig
# ==========================================

def compute_capital_need(state):
    """(unowned_targets, total_needed_cash) für die Rebalancing-/Kaufphase."""
    unowned_targets = [(isin, ts) for isin, ts in state.target_isins_scored
                       if not any(p.get("isin") == isin for p in state.positions)
                       and isin not in state.sold_isins]
    total_needed_cash = sum(budget_for_score(ts, state.buy_threshold) * vol_size_multiplier(isin)
                            for isin, ts in unowned_targets)
    return unowned_targets, total_needed_cash


# ==========================================
# 3. REBALANCING (Schwache Halten-Positionen verkaufen)
# Sortiert nach schlechtestem Score (schwächste zuerst)
# ==========================================

def phase_rebalance(state, total_needed_cash):
    halten_positions = [p for p in state.positions
                        if p.get("isin") not in state.target_isins
                        and p.get("score", 0) < REBALANCE_THRESHOLD]
    halten_positions.sort(key=lambda p: (p.get("score", 0), p["gewinn_verlust"] / p["investiert"] if p["investiert"] > 0 else 0))

    for p in halten_positions:
        if state.current_cash >= total_needed_cash:
            break
        isin = p.get("isin")
        stock = p.get("wertpapier", isin)
        price = p["boersenkurs"]
        begruendung = "Rebalancing | " + score_reason(isin)
        tx, net_cash = _make_sell_record(p, price,
                                         notiz="Rebalancing (Kapitalbeschaffung für Neukäufe)",
                                         begruendung=begruendung)
        state.current_cash += net_cash
        state.summary.append(f"Rebalancing-Verkauf: {p['stueck']}x {stock} ({isin}) zu {price:.2f} EUR (Score={p.get('score',0)}).")
        state.transactions.append(tx)
        state.positions.remove(p)


# ==========================================
# 4. NEUKÄUFE — höchster Score zuerst, Größe score-abhängig
# ==========================================

def phase_buy(state, unowned_targets):
    for isin, ts in unowned_targets:
        if isin not in state.live_prices:
            continue
        price = state.live_prices[isin]
        stock = isin_to_name.get(isin, isin)
        vol_mult = vol_size_multiplier(isin)
        budget = budget_for_score(ts, state.buy_threshold) * vol_mult
        # Dynamische Mindest-Barreserve (2% Gesamtvermögen) nie unterschreiten.
        spendable = state.current_cash - cash_reserve(state)
        budget_before_cap = min(budget, spendable)
        # Erst Sektor-Cap, dann Einzelpositions-Cap — beide sind Wachstums-Limits.
        budget_for_this = capped_budget(budget_before_cap, isin, state.positions)
        budget_for_this = position_capped_budget(budget_for_this, state.positions)
        if budget_for_this < MIN_ORDER_VALUE + fee_per_trade:
            if budget_for_this < budget_before_cap:
                state.summary.append(f"Sektor-Cap: Kauf von {stock} ({isin}) gekappt/blockiert "
                                     f"(Sektor {sector_map.get(isin)} nahe/über {SEKTOR_SOFT_CAP*100:.0f}%).")
            continue  # zu wenig freies Kapital für eine sinnvolle Order
        units_to_buy = int((budget_for_this - fee_per_trade) / price)
        order_value = units_to_buy * price
        if units_to_buy > 0 and order_value >= MIN_ORDER_VALUE:
            begruendung = score_reason(isin)
            tx, total_cost = _make_buy_record(isin, stock, units_to_buy, price, ts, begruendung)
            state.current_cash -= total_cost
            state.positions.append({
                "isin": isin,
                "wertpapier": stock,
                "stueck": units_to_buy,
                "kaufkurs": price,
                "boersenkurs": price,
                "investiert": round(units_to_buy * price, 2),
                "boersenwert": round(units_to_buy * price, 2),
                "gewinn_verlust": 0.0,
                "score": ts,
                "dax_ref": round(dax_now, 2) if dax_now else None,
                "stop_ref_kurs": price,
                "beta": get_beta(isin)
            })
            state.transactions.append(tx)
            state.summary.append(f"Kauf: {units_to_buy}x {stock} ({isin}) zu {price:.2f} EUR, Score={ts}, Budget={budget:.0f}€ (Vola×{vol_mult}).")


# ==========================================
# AUSGABE
# ==========================================

def write_recommendation(state, portfolio_value):
    """Empfehlungs-Modus: nichts am Depot ändern, nur Vorschläge schreiben."""
    new_trades = state.transactions[state.initial_tx_count:]
    recommendation = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hinweis": ("Regelbasierter Vorschlag (Chart+Funda+KI-Sentiment, inkl. Veto). "
                    "Der Agent entscheidet autonom und kann abweichen."),
        "vorgeschlagene_trades": new_trades,
        "zusammenfassung": state.summary,
        "resultierender_barbestand": round(state.current_cash, 2),
        "resultierender_portfoliowert": round(portfolio_value, 2),
        "resultierendes_gesamtvermoegen": round(state.current_cash + portfolio_value, 2),
    }
    save_json(recommend_path, recommendation)
    print(f"[EMPFEHLUNGS-MODUS] {len(new_trades)} Trade-Vorschläge -> {recommend_path}")
    if state.summary:
        print("\n".join(state.summary))
    else:
        print("Vorschlag: keine Trades nötig, Zielportfolio erreicht.")


def write_depot(data, depot, state, portfolio_value):
    """Live-Modus: Ergebnis nach depot_status.json schreiben."""
    depot["aktueller_barbestand"] = round(state.current_cash, 2)
    depot["portfoliowert"] = round(portfolio_value, 2)
    depot["gesamtvermoegen"] = round(state.current_cash + portfolio_value, 2)
    depot["positionen"] = state.positions
    depot["transaktionshistorie"] = state.transactions
    data["depot"] = depot

    save_json(depot_path, data)

    if state.summary:
        print("\n".join(state.summary))
    else:
        print("Keine Transaktionen notwendig. Zielportfolio ist erreicht.")


# ==========================================
# ORCHESTRIERUNG
# ==========================================

def main(recommend=False):
    load_inputs()

    data = load_json(depot_path, {})
    depot = data.get("depot", {})
    positions = depot.get("positionen", [])
    transactions = depot.get("transaktionshistorie", [])
    state = RunState(
        current_cash=depot.get("aktueller_barbestand", 10000.0),
        positions=positions,
        transactions=transactions,
        initial_tx_count=len(transactions),  # neue Trades dieses Laufs = ab hier
    )

    phase_plan(state)
    phase_strategic_sell(state)
    phase_sector_reduction(state)
    phase_position_trim(state)
    unowned_targets, total_needed_cash = compute_capital_need(state)
    phase_rebalance(state, total_needed_cash)
    phase_buy(state, unowned_targets)

    portfolio_value = sum(p.get("boersenwert", 0) for p in state.positions)

    if recommend:
        write_recommendation(state, portfolio_value)
    else:
        write_depot(data, depot, state, portfolio_value)


if __name__ == "__main__":
    # Empfehlungs-Modus: berechnet Score/Sentiment/Veto und die Trades, die das
    # regelbasierte System vorschlagen WÜRDE, schreibt sie nach
    # data/trade_recommendations.json und lässt depot_status.json unangetastet.
    recommend = any(a in ("--recommend", "--dry-run") for a in sys.argv[1:])
    main(recommend=recommend)
