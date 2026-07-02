import json, os

repo_dir = "/home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard"

with open(os.path.join(repo_dir, 'data', 'chartanalyse_ergebnisse.json'), 'r', encoding='utf-8') as f:
    chart_data = f.read()
with open(os.path.join(repo_dir, 'data', 'fundamentalanalyse_ergebnisse.json'), 'r', encoding='utf-8') as f:
    funda_data = f.read()
with open(os.path.join(repo_dir, 'data', 'depot_status.json'), 'r', encoding='utf-8') as f:
    depot_data = f.read()

html_template = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Virtual Portfolio Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; text-align: center; margin-bottom: 30px; }
        h2, h3 { color: #34495e; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 0.9em; }
        th, td { padding: 10px 12px; border-bottom: 1px solid #ddd; text-align: left; }
        th { background-color: #34495e; color: white; position: sticky; top: 0; }
        tr:hover { background-color: #f9f9f9; }
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; display: inline-block; text-align: center; width: 75px; }
        .buy { background-color: #d4edda; color: #155724; }
        .hold { background-color: #fff3cd; color: #856404; }
        .sell { background-color: #f8d7da; color: #721c24; }
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
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Virtual Portfolio Dashboard <br><small style="font-size: 0.5em; color: #7f8c8d;">Stand: 02.07.2026</small></h1>
        
        <div class="tab-buttons">
            <button class="tab-button active" onclick="openTab(event, 'depot')">Depot Status</button>
            <button class="tab-button" onclick="openTab(event, 'chart')">Chartanalyse</button>
            <button class="tab-button" onclick="openTab(event, 'funda')">Fundamentalanalyse</button>
            <button class="tab-button" onclick="openTab(event, 'transaktionen')">Transaktionshistorie</button>
        </div>

        <div id="depot" class="tab-content active"></div>
        <div id="chart" class="tab-content"></div>
        <div id="funda" class="tab-content"></div>
        <div id="transaktionen" class="tab-content"></div>
    </div>

    <script>
        const chartData = CHART_DATA_PLACEHOLDER;
        const fundaData = FUNDA_DATA_PLACEHOLDER;
        const depotData = DEPOT_DATA_PLACEHOLDER;

        function getBadge(rating) {
            if (!rating) return '';
            const r = rating.toLowerCase();
            if (r.includes("kauf") || r.includes("attraktiv")) return `<span class="badge buy">${rating}</span>`;
            if (r.includes("halt") || r.includes("fair")) return `<span class="badge hold">${rating}</span>`;
            if (r.includes("verkauf") || r.includes("teuer")) return `<span class="badge sell">${rating}</span>`;
            return `<span class="badge" style="background:#e2e3e5; color:#333;">${rating}</span>`;
        }
        
        function formatEUR(val) {
            if (val === undefined || val === null) return '-';
            return val.toLocaleString('de-DE', {style: 'currency', currency: 'EUR'});
        }
        
        function formatEURSign(val) {
            if (val === undefined || val === null) return '-';
            return val.toLocaleString('de-DE', {style: 'currency', currency: 'EUR', signDisplay: 'always'});
        }

        // --- DEPOT STATUS ---
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
                </tr>`;
            });
        }
        depotHtml += `</table>`;
        document.getElementById('depot').innerHTML = depotHtml;

        // --- CHARTANALYSE ---
        let chartHtml = `<h2>Chartanalyse (Technisch)</h2>`;
        if (chartData.sektoren) {
            for (const [sektor, werte] of Object.entries(chartData.sektoren)) {
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
            }
        }
        document.getElementById('chart').innerHTML = chartHtml;

        // --- FUNDAMENTALANALYSE ---
        let fundaHtml = `<h2>Fundamentalanalyse</h2>`;
        if (fundaData.sektoren) {
            for (const [sektor, werte] of Object.entries(fundaData.sektoren)) {
                fundaHtml += `<h3 style="background-color: #ecf0f1; padding: 10px 15px; border-left: 5px solid #34495e; margin-top: 30px;">${sektor}</h3>`;
                fundaHtml += `<table>
                    <tr>
                        <th>Wertpapier</th>
                        <th>Bewertung</th>
                        <th>Risiko</th>
                        <th>KGV</th>
                        <th>Dividende</th>
                        <th>Umsatzwachstum (yoy)</th>
                        <th>Gewinnwachstum (yoy)</th>
                        <th>EK-Quote</th>
                        <th>Begründung</th>
                    </tr>`;
                werte.forEach(w => {
                    let empf = w.bewertung;
                    if(empf === "Attraktiv") empf = "Kaufen";
                    if(empf === "Teuer") empf = "Verkaufen";
                    
                    let divText = w.dividendenrendite !== undefined ? w.dividendenrendite + '%' : '-';
                    let uwText = w.umsatzwachstum_yoy !== undefined ? w.umsatzwachstum_yoy + '%' : '-';
                    let gwText = w.gewinnwachstum_yoy !== undefined ? w.gewinnwachstum_yoy + '%' : '-';
                    let ekText = w.eigenkapitalquote !== undefined ? w.eigenkapitalquote + '%' : '-';
                    
                    fundaHtml += `<tr>
                        <td><strong>${w.wertpapier}</strong><br><small style="color:#666">${w.isin || ''}</small></td>
                        <td>${getBadge(w.bewertung)}</td>
                        <td>${w.risiko || '-'}</td>
                        <td>${w.kgv || '-'}</td>
                        <td>${divText}</td>
                        <td>${uwText}</td>
                        <td>${gwText}</td>
                        <td>${ekText}</td>
                        <td style="font-size:0.9em;">${w.begruendung}</td>
                    </tr>`;
                });
                fundaHtml += `</table>`;
            }
        }
        document.getElementById('funda').innerHTML = fundaHtml;

        // --- TRANSAKTIONSHISTORIE ---
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
            const transactionsRev = [...d.transaktionshistorie].sort((a, b) => new Date(b.datum) - new Date(a.datum));
            transactionsRev.forEach(t => {
                let typColor = t.typ === 'Kauf' ? 'color: #155724;' : 'color: #721c24;';
                
                // Color coding for G/V
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

        // Tab Logic
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

with open(os.path.join(repo_dir, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(html_output)

print("Dashboard index.html generiert.")
