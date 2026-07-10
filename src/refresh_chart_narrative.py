"""Regeneriere chart-Begründung, Trend und Signal aus den frischen Indikatoren.

Läuft im Daily-Cron NACH compute_indicators.py, damit die Textbegründung
(z.B. "Kurs 1013.20 vs. SMA50 1177.25 / SMA200 1542.32 → Abwärtstrend. RSI 39,
MACD Positiv.") immer zu den tatsächlich gespeicherten Zahlen passt. Ohne
diesen Schritt bleibt der Text vom LLM-Vorlauf stehen, während compute_indicators
darunter deterministische Werte schreibt — Ergebnis: sichtbare Widersprüche.

Empfehlungsfeld (`empfehlung`) wird NICHT angefasst — das ist das kombinierte
Chart+Funda-Rating und wird woanders vergeben. Position ohne verlässlichen
Kurs (aktueller_kurs None) bleibt unangetastet inkl. bestehendem Hinweistext.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import CHART as CHART_PATH, load_json, save_json


def classify_trend(kurs, sma50, sma200):
    if kurs > sma50 and kurs > sma200 and sma50 > sma200:
        return "Aufwärtstrend"
    if kurs < sma50 and kurs < sma200 and sma50 < sma200:
        return "Abwärtstrend"
    if kurs > sma50:
        return "Leichter Aufwärtstrend"
    return "Leichter Abwärtstrend"


def derive_signal(trend, rsi):
    if trend == "Aufwärtstrend":
        return "Halten" if rsi is not None and rsi > 70 else "Kaufen"
    if trend == "Abwärtstrend":
        return "Halten" if rsi is not None and rsi < 30 else "Verkaufen"
    return "Halten"


def render_narrative(kurs, sma50, sma200, trend, rsi, macd):
    rsi_txt = f"{round(rsi)}" if rsi is not None else "n/a"
    macd_txt = macd or "n/a"
    return (
        f"Kurs {kurs:.2f} vs. SMA50 {sma50:.2f} / SMA200 {sma200:.2f} "
        f"→ {trend}. RSI {rsi_txt}, MACD {macd_txt}."
    )


def refresh_item(item):
    kurs = item.get("aktueller_kurs")
    sma50 = item.get("sma_50")
    sma200 = item.get("sma_200")
    if kurs is None or sma50 is None or sma200 is None:
        return False
    # USD→EUR-konvertierte Werte werden vom Portfolio als "nicht handelbar" geführt;
    # der bestehende Hinweistext bleibt bewusst stehen, damit der Trade-Adapter
    # diese Positionen weiterhin überspringt.
    src = item.get("indicators_source") or ""
    if "USD" in src:
        return False
    rsi = item.get("rsi_14")
    macd = item.get("macd")
    trend = classify_trend(kurs, sma50, sma200)
    signal = derive_signal(trend, rsi)
    item["trend"] = trend
    item["signal"] = signal
    item["begruendung"] = render_narrative(kurs, sma50, sma200, trend, rsi, macd)
    item["datum"] = datetime.datetime.now().strftime("%Y-%m-%d")
    return True


def main():
    data = load_json(CHART_PATH, {})

    updated = 0
    skipped = 0
    for _, items in data.get("sektoren", {}).items():
        for item in items:
            if refresh_item(item):
                updated += 1
            else:
                skipped += 1

    save_json(CHART_PATH, data)

    print(f"Narrativ aktualisiert: {updated} Positionen, {skipped} übersprungen (keine Kurs-/SMA-Daten).")


if __name__ == "__main__":
    main()
