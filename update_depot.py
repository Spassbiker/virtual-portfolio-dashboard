import json
from datetime import datetime

depot_path = "/home/ubuntu/.openclaw/workspace/virtual-portfolio-dashboard/depot_status.json"

with open(depot_path, "r") as f:
    data = json.load(f)

depot = data["depot"]
current_cash = depot["aktueller_barbestand"]

# We want to buy EUNL.DE, MSFT.DE, and NVDA.DE
# Prices (EUR)
prices = {
    "EUNL.DE": 130.00,
    "MSFT.DE": 325.00,
    "NVDA.DE": 185.00
}

buys = [
    {"symbol": "EUNL.DE", "name": "iShares Core MSCI World", "units": 50},
    {"symbol": "MSFT.DE", "name": "Microsoft Corp.", "units": 5},
    {"symbol": "NVDA.DE", "name": "Nvidia Corp.", "units": 8},
]

fee_per_trade = 5.00
transactions = depot.get("transaktionshistorie", [])
positions = depot.get("positionen", [])

summary = []

for b in buys:
    symbol = b["symbol"]
    name = b["name"]
    units = b["units"]
    price = prices[symbol]
    
    total_cost = (units * price) + fee_per_trade
    if current_cash >= total_cost:
        current_cash -= total_cost
        
        # update position
        found = False
        for p in positions:
            if p["symbol"] == symbol:
                # average price calculation
                total_value = p["anteile"] * p["kaufkurs_durchschnitt"] + units * price
                p["anteile"] += units
                p["kaufkurs_durchschnitt"] = round(total_value / p["anteile"], 2)
                p["aktueller_kurs"] = price
                p["gesamtwert"] = round(p["anteile"] * price, 2)
                found = True
                break
        
        if not found:
            positions.append({
                "symbol": symbol,
                "name": name,
                "anteile": units,
                "kaufkurs_durchschnitt": price,
                "aktueller_kurs": price,
                "gesamtwert": round(units * price, 2)
            })
            
        transactions.append({
            "datum": "2026-06-30",
            "typ": "Kauf",
            "symbol": symbol,
            "name": name,
            "anteile": units,
            "kurs": price,
            "gebuehren": fee_per_trade,
            "steuern": 0.0,
            "gesamtbetrag": round(total_cost, 2),
            "notiz": "Erster Aufbau Core-Satellite Strategie"
        })
        summary.append(f"Kauf: {units}x {name} ({symbol}) zu {price} EUR. Gebühren: {fee_per_trade} EUR.")

portfolio_value = sum(p["gesamtwert"] for p in positions)

depot["aktueller_barbestand"] = round(current_cash, 2)
depot["portfoliowert"] = round(portfolio_value, 2)
depot["gesamtvermoegen"] = round(current_cash + portfolio_value, 2)
depot["positionen"] = positions
depot["transaktionshistorie"] = transactions

with open(depot_path, "w") as f:
    json.dump(data, f, indent=2)

print("\n".join(summary))
