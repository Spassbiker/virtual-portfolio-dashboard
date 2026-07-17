"""Sanity-Check für Chart-/Fundamentalanalyse-Daten.

Erkennt LLM-halluzinierte oder veraltete technische Indikatoren (z. B. Kurs
weit weg von SMA, Aufwärtstrend bei fallendem Kurs, negative Begründung bei
Kaufen-Signal). Diese Logik MUSS mit dataConsistency() in build_dashboard.py
synchron bleiben — sonst zeigt das Dashboard etwas anderes an, als die
Kauf-Engine (update_depot.py) tatsächlich verwendet.
"""

from __future__ import annotations

import re

# Diese Wörter deuten auf eine negative Einschätzung hin.
_NEG_PATTERNS = (
    "abwärts", "abwaerts", "sinkflug", "einbruch", "keine wende",
    "keine bodenbildung", "verlust", "abschwung", "bearish", "schwach",
)
# Wenn eines dieser Wörter im selben Satz steht, ist das negative Pattern
# retrospektiv/relativiert gemeint (z. B. "nach schwachem Vorjahr, jetzt
# Erholung") und zählt nicht als aktuelles Warnsignal.
_POSITIVE_CONTEXT = (
    "erholt", "erholung", "verbessert", "wende", "aufschwung",
    "attraktiv", "unterbewertet",
)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _has_real_negative_signal(text_f, text_c):
    """True nur bei einem echten, nicht relativierten negativen Satz."""
    for text in (text_f, text_c):
        if not text:
            continue
        for sentence in re.split(r"[.;]", text):
            s = sentence.lower()
            if not any(p in s for p in _NEG_PATTERNS):
                continue
            if "schwach" in s and "vorjahr" in s:
                continue  # rückblickend (Vorjahr), nicht der aktuelle Ausblick
            if any(pc in s for pc in _POSITIVE_CONTEXT):
                continue
            return True
    return False


def data_consistency(chart_item: dict | None, funda_item: dict | None) -> list[str]:
    """Gibt Liste von Warnstrings zurück; leer = Daten sehen konsistent aus."""
    c = chart_item or {}
    f = funda_item or {}
    warnings: list[str] = []

    price = _num(c.get("aktueller_kurs")) or _num(f.get("aktueller_kurs"))
    sma50 = _num(c.get("sma_50"))
    sma200 = _num(c.get("sma_200"))
    support = _num(c.get("unterstuetzung"))
    resistance = _num(c.get("widerstand"))
    trend = (c.get("trend") or "").lower()

    # 1. SMA50-Sanity: Kurs sollte innerhalb +/- 30% des SMA50 liegen.
    if price is not None and sma50 and sma50 > 0:
        dev = abs(price - sma50) / sma50
        if dev > 0.30:
            warnings.append(f"SMA50 {sma50} weit weg von Kurs {price} ({round(dev*100)}% Abweichung)")

    # 2. SMA200-Sanity: Schwelle wird bei klar durch SMA50 bestätigtem
    #    Aufwärtstrend (Kurs > SMA50 > SMA200) gelockert — das ist ein echter,
    #    starker Trend nach einer Rally, keine Datenanomalie.
    if price is not None and sma200 and sma200 > 0:
        aligned_uptrend = ("aufw" in trend and sma50 and sma50 > 0
                            and price > sma50 > sma200)
        threshold = 0.60 if aligned_uptrend else 0.30
        dev = abs(price - sma200) / sma200
        if dev > threshold:
            warnings.append(f"SMA200 {sma200} weit weg von Kurs {price} ({round(dev*100)}% Abweichung)")

    # 3. Support/Resistance-Sanity.
    if price is not None and support and support > 0 and price < support * 0.5:
        warnings.append(f"Kurs {price} weit unter Unterstützung {support}")
    if price is not None and resistance and resistance > 0 and price > resistance * 2:
        warnings.append(f"Kurs {price} weit über Widerstand {resistance}")

    # 4. Trend/Kurs-Konsistenz.
    if "aufw" in trend and price is not None and sma50 and sma50 > 0 and price < sma50 * 0.85:
        warnings.append('"Aufwärtstrend" behauptet, aber Kurs deutlich unter SMA50')
    if "abw" in trend and price is not None and sma50 and sma50 > 0 and price > sma50 * 1.15:
        warnings.append('"Abwärtstrend" behauptet, aber Kurs deutlich über SMA50')

    # 5. Text-Sentiment vs. Signal-Konflikt.
    # Achtung: "kauf" in signal matcht auch "Verkaufen" als Teilstring — daher
    # "verkauf" explizit ausschließen, sonst feuert das bei jedem Verkaufssignal.
    signal = (c.get("signal") or c.get("empfehlung") or f.get("empfehlung") or "").lower()
    is_buy_signal = "kauf" in signal and "verkauf" not in signal
    if _has_real_negative_signal(f.get("begruendung"), c.get("begruendung")) and is_buy_signal:
        warnings.append('Begründung klingt negativ, aber Signal "Kaufen"')

    return warnings
