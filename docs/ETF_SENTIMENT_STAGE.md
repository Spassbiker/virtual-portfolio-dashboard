# ETF-Sentiment-Stufe (Phase 1 + 2)

Ergänzt das Aktien-Sentiment (`SENTIMENT_STAGE.md`) um eine Sentiment-Bewertung
für den ETF-Sleeve. Unterschied zur Aktien-Logik: ein ETF hat keine eigenen
Schlagzeilen, also wird nicht pro Firma, sondern pro **Thema** (Typ A) oder
**Sektor** (Typ B) bewertet. Faktor-ETFs (Momentum/Quality/MinVol, Typ C)
haben keine sinnvolle News-Sentiment-Story und bleiben außen vor (siehe
`etf_theme_map.py`).

Aktuell **informativ** — der ETF-Sleeve ist Buy-and-Hold (siehe
`ETF_SLEEVE_VORSCHLAG.md`), es gibt keinen automatisierten Kauf/Verkauf auf
Basis dieses Scores. Score + Begründung erscheinen im Dashboard als Kontext.

## Pipeline

```
1. fetch_etf_news.py            Themen-/Sektor-Schlagzeilen -> data/etf_news_raw.json    [Python]
2. AGENT-SCHRITT                etf_news_raw.json -> data/etf_sentiment_scores.json      [LLM]
3. build_dashboard.py           zeigt Score+Begründung im ETF-Sleeve-Tab an              [Python]
```

Fehlt `etf_sentiment_scores.json`, zeigt das Dashboard einfach keine
Sentiment-Spalte — nichts bricht.

## Datenvertrag `data/etf_sentiment_scores.json`

```json
{
  "generated_at": "2026-07-11 08:55",
  "scores": {
    "<ISIN>": {
      "typ": "A",                  // "A" (Themen-ETF) oder "B" (Sektor-ETF)
      "sentiment_score": 2,        // Ganzzahl -3..+3
      "begruendung": "Kurztext, warum (1 Satz, konkret)."
    }
  }
}
```

Kein `veto`-Feld hier (anders als bei Aktien) — es gibt keine automatisierte
Kaufsperre im ETF-Sleeve, das Feld hätte keine Wirkung.

## Prompt für den Agent-Schritt

> Lies `data/etf_news_raw.json`. Für **jede** ISIN darin: bewerte die
> Schlagzeilen der letzten Tage als Themen-/Sektorstimmung für genau dieses
> Thema (Feld `thema`), nicht für eine einzelne Firma.
>
> Vergib einen `sentiment_score` von **−3 bis +3**:
> - **+3/+2**: klar positive, für das Thema/den Sektor relevante News
>   (Preisrally, politischer Rückenwind, starke Nachfragedaten).
> - **+1/0**: leicht positiv / neutral / nur generische Marktnews.
> - **−1/−2**: belastende News (Preisverfall, regulatorischer Gegenwind,
>   schwache Sektordaten).
> - **−3**: schwerwiegend negativ (Nachfrageeinbruch, Sektorkrise).
>
> Bei Typ B (breiter Sektor-ETF) zählt Makro-/Sektorlage stärker als
> Einzelmeldungen einer Firma. Ignoriere Schlagzeilen, die offensichtlich
> nichts mit dem Thema zu tun haben (score 0 bei fehlenden relevanten News).
> Erfinde keine Fakten; bewerte nur, was in den Schlagzeilen steht.
>
> Schreibe das Ergebnis EXAKT im Vertragsformat oben nach
> `data/etf_sentiment_scores.json` — überschreibe die Datei komplett.
> `generated_at` im Format `YYYY-MM-DD HH:MM`. Jede `begruendung` ein knapper Satz.
