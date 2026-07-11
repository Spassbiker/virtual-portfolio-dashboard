import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import CHART, FUNDA, DEPOT, SENT, ETF_SENT, ETF_RANKING, INDEX_HTML


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


chart_data = _read_text(CHART)
funda_data = _read_text(FUNDA)
depot_data = _read_text(DEPOT)

# KI-Sentiment (optional): fehlt die Datei, wird ein leeres Objekt injiziert,
# damit das Dashboard ohne Sentiment-Stufe trotzdem funktioniert.
sentiment_data = _read_text(SENT) if os.path.exists(SENT) else '{"scores": {}}'

# ETF-Sentiment (Phase 1+2, optional): analog zum Aktien-Sentiment, fehlt die
# Datei zeigt das Dashboard einfach keine Sentiment-Spalte im ETF-Sleeve.
etf_sentiment_data = _read_text(ETF_SENT) if os.path.exists(ETF_SENT) else '{"scores": {}}'

# ETF-Ranking (Composite-Score über den gesamten Katalog, siehe etf_ranking.py):
# fehlt die Datei (z.B. vor dem ersten Lauf), zeigt der Tab einfach nichts an.
etf_ranking_data = _read_text(ETF_RANKING) if os.path.exists(ETF_RANKING) else '{"sektoren": {}}'

build_date = datetime.date.today().strftime("%d.%m.%Y")

