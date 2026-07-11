"""Zentrale Pfad- und I/O-Helfer für die Portfolio-Skripte.

Vorher: jedes Skript hat `base_dir = "/home/ubuntu/.openclaw/workspace/..."`
oder `os.path.join(BASE, "data", "...")` selbst gebaut, teils mit hardcodierten
Absolutpfaden, teils relativ zum Skript. Bei einem Umzug oder Rename der
Data-Files musste man 6 Stellen anfassen.

Neu: alle Pfade werden hier definiert. Andere Module importieren nur diese
Konstanten. BASE ist über das Skript-Verzeichnis aufgelöst — funktioniert
unabhängig davon, wo das Repo checked-out ist.
"""

from __future__ import annotations

import json
import os
from typing import Any

# BASE = das Repo-Wurzel-Verzeichnis (eine Ebene über src/).
BASE: str = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA_DIR: str = os.path.join(BASE, "data")
DOCS_DIR: str = os.path.join(BASE, "docs")

# JSON-Dateien im Datenverzeichnis (single source of truth).
CHART: str = os.path.join(DATA_DIR, "chartanalyse_ergebnisse.json")
FUNDA: str = os.path.join(DATA_DIR, "fundamentalanalyse_ergebnisse.json")
DEPOT: str = os.path.join(DATA_DIR, "depot_status.json")
SENT: str = os.path.join(DATA_DIR, "sentiment_scores.json")
NEWS: str = os.path.join(DATA_DIR, "news_raw.json")
TRADES: str = os.path.join(DATA_DIR, "trade_recommendations.json")
TRANS_HIST: str = os.path.join(DATA_DIR, "transaktionshistorie.json")
ETF_KATALOG: str = os.path.join(DATA_DIR, "etf_katalog.json")
ETF_NEWS: str = os.path.join(DATA_DIR, "etf_news_raw.json")
ETF_SENT: str = os.path.join(DATA_DIR, "etf_sentiment_scores.json")

# Backup-Dateien (werden von den Refresh-Skripten geschrieben, hier nur als
# Konstanten damit man den Namen an einer Stelle ändern kann).
FUNDA_BACKUP: str = os.path.join(DATA_DIR, "fundamentalanalyse_ergebnisse.backup.json")
FUNDA_OPP_BACKUP: str = os.path.join(DATA_DIR, "fundamentalanalyse_ergebnisse.opportunity_backup.json")
CHART_OPP_BACKUP: str = os.path.join(DATA_DIR, "chartanalyse_ergebnisse.opportunity_backup.json")

# Dashboard-Output.
INDEX_HTML: str = os.path.join(BASE, "index.html")


def load_json(path: str, default: Any = None) -> Any:
    """Robuster Load: bei fehlender Datei oder Parse-Fehler `default` zurück.

    Nur für Fälle geeignet, wo eine fehlende Datei ok ist (z.B. sentiment_scores
    beim ersten Lauf). Für Pflicht-Dateien den Fehler propagieren lassen.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: str, data: Any) -> None:
    """Konsistentes Schreib-Format für alle Datenfiles: indent=2, utf-8, kein ASCII-Escape."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
