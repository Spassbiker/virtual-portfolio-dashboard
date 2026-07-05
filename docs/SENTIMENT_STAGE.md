# KI-Sentiment-Stufe (Stufe 1 + 2)

Diese Stufe ergänzt das deterministische Scoring um eine **qualitative
LLM-Bewertung** aus aktuellen Nachrichten. Kernprinzip: Das LLM sitzt **nur auf
der qualitativen Seite** (Text → Stimmung). Die harte Mathematik (RSI, MACD,
Steuern, Ordergröße) bleibt zu 100 % deterministisch in Python.

## Pipeline-Reihenfolge

```
1. update_prices.py        Live-Kurse
2. compute_indicators.py   RSI/MACD/SMA (deterministisch)
3. (Fundamentalanalyse)    funda-Kennzahlen
4. fetch_news.py           Schlagzeilen  ->  data/news_raw.json     [Python, kein LLM]
5. AGENT-SCHRITT           news_raw.json ->  data/sentiment_scores.json  [LLM]
6. update_depot.py         liest sentiment_scores.json, handelt        [Python]
```

Schritt 5 ist der einzige LLM-Schritt. Fehlt `sentiment_scores.json`, läuft
`update_depot.py` unverändert rein deterministisch weiter (Rückwärtskompatibel).

## Datenvertrag `data/sentiment_scores.json`

```json
{
  "generated_at": "2026-07-05 09:40",
  "scores": {
    "<ISIN>": {
      "sentiment_score": 2,        // Ganzzahl -3..+3, wird in update_depot geklemmt
      "veto": false,               // true blockiert NUR Käufe, erzeugt nie welche
      "begruendung": "Kurztext, warum (1 Satz, konkret)."
    }
  }
}
```

### Wirkung im Scoring
- **Stufe 1:** `sentiment_score` wird als dritter Summand zu `chart + funda`
  addiert. `total_score = chart_score + funda_score + sentiment_score`.
- **Stufe 2:** `veto: true` entfernt die ISIN aus den Kaufkandidaten. Ein Veto
  kann eine Position **nicht** erzwingen und keinen Verkauf auslösen — es bremst
  nur Neukäufe. Bestehende Positionen bleiben unberührt (Verkauf entscheidet
  weiter der harte Score / das Verkaufen-Signal).

## Prompt für den Agent-Schritt (Schritt 5)

> Lies `data/news_raw.json`. Für **jede** ISIN darin: bewerte die Schlagzeilen
> als Nachrichtenstimmung der letzten Tage für genau dieses Unternehmen.
>
> Vergib einen `sentiment_score` von **−3 bis +3**:
> - **+3/+2**: klar positive, kursrelevante News (starke Zahlen, Großauftrag,
>   angehobener Ausblick).
> - **+1/0**: leicht positiv / neutral / nur generische Marktnews.
> - **−1/−2**: belastende News (schwache Zahlen, gesenkter Ausblick, Downgrade).
> - **−3**: schwerwiegend negativ (Gewinnwarnung, Skandal, Ermittlungen).
>
> Setze `veto: true` **nur** bei einem konkreten, akuten Grund, einen Kauf
> jetzt zu vermeiden (z. B. laufende Gewinnwarnung, Übernahme in Schwebe,
> Bilanzskandal). Im Zweifel `false`.
>
> Ignoriere Schlagzeilen, die offensichtlich ein anderes Unternehmen betreffen
> (Yahoo-Suche liefert gelegentlich generische Marktartikel — diese neutral mit
> 0 bewerten). Erfinde keine Fakten; bewerte nur, was in den Schlagzeilen steht.
>
> Schreibe das Ergebnis exakt im Vertragsformat nach
> `data/sentiment_scores.json`. Jede `begruendung` in einem knappen Satz.

## Warum kein API-Key im Python-Code?

Der Portfoliomanager läuft ohnehin als OpenClaw-Agent-Cron — das ist bereits
ein LLM. Der Agent erledigt Schritt 5 direkt, ohne separaten kostenpflichtigen
API-Zugang. Das hält die Kosten bei null und die Determinismus-Grenze sauber.