html_template = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Virtual Portfolio Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 1500px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; text-align: center; margin-bottom: 30px; }
        h2, h3 { color: #34495e; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 0.9em; }
        th, td { padding: 10px 12px; border-bottom: 1px solid #ddd; text-align: left; }
        th { background-color: #34495e; color: white; position: sticky; top: 0; }
        th.sortable { cursor: pointer; user-select: none; }
        th.sortable:hover { background-color: #2c3e50; }
        th.sortable .arrow { opacity: 0.4; margin-left: 4px; }
        th.sortable.sorted .arrow { opacity: 1; }
        tr:hover { background-color: #f9f9f9; }
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; display: inline-block; text-align: center; min-width: 65px; }
        .buy { background-color: #d4edda; color: #155724; }
        .hold { background-color: #fff3cd; color: #856404; }
        .sell { background-color: #f8d7da; color: #721c24; }
        .risk-low { background-color: #d1ecf1; color: #0c5460; }
        .risk-mid { background-color: #fff3cd; color: #856404; }
        .risk-high { background-color: #f8d7da; color: #721c24; }
        .peer-good { color: #155724; font-weight: bold; }
        .peer-bad { color: #721c24; font-weight: bold; }
        .peer-neutral { color: #6c757d; }
        .tab-buttons { border-bottom: 2px solid #34495e; margin-bottom: 20px; }
        .tab-button { background-color: #ecf0f1; border: none; padding: 12px 25px; cursor: pointer; font-size: 16px; border-radius: 5px 5px 0 0; margin-right: 5px; font-weight: bold; color: #7f8c8d; transition: all 0.3s; }
        .tab-button:hover { background-color: #bdc3c7; }
        .tab-button.active { background-color: #34495e; color: white; }
        .tab-content { display: none; animation: fadeIn 0.5s; }
        .tab-content.active { display: block; overflow-x: auto; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: #f8f9fa; padding: 20px; border-radius: 8px; border: 1px solid #dee2e6; text-align: center; }
        .stat-card h4 { margin: 0 0 10px 0; color: #6c757d; font-size: 0.9em; text-transform: uppercase; }
        .stat-card p { margin: 0; font-size: 1.5em; font-weight: bold; color: #2c3e50; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

        /* --- Score & Filter Styling --- */
        .filter-bar { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px 20px; margin-bottom: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; align-items: end; }
        .filter-group { display: flex; flex-direction: column; }
        .filter-group label { font-size: 0.8em; font-weight: 600; color: #6c757d; text-transform: uppercase; margin-bottom: 4px; }
        .filter-group select, .filter-group input { padding: 6px 10px; border: 1px solid #ced4da; border-radius: 4px; font-size: 0.95em; background: white; }
        .filter-reset { background: #6c757d; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 0.9em; font-weight: 600; }
        .filter-reset:hover { background: #495057; }
        .filter-count { font-size: 0.85em; color: #6c757d; font-style: italic; margin-bottom: 10px; }

        .score-cell { font-weight: bold; color: white; padding: 6px 10px; border-radius: 4px; text-align: center; min-width: 45px; display: inline-block; }
        .score-a { background: #1e7e34; }  /* >= 80 */
        .score-b { background: #28a745; }  /* 65-80 */
        .score-c { background: #ffc107; color: #333; }  /* 50-65 */
        .score-d { background: #fd7e14; }  /* 35-50 */
        .score-e { background: #dc3545; }  /* < 35 */

        .subscore { font-size: 0.85em; color: #495057; }
        .subscore-bar { display: inline-block; width: 40px; height: 6px; background: #e9ecef; border-radius: 3px; overflow: hidden; vertical-align: middle; margin-right: 4px; }
        .subscore-bar-fill { height: 100%; background: #28a745; }
        .subscore-bar-fill.low { background: #dc3545; }
        .subscore-bar-fill.mid { background: #ffc107; }

        .perfect-setup { background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.75em; font-weight: bold; margin-left: 6px; }
        .in-depot { background: #17a2b8; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.75em; margin-left: 6px; }
        .data-warning { background: #f8d7da; color: #721c24; padding: 3px 8px; border-radius: 12px; font-size: 0.75em; font-weight: bold; margin-left: 6px; cursor: help; border: 1px solid #f5c6cb; }
        tr.inconsistent-row { background: #fdf5f5; }
        tr.inconsistent-row:hover { background: #fbecec; }

        .weights-info { background: #e7f3ff; border-left: 4px solid #0066cc; padding: 10px 15px; margin-bottom: 20px; border-radius: 4px; font-size: 0.9em; color: #004085; }
        .weights-info strong { color: #002752; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Virtual Portfolio Dashboard <br><small style="font-size: 0.5em; color: #7f8c8d;">Build: BUILD_DATE_PLACEHOLDER</small></h1>

        <div class="tab-buttons">
            <button class="tab-button active" onclick="openTab(event, 'ranking')">🎯 Empfehlungen</button>
            <button class="tab-button" onclick="openTab(event, 'depot')">Depot Status</button>
            <button class="tab-button" onclick="openTab(event, 'etfsleeve')">📊 ETF-Sleeve</button>
            <button class="tab-button" onclick="openTab(event, 'etfranking')">🌐 ETF-Empfehlungen</button>
            <button class="tab-button" onclick="openTab(event, 'chart')">Chartanalyse</button>
            <button class="tab-button" onclick="openTab(event, 'funda')">Fundamentalanalyse</button>
            <button class="tab-button" onclick="openTab(event, 'sentiment')">🤖 KI-Sentiment</button>
            <button class="tab-button" onclick="openTab(event, 'transaktionen')">Transaktionshistorie</button>
        </div>

        <div id="ranking" class="tab-content active"></div>
        <div id="depot" class="tab-content"></div>
        <div id="etfsleeve" class="tab-content"></div>
        <div id="etfranking" class="tab-content"></div>
        <div id="chart" class="tab-content"></div>
        <div id="funda" class="tab-content"></div>
        <div id="sentiment" class="tab-content"></div>
        <div id="transaktionen" class="tab-content"></div>
    </div>

    <script>
        const chartData = CHART_DATA_PLACEHOLDER;
        const fundaData = FUNDA_DATA_PLACEHOLDER;
        const depotData = DEPOT_DATA_PLACEHOLDER;
        const sentimentData = SENTIMENT_DATA_PLACEHOLDER;
        const sentimentScores = (sentimentData && sentimentData.scores) ? sentimentData.scores : {};
        const etfSentimentData = ETF_SENTIMENT_DATA_PLACEHOLDER;
        const etfRankingData = ETF_RANKING_DATA_PLACEHOLDER;
        const etfSentimentScores = (etfSentimentData && etfSentimentData.scores) ? etfSentimentData.scores : {};

        function getSentiment(isin) {
            return (isin && sentimentScores[isin]) ? sentimentScores[isin] : null;
        }
        // Kompaktes Sentiment-Badge (Pfeil + Wert) + optionales Veto, mit Begründung als Tooltip.
        function sentimentBadge(isin) {
            const s = getSentiment(isin);
            if (!s) return '<span style="color:#adb5bd;">–</span>';
            const val = (typeof s.sentiment_score === 'number') ? s.sentiment_score : 0;
            const tip = (s.begruendung || '').replace(/"/g, '&quot;');
            let color = '#6c757d', arrow = '→';
            if (val > 0) { color = '#155724'; arrow = '▲'; }
            else if (val < 0) { color = '#721c24'; arrow = '▼'; }
            const sign = val > 0 ? '+' : '';
            let html = `<span title="${tip}" style="font-weight:bold;color:${color};">${arrow} ${sign}${val}</span>`;
            if (s.veto) html += ` <span class="badge sell" title="${tip}" style="min-width:auto;">🚫 Veto</span>`;
            return html;
        }

        // ETF-Sentiment-Badge (Themen-/Sektor-Score, kein Veto - der ETF-Sleeve
        // ist Buy-and-Hold, siehe docs/ETF_SENTIMENT_STAGE.md).
        function etfSentimentBadge(isin) {
            const s = isin ? etfSentimentScores[isin] : null;
            if (!s) return '<span style="color:#adb5bd;">–</span>';
            const val = (typeof s.sentiment_score === 'number') ? s.sentiment_score : 0;
            const tip = (s.begruendung || '').replace(/"/g, '&quot;');
            let color = '#6c757d', arrow = '→';
            if (val > 0) { color = '#155724'; arrow = '▲'; }
            else if (val < 0) { color = '#721c24'; arrow = '▼'; }
            const sign = val > 0 ? '+' : '';
            const typTag = s.typ ? `<span style="color:#adb5bd; font-size:0.8em;"> (${s.typ})</span>` : '';
            return `<span title="${tip}" style="font-weight:bold;color:${color};">${arrow} ${sign}${val}</span>${typTag}`;
        }

        function getBadge(rating) {
            if (!rating) return '';
            const r = rating.toLowerCase();
            if (r.includes("kauf") || r.includes("attraktiv")) return `<span class="badge buy">${rating}</span>`;
            if (r.includes("halt") || r.includes("fair")) return `<span class="badge hold">${rating}</span>`;
            if (r.includes("verkauf") || r.includes("teuer")) return `<span class="badge sell">${rating}</span>`;
            return `<span class="badge" style="background:#e2e3e5; color:#333;">${rating}</span>`;
        }

        function getRiskBadge(risk) {
            if (!risk) return '-';
            const r = risk.toLowerCase();
            if (r.includes("niedrig")) return `<span class="badge risk-low">${risk}</span>`;
            if (r.includes("mittel")) return `<span class="badge risk-mid">${risk}</span>`;
            if (r.includes("hoch")) return `<span class="badge risk-high">${risk}</span>`;
            return risk;
        }

        function formatEUR(val) {
            if (val === undefined || val === null || val === '') return '-';
            return Number(val).toLocaleString('de-DE', {style: 'currency', currency: 'EUR'});
        }

        function formatEURSign(val) {
            if (val === undefined || val === null || val === '') return '-';
            let num = Number(val);
            try {
                return num.toLocaleString('de-DE', {style: 'currency', currency: 'EUR', signDisplay: 'always'});
            } catch (e) {
                let formatted = num.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'});
                return num > 0 ? '+' + formatted : formatted;
            }
        }

        // ==========================================
        // COMPOSITE SCORING SYSTEM
        // ==========================================
        // Weights: Fundamental 40 %, Chart 30 %, Risiko 15 %, Perfect-Setup-Bonus 15 %
        // ==========================================

        const WEIGHTS = { fundamental: 0.40, chart: 0.30, risiko: 0.15, perfect: 0.15 };

        function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
        function linMap(v, xLo, xHi, yLo, yHi) {
            if (v === null || v === undefined || isNaN(v)) return null;
            const t = (v - xLo) / (xHi - xLo);
            return clamp(yLo + t * (yHi - yLo), Math.min(yLo, yHi), Math.max(yLo, yHi));
        }
        function numOrNull(v) {
            if (v === null || v === undefined || v === '') return null;
            const n = Number(v);
            return isNaN(n) ? null : n;
        }

        function fundamentalScore(f) {
            if (!f) return { score: null, parts: {} };
            const parts = {};

            // Bewertung: Attraktiv=100, Fair=55, Teuer=20
            const b = (f.bewertung || '').toLowerCase();
            if (b.includes('attraktiv')) parts.bewertung = 100;
            else if (b.includes('fair')) parts.bewertung = 55;
            else if (b.includes('teuer')) parts.bewertung = 20;

            // KGV: <=12 -> 100, 12-25 -> 80..50, 25-40 -> 50..20, >40 -> 15
            const kgv = numOrNull(f.kgv);
            if (kgv !== null && kgv > 0) {
                if (kgv <= 12) parts.kgv = 100;
                else if (kgv <= 25) parts.kgv = linMap(kgv, 12, 25, 100, 55);
                else if (kgv <= 40) parts.kgv = linMap(kgv, 25, 40, 55, 25);
                else parts.kgv = 15;
            }

            // Dividendenrendite: 0->0, 2%->50, 4%->85, >=5% -> 100
            const div = numOrNull(f.dividendenrendite);
            if (div !== null) {
                if (div <= 0) parts.dividende = 0;
                else if (div <= 2) parts.dividende = linMap(div, 0, 2, 0, 50);
                else if (div <= 4) parts.dividende = linMap(div, 2, 4, 50, 85);
                else parts.dividende = clamp(linMap(div, 4, 6, 85, 100), 0, 100);
            }

            // Umsatzwachstum: >=25% -> 100, 0% -> 45, <=-10% -> 5
            const uw = numOrNull(f.umsatzwachstum_yoy);
            if (uw !== null) {
                if (uw >= 25) parts.umsatzwachstum = 100;
                else if (uw >= 0) parts.umsatzwachstum = linMap(uw, 0, 25, 45, 100);
                else parts.umsatzwachstum = clamp(linMap(uw, -10, 0, 5, 45), 0, 100);
            }

            // Gewinnwachstum: analog
            const gw = numOrNull(f.gewinnwachstum_yoy);
            if (gw !== null) {
                if (gw >= 25) parts.gewinnwachstum = 100;
                else if (gw >= 0) parts.gewinnwachstum = linMap(gw, 0, 25, 45, 100);
                else parts.gewinnwachstum = clamp(linMap(gw, -20, 0, 5, 45), 0, 100);
            }

            // Eigenkapitalquote: >=50% -> 100, 30% -> 65, <=15% -> 25
            const ek = numOrNull(f.eigenkapitalquote);
            if (ek !== null) {
                if (ek >= 50) parts.ek = 100;
                else if (ek >= 30) parts.ek = linMap(ek, 30, 50, 65, 100);
                else parts.ek = clamp(linMap(ek, 15, 30, 25, 65), 0, 100);
            }

            const vals = Object.values(parts).filter(v => v !== null && v !== undefined);
            const score = vals.length ? vals.reduce((a,b) => a+b, 0) / vals.length : null;
            return { score, parts };
        }

        function chartScore(c) {
            if (!c) return { score: null, parts: {} };
            const parts = {};

            const sig = (c.signal || c.empfehlung || '').toLowerCase();
            if (sig.includes('kauf')) parts.signal = 100;
            else if (sig.includes('halt')) parts.signal = 50;
            else if (sig.includes('verkauf')) parts.signal = 10;

            const trend = (c.trend || '').toLowerCase();
            if (trend.includes('aufw')) parts.trend = 90;
            else if (trend.includes('seit')) parts.trend = 50;
            else if (trend.includes('abw')) parts.trend = 20;

            // RSI sweet spot 40-55 = 100, 30-40 = 80, 55-70 = 60, <30 oversold = 40, >70 overbought = 20
            const rsi = numOrNull(c.rsi_14);
            if (rsi !== null) {
                if (rsi >= 40 && rsi <= 55) parts.rsi = 100;
                else if (rsi >= 30 && rsi < 40) parts.rsi = linMap(rsi, 30, 40, 70, 100);
                else if (rsi > 55 && rsi <= 70) parts.rsi = linMap(rsi, 55, 70, 90, 55);
                else if (rsi < 30) parts.rsi = 40;
                else parts.rsi = clamp(linMap(rsi, 70, 90, 55, 15), 0, 100);
            }

            const macd = (c.macd || '').toLowerCase();
            if (macd.includes('positiv')) parts.macd = 90;
            else if (macd.includes('neutral')) parts.macd = 50;
            else if (macd.includes('negativ')) parts.macd = 20;

            const vals = Object.values(parts).filter(v => v !== null && v !== undefined);
            const score = vals.length ? vals.reduce((a,b) => a+b, 0) / vals.length : null;
            return { score, parts };
        }

        function riskScore(risk) {
            const r = (risk || '').toLowerCase();
            if (r.includes('niedrig')) return 100;
            if (r.includes('mittel')) return 60;
            if (r.includes('hoch')) return 25;
            return null;
        }

        // Detects LLM-halluzinated or stale technical indicators.
        // Returns list of warning strings; empty list means data looks consistent.
        function dataConsistency(f, c) {
            const warnings = [];
            const price = numOrNull((c && c.aktueller_kurs) || (f && f.aktueller_kurs));
            const sma50 = numOrNull(c && c.sma_50);
            const sma200 = numOrNull(c && c.sma_200);
            const support = numOrNull(c && c.unterstuetzung);
            const resistance = numOrNull(c && c.widerstand);

            // 1. SMA sanity: price should be within +/- 30% of SMAs.
            if (price !== null && sma50 !== null && sma50 > 0) {
                const dev = Math.abs(price - sma50) / sma50;
                if (dev > 0.30) warnings.push(`SMA50 ${sma50} weit weg von Kurs ${price} (${Math.round(dev*100)}% Abweichung)`);
            }
            if (price !== null && sma200 !== null && sma200 > 0) {
                const dev = Math.abs(price - sma200) / sma200;
                if (dev > 0.30) warnings.push(`SMA200 ${sma200} weit weg von Kurs ${price} (${Math.round(dev*100)}% Abweichung)`);
            }
            // 2. Support/Resistance sanity: price should be between (loose bracket allowed).
            if (price !== null && support !== null && support > 0 && price < support * 0.5) {
                warnings.push(`Kurs ${price} weit unter Unterstützung ${support}`);
            }
            if (price !== null && resistance !== null && resistance > 0 && price > resistance * 2) {
                warnings.push(`Kurs ${price} weit über Widerstand ${resistance}`);
            }
            // 3. Trend/Kurs-Konsistenz: Aufwärtstrend behauptet, aber Kurs unter SMA_50.
            const trend = (c && c.trend || '').toLowerCase();
            if (trend.includes('aufw') && price !== null && sma50 !== null && sma50 > 0 && price < sma50 * 0.85) {
                warnings.push(`"Aufwärtstrend" behauptet, aber Kurs deutlich unter SMA50`);
            }
            if (trend.includes('abw') && price !== null && sma50 !== null && sma50 > 0 && price > sma50 * 1.15) {
                warnings.push(`"Abwärtstrend" behauptet, aber Kurs deutlich über SMA50`);
            }
            // 4. Text-Sentiment vs. Signal-Konflikt: Begründung negativ, aber Signal Kaufen.
            const bruendungF = ((f && f.begruendung) || '').toLowerCase();
            const bruendungC = ((c && c.begruendung) || '').toLowerCase();
            const signal = ((c && (c.signal || c.empfehlung)) || (f && f.empfehlung) || '').toLowerCase();
            const negPatterns = ['abwärts', 'abwaerts', 'sinkflug', 'einbruch', 'keine wende', 'keine bodenbildung', 'verlust', 'abschwung', 'bearish', 'schwach'];
            const hasNeg = negPatterns.some(p => bruendungF.includes(p) || bruendungC.includes(p));
            if (hasNeg && signal.includes('kauf')) {
                warnings.push(`Begründung klingt negativ, aber Signal "Kaufen"`);
            }
            return warnings;
        }

        function perfectSetupScore(f, c) {
            // Perfect if: Bewertung=Attraktiv AND Signal=Kaufen AND RSI in [30, 55] AND Trend Aufwärts
            let s = 0, n = 0;
            const bewert = (f && f.bewertung || '').toLowerCase();
            const signal = (c && (c.signal || c.empfehlung) || '').toLowerCase();
            const rsi = numOrNull(c && c.rsi_14);
            const trend = (c && c.trend || '').toLowerCase();

            if (bewert) { n++; if (bewert.includes('attraktiv')) s += 25; }
            if (signal) { n++; if (signal.includes('kauf')) s += 25; }
            if (rsi !== null) { n++; if (rsi >= 30 && rsi <= 55) s += 25; }
            if (trend) { n++; if (trend.includes('aufw')) s += 25; }
            return n > 0 ? (s / n) * 4 : null;   // scale to 0-100
        }

        function isPerfectSetup(f, c) {
            if (dataConsistency(f, c).length > 0) return false;
            const bewert = (f && f.bewertung || '').toLowerCase();
            const signal = (c && (c.signal || c.empfehlung) || '').toLowerCase();
            const rsi = numOrNull(c && c.rsi_14);
            const trend = (c && c.trend || '').toLowerCase();
            return bewert.includes('attraktiv') && signal.includes('kauf')
                && rsi !== null && rsi >= 30 && rsi <= 55
                && trend.includes('aufw');
        }

        function compositeScore(f, c) {
            const fs = fundamentalScore(f);
            const cs = chartScore(c);
            const rs = riskScore(f && f.risiko);
            let ps = perfectSetupScore(f, c);

            const warnings = dataConsistency(f, c);
            const inconsistent = warnings.length > 0;

            // If chart data is inconsistent, penalize its trust: halve chart score, kill Perfect Setup.
            let chartAdj = cs.score;
            if (inconsistent && chartAdj !== null) chartAdj = chartAdj * 0.5;
            if (inconsistent) ps = 0;

            let totalW = 0, sum = 0;
            if (fs.score !== null)  { sum += WEIGHTS.fundamental * fs.score; totalW += WEIGHTS.fundamental; }
            if (chartAdj !== null)  { sum += WEIGHTS.chart * chartAdj;       totalW += WEIGHTS.chart; }
            if (rs !== null)        { sum += WEIGHTS.risiko * rs;            totalW += WEIGHTS.risiko; }
            if (ps !== null)        { sum += WEIGHTS.perfect * ps;           totalW += WEIGHTS.perfect; }

            const score = totalW > 0 ? sum / totalW : null;
            return { composite: score, fund: fs.score, chart: chartAdj, chartRaw: cs.score, risiko: rs, perfect: ps, fundParts: fs.parts, chartParts: cs.parts, warnings, inconsistent };
        }

        function scoreClass(s) {
            if (s === null || s === undefined) return '';
            if (s >= 80) return 'score-a';
            if (s >= 65) return 'score-b';
            if (s >= 50) return 'score-c';
            if (s >= 35) return 'score-d';
            return 'score-e';
        }

        function scoreCell(s) {
            if (s === null || s === undefined) return '<span style="color:#999">–</span>';
            return `<span class="score-cell ${scoreClass(s)}">${Math.round(s)}</span>`;
        }

        function subscoreBar(s) {
            if (s === null || s === undefined) return '<span style="color:#999">–</span>';
            const cls = s >= 65 ? '' : (s >= 40 ? 'mid' : 'low');
            return `<span class="subscore-bar"><span class="subscore-bar-fill ${cls}" style="width:${Math.round(s)}%"></span></span><span class="subscore">${Math.round(s)}</span>`;
        }

        // ==========================================
        // PEER-COMPARISON (sector medians)
        // ==========================================
        function median(arr) {
            const a = arr.filter(v => v !== null && v !== undefined && !isNaN(v)).sort((x,y) => x - y);
            if (!a.length) return null;
            const m = Math.floor(a.length / 2);
            return a.length % 2 ? a[m] : (a[m-1] + a[m]) / 2;
        }

        const sectorMedians = {};
        if (fundaData.sektoren) {
            Object.keys(fundaData.sektoren).forEach(sektor => {
                const werte = fundaData.sektoren[sektor];
                sectorMedians[sektor] = {
                    kgv: median(werte.map(w => numOrNull(w.kgv))),
                    dividende: median(werte.map(w => numOrNull(w.dividendenrendite))),
                    umsatz: median(werte.map(w => numOrNull(w.umsatzwachstum_yoy))),
                    gewinn: median(werte.map(w => numOrNull(w.gewinnwachstum_yoy)))
                };
            });
        }

        function peerLabel(val, med, invert) {
            // invert=true → lower is better (KGV). false → higher is better (Dividende, Wachstum)
            if (val === null || val === undefined || med === null || med === undefined) return '';
            const delta = ((val - med) / Math.abs(med || 1)) * 100;
            const better = invert ? val < med : val > med;
            const diff = Math.abs(delta).toFixed(0);
            if (Math.abs(delta) < 5) return `<span class="peer-neutral" title="≈ Sektor-Ø">≈</span>`;
            return better
                ? `<span class="peer-good" title="besser als Sektor-Ø (${med.toFixed(1)})">▲${diff}%</span>`
                : `<span class="peer-bad" title="schlechter als Sektor-Ø (${med.toFixed(1)})">▼${diff}%</span>`;
        }

        // ==========================================
        // BUILD FLAT LIST FOR RANKING
        // ==========================================
        const depotIsins = new Set((depotData.depot.positionen || []).map(p => p.isin));

        function buildFlatList() {
            const chartByIsin = {};
            const chartByName = {};
            if (chartData.sektoren) {
                Object.values(chartData.sektoren).forEach(list => list.forEach(w => {
                    if (w.isin) chartByIsin[w.isin] = w;
                    if (w.wertpapier) chartByName[w.wertpapier] = w;
                }));
            }
            const rows = [];
            if (fundaData.sektoren) {
                Object.keys(fundaData.sektoren).forEach(sektor => {
                    fundaData.sektoren[sektor].forEach(f => {
                        const c = (f.isin && chartByIsin[f.isin]) || chartByName[f.wertpapier] || null;
                        const scores = compositeScore(f, c);
                        rows.push({
                            wertpapier: f.wertpapier,
                            isin: f.isin || '',
                            sektor,
                            f, c,
                            scores,
                            inDepot: f.isin && depotIsins.has(f.isin),
                            perfect: isPerfectSetup(f, c)
                        });
                    });
                });
            }
            return rows;
        }

        const allRows = buildFlatList();

        // ==========================================
        // RANKING TAB (with filters, sort)
        // ==========================================
        const sectors = ['Alle', ...new Set(allRows.map(r => r.sektor))];
        const riskLevels = ['Alle', 'Niedrig', 'Mittel', 'Hoch'];

        let uiState = {
            sort: 'composite',
            dir: 'desc',
            sektor: 'Alle',
            risiko: 'Alle',
            minScore: 0,
            onlyPerfect: false,
            excludeDepot: false,
            onlyKaufen: false,
            hideInconsistent: false
        };

        function renderRankingTab() {
            const sectorOpts = sectors.map(s => `<option value="${s}"${uiState.sektor===s?' selected':''}>${s}</option>`).join('');
            const riskOpts = riskLevels.map(r => `<option value="${r}"${uiState.risiko===r?' selected':''}>${r}</option>`).join('');

            const header = `
                <h2>🎯 Empfehlungs-Ranking</h2>
                <div class="weights-info">
                    <strong>Composite-Score</strong> — Gewichtung: Fundamental 40 % · Chart 30 % · Risiko 15 % · Perfect-Setup-Bonus 15 %.
                    Perfect Setup: Bewertung <em>Attraktiv</em> + Signal <em>Kaufen</em> + RSI 30–55 + Trend <em>Aufwärts</em>.
                    <br>
                    <strong>⚠️ Daten prüfen</strong> — Sanity-Check erkennt inkonsistente Analyse-Daten (z. B. Kurs weit weg von SMA, Aufwärtstrend bei fallendem Kurs, negative Begründung bei Kaufen-Signal). Bei Warnung wird Chart-Score halbiert und Perfect Setup entfernt.
                </div>
                <div class="filter-bar">
                    <div class="filter-group">
                        <label>Sektor</label>
                        <select id="f-sektor">${sectorOpts}</select>
                    </div>
                    <div class="filter-group">
                        <label>Risiko</label>
                        <select id="f-risiko">${riskOpts}</select>
                    </div>
                    <div class="filter-group">
                        <label>Min. Score: <span id="f-minScore-val">${uiState.minScore}</span></label>
                        <input type="range" id="f-minScore" min="0" max="100" step="5" value="${uiState.minScore}">
                    </div>
                    <div class="filter-group">
                        <label><input type="checkbox" id="f-perfect"${uiState.onlyPerfect?' checked':''}> nur Perfect Setup</label>
                        <label><input type="checkbox" id="f-kaufen"${uiState.onlyKaufen?' checked':''}> nur "Kaufen"-Signal</label>
                    </div>
                    <div class="filter-group">
                        <label><input type="checkbox" id="f-nodepot"${uiState.excludeDepot?' checked':''}> nicht im Depot</label>
                        <label><input type="checkbox" id="f-noinconsistent"${uiState.hideInconsistent?' checked':''}> ⚠️ Inkonsistente verstecken</label>
                        <button class="filter-reset" id="f-reset">Filter zurücksetzen</button>
                    </div>
                </div>
                <div class="filter-count" id="f-count"></div>
            `;

            const cols = [
                { key: 'wertpapier', label: 'Wertpapier', sortable: true },
                { key: 'sektor', label: 'Sektor', sortable: true },
                { key: 'composite', label: 'Score', sortable: true },
                { key: 'fund', label: 'Fundamental', sortable: true },
                { key: 'chart', label: 'Chart', sortable: true },
                { key: 'risiko', label: 'Risiko', sortable: true },
                { key: 'kurs', label: 'Kurs', sortable: true },
                { key: 'kgv', label: 'KGV', sortable: true },
                { key: 'dividende', label: 'Div. %', sortable: true },
                { key: 'rsi', label: 'RSI', sortable: true },
                { key: 'signal', label: 'Signal', sortable: false },
                { key: 'begruendung', label: 'Begründung', sortable: false }
            ];

            const thHtml = cols.map(c => {
                const active = c.sortable && uiState.sort === c.key;
                const arrow = active ? (uiState.dir === 'asc' ? '▲' : '▼') : '↕';
                return c.sortable
                    ? `<th class="sortable${active?' sorted':''}" data-sort="${c.key}">${c.label}<span class="arrow">${arrow}</span></th>`
                    : `<th>${c.label}</th>`;
            }).join('');

            document.getElementById('ranking').innerHTML = header + `<table id="ranking-table"><thead><tr>${thHtml}</tr></thead><tbody id="ranking-body"></tbody></table>`;

            // Bind events
            document.getElementById('f-sektor').addEventListener('change', e => { uiState.sektor = e.target.value; refreshRankingBody(); });
            document.getElementById('f-risiko').addEventListener('change', e => { uiState.risiko = e.target.value; refreshRankingBody(); });
            document.getElementById('f-minScore').addEventListener('input', e => {
                uiState.minScore = Number(e.target.value);
                document.getElementById('f-minScore-val').textContent = uiState.minScore;
                refreshRankingBody();
            });
            document.getElementById('f-perfect').addEventListener('change', e => { uiState.onlyPerfect = e.target.checked; refreshRankingBody(); });
            document.getElementById('f-kaufen').addEventListener('change', e => { uiState.onlyKaufen = e.target.checked; refreshRankingBody(); });
            document.getElementById('f-nodepot').addEventListener('change', e => { uiState.excludeDepot = e.target.checked; refreshRankingBody(); });
            document.getElementById('f-noinconsistent').addEventListener('change', e => { uiState.hideInconsistent = e.target.checked; refreshRankingBody(); });
            document.getElementById('f-reset').addEventListener('click', () => {
                uiState = { sort: 'composite', dir: 'desc', sektor: 'Alle', risiko: 'Alle', minScore: 0, onlyPerfect: false, excludeDepot: false, onlyKaufen: false, hideInconsistent: false };
                renderRankingTab();
            });
            document.querySelectorAll('#ranking-table th.sortable').forEach(th => {
                th.addEventListener('click', () => {
                    const k = th.dataset.sort;
                    if (uiState.sort === k) uiState.dir = uiState.dir === 'asc' ? 'desc' : 'asc';
                    else { uiState.sort = k; uiState.dir = (k === 'wertpapier' || k === 'sektor') ? 'asc' : 'desc'; }
                    renderRankingTab();
                });
            });

            refreshRankingBody();
        }

        function refreshRankingBody() {
            let rows = allRows.slice();
            if (uiState.sektor !== 'Alle') rows = rows.filter(r => r.sektor === uiState.sektor);
            if (uiState.risiko !== 'Alle') rows = rows.filter(r => (r.f.risiko || '').toLowerCase().includes(uiState.risiko.toLowerCase()));
            if (uiState.minScore > 0) rows = rows.filter(r => (r.scores.composite || 0) >= uiState.minScore);
            if (uiState.onlyPerfect) rows = rows.filter(r => r.perfect);
            if (uiState.excludeDepot) rows = rows.filter(r => !r.inDepot);
            if (uiState.onlyKaufen) rows = rows.filter(r => {
                const sig = ((r.c && (r.c.signal || r.c.empfehlung)) || '').toLowerCase();
                return sig.includes('kauf');
            });
            if (uiState.hideInconsistent) rows = rows.filter(r => !(r.scores.warnings && r.scores.warnings.length));

            // sort
            const sortKey = uiState.sort;
            const getVal = r => {
                switch (sortKey) {
                    case 'wertpapier': return r.wertpapier || '';
                    case 'sektor': return r.sektor || '';
                    case 'composite': return r.scores.composite;
                    case 'fund': return r.scores.fund;
                    case 'chart': return r.scores.chart;
                    case 'risiko': return r.scores.risiko;
                    case 'kurs': return numOrNull((r.c && r.c.aktueller_kurs) || r.f.aktueller_kurs);
                    case 'kgv': return numOrNull(r.f.kgv);
                    case 'dividende': return numOrNull(r.f.dividendenrendite);
                    case 'rsi': return numOrNull(r.c && r.c.rsi_14);
                    default: return 0;
                }
            };
            rows.sort((a,b) => {
                const av = getVal(a), bv = getVal(b);
                if (av === null || av === undefined) return 1;
                if (bv === null || bv === undefined) return -1;
                if (typeof av === 'string') return uiState.dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
                return uiState.dir === 'asc' ? av - bv : bv - av;
            });

            const body = rows.map(r => {
                const kurs = (r.c && r.c.aktueller_kurs) || r.f.aktueller_kurs;
                const warnings = (r.scores.warnings || []);
                const warnBadge = warnings.length
                    ? `<span class="data-warning" title="${warnings.join(' | ').replace(/"/g,'&quot;')}">⚠️ Daten prüfen</span>`
                    : '';
                const badges = warnBadge
                             + (r.perfect ? '<span class="perfect-setup" title="Fundamental Attraktiv + Signal Kaufen + RSI 30–55 + Aufwärtstrend">⭐ Perfect</span>' : '')
                             + (r.inDepot ? '<span class="in-depot" title="bereits im Depot">Im Depot</span>' : '');
                const signal = (r.c && (r.c.signal || r.c.empfehlung)) || '-';
                const begruendung = ((r.f && r.f.begruendung) || '') + ((r.c && r.c.begruendung) ? ' · ' + r.c.begruendung : '');
                const rowCls = warnings.length ? ' class="inconsistent-row"' : '';
                return `<tr${rowCls}>
                    <td><strong>${r.wertpapier}</strong>${badges}<br><small style="color:#666">${r.isin}</small></td>
                    <td>${r.sektor}</td>
                    <td>${scoreCell(r.scores.composite)}</td>
                    <td>${subscoreBar(r.scores.fund)}</td>
                    <td>${subscoreBar(r.scores.chart)}</td>
                    <td>${getRiskBadge(r.f.risiko)}</td>
                    <td>${formatEUR(kurs)}</td>
                    <td>${r.f.kgv !== undefined ? r.f.kgv : '-'}</td>
                    <td>${r.f.dividendenrendite !== undefined ? r.f.dividendenrendite + '%' : '-'}</td>
                    <td>${r.c && r.c.rsi_14 !== undefined ? r.c.rsi_14 : '-'}</td>
                    <td>${getBadge(signal)}</td>
                    <td style="font-size:0.85em; max-width:280px;">${begruendung || '-'}</td>
                </tr>`;
            }).join('');

            document.getElementById('ranking-body').innerHTML = body || '<tr><td colspan="12" style="text-align:center; padding:30px; color:#6c757d;">Keine Titel passen zu den aktuellen Filtern.</td></tr>';
            document.getElementById('f-count').textContent = `${rows.length} von ${allRows.length} Titeln angezeigt`;
        }

        renderRankingTab();

        // ==========================================
        // DEPOT STATUS
        // ==========================================
        const d = depotData.depot;
        let depotHtml = `<h2>Aktueller Depot-Status</h2>
        <div class="stats-grid">
            <div class="stat-card"><h4>Gesamtvermögen</h4><p>${formatEUR(d.gesamtvermoegen)}</p></div>
            <div class="stat-card"><h4>Barbestand</h4><p>${formatEUR(d.aktueller_barbestand)}</p></div>
            <div class="stat-card"><h4>Portfoliowert</h4><p>${formatEUR(d.portfoliowert)}</p></div>
            <div class="stat-card"><h4>Startkapital</h4><p>${formatEUR(d.startkapital)}</p></div>
        </div>
        <table>
            <tr>
                <th>Wertpapier</th>
                <th>ISIN</th>
                <th>Stück</th>
                <th>Kaufkurs</th>
                <th>Börsenkurs</th>
                <th>Investiert</th>
                <th>Börsenwert</th>
                <th>Gewinn/Verlust</th>
                <th>🤖 KI-Sentiment</th>
            </tr>`;
        if (d.positionen && d.positionen.length > 0) {
            d.positionen.forEach(p => {
                let gvColor = p.gewinn_verlust >= 0 ? '#155724' : '#721c24';
                let gvBg = p.gewinn_verlust >= 0 ? '#d4edda' : '#f8d7da';
                depotHtml += `<tr>
                    <td><strong>${p.wertpapier}</strong></td>
                    <td style="color:#666;">${p.isin || ''}</td>
                    <td>${p.stueck}</td>
                    <td>${formatEUR(p.kaufkurs)}</td>
                    <td>${formatEUR(p.boersenkurs)}</td>
                    <td>${formatEUR(p.investiert)}</td>
                    <td>${formatEUR(p.boersenwert)}</td>
                    <td><span style="background-color: ${gvBg}; color: ${gvColor}; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${formatEURSign(p.gewinn_verlust)}</span></td>
                    <td>${sentimentBadge(p.isin)}</td>
                </tr>`;
            });
        }
        depotHtml += `</table>`;
        document.getElementById('depot').innerHTML = depotHtml;

        // ==========================================
        // ETF-SLEEVE (separates Budget, passiv)
        // ==========================================
        (function renderEtfSleeve() {
            const e = depotData.etf_depot;
            if (!e) {
                document.getElementById('etfsleeve').innerHTML = '<p style="color:#6c757d;">Noch kein ETF-Sleeve angelegt.</p>';
                return;
            }
            let html = `<h2>📊 ETF-Sleeve <small style="font-size:0.5em; color:#6c757d;">(separates Budget, passive Diversifikation je Sektor)</small></h2>
            <div class="stats-grid">
                <div class="stat-card"><h4>Gesamtvermögen (ETF)</h4><p>${formatEUR(e.gesamtvermoegen)}</p></div>
                <div class="stat-card"><h4>Barbestand</h4><p>${formatEUR(e.aktueller_barbestand)}</p></div>
                <div class="stat-card"><h4>ETF-Wert</h4><p>${formatEUR(e.portfoliowert)}</p></div>
                <div class="stat-card"><h4>Budget (Start)</h4><p>${formatEUR(e.startkapital)}</p></div>
            </div>
            <table>
                <tr>
                    <th>Sektor</th>
                    <th>ETF</th>
                    <th>ISIN</th>
                    <th>Stück</th>
                    <th>Kaufkurs</th>
                    <th>Kurs</th>
                    <th>Investiert</th>
                    <th>Wert</th>
                    <th>Gewinn/Verlust</th>
                    <th>KI-Sentiment</th>
                </tr>`;
            (e.positionen || []).forEach(p => {
                let gvColor = p.gewinn_verlust >= 0 ? '#155724' : '#721c24';
                let gvBg = p.gewinn_verlust >= 0 ? '#d4edda' : '#f8d7da';
                html += `<tr>
                    <td>${p.sektor}</td>
                    <td><strong>${p.wertpapier}</strong></td>
                    <td style="color:#666;">${p.isin || ''}</td>
                    <td>${p.stueck}</td>
                    <td>${formatEUR(p.kaufkurs)}</td>
                    <td>${formatEUR(p.boersenkurs)}</td>
                    <td>${formatEUR(p.investiert)}</td>
                    <td>${formatEUR(p.boersenwert)}</td>
                    <td><span style="background-color: ${gvBg}; color: ${gvColor}; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${formatEURSign(p.gewinn_verlust)}</span></td>
                    <td>${etfSentimentBadge(p.isin)}</td>
                </tr>`;
            });
            html += `</table>`;
            const etfGen = (etfSentimentData && etfSentimentData.generated_at) ? etfSentimentData.generated_at : null;
            if (etfGen) html += `<p style="color:#6c757d; font-size:0.85em;">KI-Sentiment Stand: ${etfGen} · (A) Themen-ETF, (B) Sektor-ETF · rein informativ, kein Auto-Trading im ETF-Sleeve</p>`;

            const etfTx = (e.transaktionshistorie || []).slice().sort((a, b) => (b.datum || '').localeCompare(a.datum || ''));
            if (etfTx.length > 0) {
                html += `<h3 style="margin-top:30px;">Transaktionshistorie (ETF-Sleeve)</h3><table>
                    <tr>
                        <th>Datum</th>
                        <th>Typ</th>
                        <th>Sektor</th>
                        <th>ETF</th>
                        <th>Stück</th>
                        <th>Kurs</th>
                        <th>Gebühr</th>
                        <th>Gesamt</th>
                        <th>Notiz</th>
                    </tr>`;
                etfTx.forEach(t => {
                    let typColor = t.typ === 'Kauf' ? 'color: #155724;' : 'color: #721c24;';
                    html += `<tr>
                        <td>${t.datum || ''}</td>
                        <td style="${typColor} font-weight:bold;">${t.typ || ''}</td>
                        <td>${t.sektor || ''}</td>
                        <td><strong>${t.wertpapier}</strong><br><small style="color:#666">${t.isin || ''}</small></td>
                        <td>${t.stueck}</td>
                        <td>${formatEUR(t.kurs)}</td>
                        <td>${formatEUR(t.gebuehr)}</td>
                        <td>${formatEUR(t.gesamt)}</td>
                        <td style="font-size:0.9em;">${t.notiz || ''}</td>
                    </tr>`;
                });
                html += `</table>`;
            }
            document.getElementById('etfsleeve').innerHTML = html;
        })();

        // ==========================================
        // ETF-EMPFEHLUNGS-RANKING (Composite-Score über den gesamten Katalog)
        // ==========================================
        (function renderEtfRanking() {
            const sektoren = (etfRankingData && etfRankingData.sektoren) || {};
            const rows = [];
            Object.keys(sektoren).forEach(sektor => {
                sektoren[sektor].forEach(r => rows.push(Object.assign({ sektor }, r)));
            });
            if (!rows.length) {
                document.getElementById('etfranking').innerHTML = '<p style="color:#6c757d;">Noch kein ETF-Ranking berechnet (etf_ranking.py).</p>';
                return;
            }

            const bucketCls = { CORE: 'buy', SATELLITE: 'hold', BEOBACHTEN: 'hold', MEIDEN: 'sell' };
            function bucketBadge(b) {
                return `<span class="badge ${bucketCls[b] || 'hold'}">${b}</span>`;
            }

            const etfSectors = ['Alle', ...new Set(rows.map(r => r.sektor))];
            const buckets = ['Alle', 'CORE', 'SATELLITE', 'BEOBACHTEN', 'MEIDEN'];
            let etfUiState = { sort: 'composite', dir: 'desc', sektor: 'Alle', bucket: 'Alle', minScore: 0 };

            function renderTab() {
                const sectorOpts = etfSectors.map(s => `<option value="${s}"${etfUiState.sektor===s?' selected':''}>${s}</option>`).join('');
                const bucketOpts = buckets.map(b => `<option value="${b}"${etfUiState.bucket===b?' selected':''}>${b}</option>`).join('');
                const genAt = etfRankingData.generated_at ? `Stand: ${etfRankingData.generated_at}` : '';
                const header = `
                    <h2>🌐 ETF-Empfehlungs-Ranking <small style="font-size:0.5em; color:#6c757d;">${genAt}</small></h2>
                    <div class="weights-info">
                        <strong>Composite-Score</strong> — Gewichtung: Momentum 35 % (Trend/Return/RSI) · Risiko 25 % (Volatilität/Drawdown/Ertrag-Risiko) · Sentiment 20 % · Struktur 20 % (TER/Fondsgröße).
                        <br>
                        <strong>Bucket</strong>: CORE ≥75 (basisallokationstauglich) · SATELLITE 60–74 (taktisch beimischen) · BEOBACHTEN 45–59 · MEIDEN &lt;45 oder Fondsgröße &lt;50 Mio. €.
                        Peer-Rang = Platzierung innerhalb des Themen-Sektors.
                    </div>
                    <div class="filter-bar">
                        <div class="filter-group">
                            <label>Sektor</label>
                            <select id="ef-sektor">${sectorOpts}</select>
                        </div>
                        <div class="filter-group">
                            <label>Bucket</label>
                            <select id="ef-bucket">${bucketOpts}</select>
                        </div>
                        <div class="filter-group">
                            <label>Min. Score: <span id="ef-minScore-val">${etfUiState.minScore}</span></label>
                            <input type="range" id="ef-minScore" min="0" max="100" step="5" value="${etfUiState.minScore}">
                        </div>
                        <div class="filter-group">
                            <button class="filter-reset" id="ef-reset">Filter zurücksetzen</button>
                        </div>
                    </div>
                    <div class="filter-count" id="ef-count"></div>
                `;

                const cols = [
                    { key: 'wertpapier', label: 'ETF', sortable: true },
                    { key: 'sektor', label: 'Sektor', sortable: true },
                    { key: 'composite', label: 'Score', sortable: true },
                    { key: 'momentum', label: 'Momentum', sortable: true },
                    { key: 'risiko', label: 'Risiko', sortable: true },
                    { key: 'sentiment', label: 'Sentiment', sortable: true },
                    { key: 'struktur', label: 'Struktur', sortable: true },
                    { key: 'ter', label: 'TER', sortable: true },
                    { key: 'aum', label: 'AUM Mio.€', sortable: true },
                    { key: 'peer', label: 'Peer-Rang', sortable: false },
                    { key: 'bucket', label: 'Bucket', sortable: false }
                ];
                const thHtml = cols.map(c => {
                    const active = c.sortable && etfUiState.sort === c.key;
                    const arrow = active ? (etfUiState.dir === 'asc' ? '▲' : '▼') : '↕';
                    return c.sortable
                        ? `<th class="sortable${active?' sorted':''}" data-sort="${c.key}">${c.label}<span class="arrow">${arrow}</span></th>`
                        : `<th>${c.label}</th>`;
                }).join('');

                document.getElementById('etfranking').innerHTML = header + `<table id="etf-ranking-table"><thead><tr>${thHtml}</tr></thead><tbody id="etf-ranking-body"></tbody></table>`;

                document.getElementById('ef-sektor').addEventListener('change', e => { etfUiState.sektor = e.target.value; refreshBody(); });
                document.getElementById('ef-bucket').addEventListener('change', e => { etfUiState.bucket = e.target.value; refreshBody(); });
                document.getElementById('ef-minScore').addEventListener('input', e => {
                    etfUiState.minScore = Number(e.target.value);
                    document.getElementById('ef-minScore-val').textContent = etfUiState.minScore;
                    refreshBody();
                });
                document.getElementById('ef-reset').addEventListener('click', () => {
                    etfUiState = { sort: 'composite', dir: 'desc', sektor: 'Alle', bucket: 'Alle', minScore: 0 };
                    renderTab();
                });
                document.querySelectorAll('#etf-ranking-table th.sortable').forEach(th => {
                    th.addEventListener('click', () => {
                        const k = th.dataset.sort;
                        if (etfUiState.sort === k) etfUiState.dir = etfUiState.dir === 'asc' ? 'desc' : 'asc';
                        else { etfUiState.sort = k; etfUiState.dir = (k === 'wertpapier' || k === 'sektor') ? 'asc' : 'desc'; }
                        renderTab();
                    });
                });

                refreshBody();
            }

            function refreshBody() {
                let filtered = rows.slice();
                if (etfUiState.sektor !== 'Alle') filtered = filtered.filter(r => r.sektor === etfUiState.sektor);
                if (etfUiState.bucket !== 'Alle') filtered = filtered.filter(r => r.bucket === etfUiState.bucket);
                if (etfUiState.minScore > 0) filtered = filtered.filter(r => (r.composite || 0) >= etfUiState.minScore);

                const getVal = r => {
                    switch (etfUiState.sort) {
                        case 'wertpapier': return r.wertpapier || '';
                        case 'sektor': return r.sektor || '';
                        case 'composite': return r.composite;
                        case 'momentum': return r.momentum.score;
                        case 'risiko': return r.risiko.score;
                        case 'sentiment': return r.sentiment.score;
                        case 'struktur': return r.struktur.score;
                        case 'ter': return r.struktur.ter;
                        case 'aum': return r.struktur.aum_mio_eur;
                        default: return 0;
                    }
                };
                filtered.sort((a, b) => {
                    const av = getVal(a), bv = getVal(b);
                    if (av === null || av === undefined) return 1;
                    if (bv === null || bv === undefined) return -1;
                    if (typeof av === 'string') return etfUiState.dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
                    return etfUiState.dir === 'asc' ? av - bv : bv - av;
                });

                const body = filtered.map(r => {
                    const warnBadge = (r.warnings && r.warnings.length)
                        ? `<span class="data-warning" title="${r.warnings.join(' | ').replace(/"/g,'&quot;')}">⚠️</span>`
                        : '';
                    return `<tr>
                        <td><strong>${r.wertpapier}</strong>${warnBadge}<br><small style="color:#666">${r.isin}</small></td>
                        <td>${r.sektor}</td>
                        <td>${scoreCell(r.composite)}</td>
                        <td>${subscoreBar(r.momentum.score)}</td>
                        <td>${subscoreBar(r.risiko.score)}</td>
                        <td>${subscoreBar(r.sentiment.score)}</td>
                        <td>${subscoreBar(r.struktur.score)}</td>
                        <td>${r.struktur.ter !== null && r.struktur.ter !== undefined ? r.struktur.ter.toFixed(2) + '%' : '-'}</td>
                        <td>${r.struktur.aum_mio_eur !== null && r.struktur.aum_mio_eur !== undefined ? r.struktur.aum_mio_eur.toLocaleString('de-DE') : '-'}</td>
                        <td style="color:#666;">${r.peer_rank}/${r.peer_total}</td>
                        <td>${bucketBadge(r.bucket)}</td>
                    </tr>`;
                }).join('');

                document.getElementById('etf-ranking-body').innerHTML = body || '<tr><td colspan="11" style="text-align:center; padding:30px; color:#6c757d;">Keine ETFs passen zu den aktuellen Filtern.</td></tr>';
                document.getElementById('ef-count').textContent = `${filtered.length} von ${rows.length} ETFs angezeigt`;
            }

            renderTab();
        })();

        // ==========================================
        // KI-SENTIMENT (Stufe 1 + 2)
        // ==========================================
        (function renderSentiment() {
            // ISIN -> Name aus Chart-/Fundamentaldaten ableiten (deckt Aktien und
            // die ETF-Sleeve-ETFs ab, da diese ebenfalls in den Sektor-Katalogen stehen).
            const nameByIsin = {};
            [chartData, fundaData].forEach(ds => {
                if (ds && ds.sektoren) Object.keys(ds.sektoren).forEach(sek => {
                    (ds.sektoren[sek] || []).forEach(w => {
                        if (w.isin && !nameByIsin[w.isin]) nameByIsin[w.isin] = w.wertpapier || w.isin;
                    });
                });
            });
            (depotData.etf_depot && depotData.etf_depot.positionen || []).forEach(p => {
                if (p.isin && !nameByIsin[p.isin]) nameByIsin[p.isin] = p.wertpapier || p.isin;
            });
            const depotIsinSet = new Set((depotData.depot.positionen || []).map(p => p.isin));
            (depotData.etf_depot && depotData.etf_depot.positionen || []).forEach(p => {
                if (p.isin) depotIsinSet.add(p.isin);
            });

            // Aktien- und ETF-Sentiment zu einer Liste zusammenführen (gleiche Feldform:
            // sentiment_score, begruendung; ETFs haben zusätzlich `typ`, Aktien ggf. `veto`).
            const combined = {};
            Object.keys(sentimentScores).forEach(isin => { combined[isin] = sentimentScores[isin]; });
            Object.keys(etfSentimentScores).forEach(isin => { combined[isin] = etfSentimentScores[isin]; });
            const isins = Object.keys(combined);
            const gen = (sentimentData && sentimentData.generated_at) ? sentimentData.generated_at : null;
            const etfGen = (etfSentimentData && etfSentimentData.generated_at) ? etfSentimentData.generated_at : null;

            let html = `<h2>🤖 KI-Sentiment <small style="font-size:0.5em; color:#6c757d;">(News-Stimmung pro Wert, −3 bis +3 · bei Aktien dritter Score-Faktor in der Trade-Entscheidung, bei ETFs rein informativ)</small></h2>`;
            if (!isins.length) {
                html += `<p style="color:#6c757d;">Noch keine KI-Sentiment-Daten vorhanden. Werden beim nächsten Portfoliomanager-Lauf erzeugt (Schritt 5: news_raw.json → sentiment_scores.json).</p>`;
                document.getElementById('sentiment').innerHTML = html;
                return;
            }
            if (gen) html += `<p style="color:#6c757d; font-size:0.9em;">Stand Aktien: ${gen}</p>`;
            if (etfGen) html += `<p style="color:#6c757d; font-size:0.9em;">Stand ETFs: ${etfGen}</p>`;

            // Sortiert: Veto zuerst, dann nach Score absteigend.
            isins.sort((a, b) => {
                const sa = combined[a], sb = combined[b];
                if (!!sb.veto - !!sa.veto) return (!!sb.veto) - (!!sa.veto);
                return (sb.sentiment_score || 0) - (sa.sentiment_score || 0);
            });

            html += `<table>
                <tr>
                    <th>Wertpapier</th>
                    <th>ISIN</th>
                    <th>Typ</th>
                    <th>Im Depot?</th>
                    <th>Sentiment</th>
                    <th>Begründung</th>
                </tr>`;
            isins.forEach(isin => {
                const s = combined[isin];
                const isEtf = !!etfSentimentScores[isin];
                const name = nameByIsin[isin] || '<span style="color:#adb5bd">?</span>';
                const inDepot = depotIsinSet.has(isin)
                    ? '<span class="badge buy" style="min-width:auto;">✓</span>' : '';
                html += `<tr>
                    <td><strong>${name}</strong></td>
                    <td style="color:#666;">${isin}</td>
                    <td style="color:#6c757d;">${isEtf ? 'ETF' : 'Aktie'}</td>
                    <td>${inDepot}</td>
                    <td>${isEtf ? etfSentimentBadge(isin) : sentimentBadge(isin)}</td>
                    <td style="font-size:0.9em;">${(s.begruendung || '').replace(/</g,'&lt;')}</td>
                </tr>`;
            });
            html += `</table>`;
            document.getElementById('sentiment').innerHTML = html;
        })();

        // ==========================================
        // CHARTANALYSE
        // ==========================================
        let chartHtml = `<h2>Chartanalyse (Technisch)</h2>`;
        if (chartData.sektoren) {
            Object.keys(chartData.sektoren).forEach(sektor => { const werte = chartData.sektoren[sektor];
                chartHtml += `<h3 style="background-color: #ecf0f1; padding: 10px 15px; border-left: 5px solid #34495e; margin-top: 30px;">${sektor}</h3>`;
                chartHtml += `<table>
                    <tr>
                        <th>Wertpapier</th>
                        <th>Aktueller Kurs</th>
                        <th>Trend</th>
                        <th>Signal</th>
                        <th>RSI(14)</th>
                        <th>MACD</th>
                        <th>SMA 50</th>
                        <th>SMA 200</th>
                        <th>Unterstützung</th>
                        <th>Widerstand</th>
                        <th>Begründung</th>
                    </tr>`;
                werte.forEach(w => {
                    chartHtml += `<tr>
                        <td><strong>${w.wertpapier}</strong><br><small style="color:#666">${w.isin || ''}</small></td>
                        <td>${formatEUR(w.aktueller_kurs)}</td>
                        <td>${w.trend || '-'}</td>
                        <td>${getBadge(w.signal)}</td>
                        <td>${w.rsi_14 || '-'}</td>
                        <td>${w.macd || '-'}</td>
                        <td>${formatEUR(w.sma_50)}</td>
                        <td>${formatEUR(w.sma_200)}</td>
                        <td style="color: green;">${formatEUR(w.unterstuetzung)}</td>
                        <td style="color: red;">${formatEUR(w.widerstand)}</td>
                        <td style="font-size:0.9em;">${w.begruendung}</td>
                    </tr>`;
                });
                chartHtml += `</table>`;
            });
        }
        document.getElementById('chart').innerHTML = chartHtml;

        // ==========================================
        // FUNDAMENTALANALYSE (with peer comparison)
        // ==========================================
        let fundaHtml = `<h2>Fundamentalanalyse <small style="font-size:0.5em; color:#6c757d;">(mit Sektor-Peer-Vergleich: ▲ besser · ▼ schlechter als Median)</small></h2>`;
        if (fundaData.sektoren) {
            Object.keys(fundaData.sektoren).forEach(sektor => {
                const werte = fundaData.sektoren[sektor];
                const meds = sectorMedians[sektor] || {};
                fundaHtml += `<h3 style="background-color: #ecf0f1; padding: 10px 15px; border-left: 5px solid #34495e; margin-top: 30px;">${sektor}
                    <small style="font-size:0.65em; color:#6c757d; font-weight:normal; margin-left:10px;">
                        Median → KGV ${meds.kgv !== null ? meds.kgv.toFixed(1) : '–'} · Div ${meds.dividende !== null ? meds.dividende.toFixed(1)+'%' : '–'} · Umsatzw. ${meds.umsatz !== null ? meds.umsatz.toFixed(1)+'%' : '–'}
                    </small></h3>`;
                fundaHtml += `<table>
                    <tr>
                        <th>Wertpapier</th>
                        <th>Aktueller Kurs</th>
                        <th>Bewertung</th>
                        <th>Risiko</th>
                        <th>KGV <small>vs. Peer</small></th>
                        <th>Dividende <small>vs. Peer</small></th>
                        <th>Umsatzwachstum (yoy)</th>
                        <th>Gewinnwachstum (yoy)</th>
                        <th>EK-Quote</th>
                        <th>Begründung</th>
                    </tr>`;
                werte.forEach(w => {
                    const kgvV = numOrNull(w.kgv);
                    const divV = numOrNull(w.dividendenrendite);
                    const uwV = numOrNull(w.umsatzwachstum_yoy);
                    const gwV = numOrNull(w.gewinnwachstum_yoy);

                    let divText = w.dividendenrendite !== undefined ? w.dividendenrendite + '%' : '-';
                    let uwText = w.umsatzwachstum_yoy !== undefined ? w.umsatzwachstum_yoy + '%' : '-';
                    let gwText = w.gewinnwachstum_yoy !== undefined ? w.gewinnwachstum_yoy + '%' : '-';
                    let ekText = w.eigenkapitalquote !== undefined ? w.eigenkapitalquote + '%' : '-';

                    fundaHtml += `<tr>
                        <td><strong>${w.wertpapier}</strong><br><small style="color:#666">${w.isin || ''}</small></td>
                        <td>${formatEUR(w.aktueller_kurs)}</td>
                        <td>${getBadge(w.bewertung)}</td>
                        <td>${getRiskBadge(w.risiko)}</td>
                        <td>${w.kgv || '-'} <span style="margin-left:6px">${peerLabel(kgvV, meds.kgv, true)}</span></td>
                        <td>${divText} <span style="margin-left:6px">${peerLabel(divV, meds.dividende, false)}</span></td>
                        <td>${uwText} <span style="margin-left:6px">${peerLabel(uwV, meds.umsatz, false)}</span></td>
                        <td>${gwText} <span style="margin-left:6px">${peerLabel(gwV, meds.gewinn, false)}</span></td>
                        <td>${ekText}</td>
                        <td style="font-size:0.9em;">${w.begruendung}</td>
                    </tr>`;
                });
                fundaHtml += `</table>`;
            });
        }
        document.getElementById('funda').innerHTML = fundaHtml;

        // ==========================================
        // TRANSAKTIONSHISTORIE
        // ==========================================
        let transHtml = `<h2>Transaktionshistorie</h2><table>
            <tr>
                <th>Datum</th>
                <th>Typ</th>
                <th>Wertpapier</th>
                <th>Stück</th>
                <th>Kurs</th>
                <th>Gebühr</th>
                <th>Steuern</th>
                <th>Gewinn/Verlust</th>
                <th>Gesamt</th>
                <th>Begründung</th>
            </tr>`;
        if (d.transaktionshistorie) {
            const transactionsRev = d.transaktionshistorie.slice().sort((a, b) => (b.datum || '').localeCompare(a.datum || ''));
            transactionsRev.forEach(t => {
                let typColor = t.typ === 'Kauf' ? 'color: #155724;' : 'color: #721c24;';

                let gv = '-';
                if (t.gewinn_verlust !== undefined && t.gewinn_verlust !== 0 && t.typ === 'Verkauf') {
                    let style = t.gewinn_verlust > 0 ? 'color: #155724; background-color: #d4edda; padding: 4px 6px; border-radius: 4px; font-weight:bold;' : 'color: #721c24; background-color: #f8d7da; padding: 4px 6px; border-radius: 4px; font-weight:bold;';
                    gv = `<span style="${style}">${formatEURSign(t.gewinn_verlust)}</span>`;
                }

                let begruendung = t.begruendung || t.notiz || '';

                transHtml += `<tr>
                    <td style="white-space: nowrap;">${t.datum}</td>
                    <td style="${typColor}"><strong>${t.typ}</strong></td>
                    <td><strong>${t.wertpapier}</strong><br><small style="color:#666">${t.isin || ''}</small></td>
                    <td>${t.stueck}</td>
                    <td>${formatEUR(t.kurs)}</td>
                    <td>${formatEUR(t.gebuehr)}</td>
                    <td>${formatEUR(t.steuern)}</td>
                    <td>${gv}</td>
                    <td><strong>${formatEUR(t.gesamt)}</strong></td>
                    <td style="font-size: 0.85em; color: #555;">${begruendung}</td>
                </tr>`;
            });
        }
        transHtml += `</table>`;
        document.getElementById('transaktionen').innerHTML = transHtml;

        // ==========================================
        // Tab Logic
        // ==========================================
        function openTab(evt, tabName) {
            const tabcontent = document.getElementsByClassName("tab-content");
            for (let i = 0; i < tabcontent.length; i++) {
                tabcontent[i].classList.remove("active");
            }
            const tablinks = document.getElementsByClassName("tab-button");
            for (let i = 0; i < tablinks.length; i++) {
                tablinks[i].classList.remove("active");
            }
            document.getElementById(tabName).classList.add("active");
            evt.currentTarget.classList.add("active");
        }
    </script>
</body>
</html>"""

html_output = html_template.replace("CHART_DATA_PLACEHOLDER", chart_data)
html_output = html_output.replace("FUNDA_DATA_PLACEHOLDER", funda_data)
html_output = html_output.replace("DEPOT_DATA_PLACEHOLDER", depot_data)
html_output = html_output.replace("ETF_SENTIMENT_DATA_PLACEHOLDER", etf_sentiment_data)
html_output = html_output.replace("ETF_RANKING_DATA_PLACEHOLDER", etf_ranking_data)
html_output = html_output.replace("SENTIMENT_DATA_PLACEHOLDER", sentiment_data)
html_output = html_output.replace("BUILD_DATE_PLACEHOLDER", build_date)

with open(INDEX_HTML, 'w', encoding='utf-8') as f:
    f.write(html_output)

print(f"Dashboard index.html generiert. Build: {build_date}")
print(f"Datei: {INDEX_HTML}")
