"""Regressionstests für die Aktien-Engine (update_depot.py).

Läuft ohne Netz und ohne echte Datenfiles: Eingabedaten werden direkt in die
Modul-Globals injiziert, Live-Preise über state.live_prices vorbelegt bzw.
get_live_price gepatcht. Getestet wird die Handels-KERNLOGIK — genau die
Stellen, an denen frühere Bugs Geld gekostet haben (9-Tage-Crash an
trend=null, Dashboard/Engine-Drift, Klumpenrisiko).

Ausführen: python3 -m unittest discover -s tests -q
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import update_depot as eng


def make_chart_item(isin, name="Test AG", **over):
    item = {
        # Defaults ergeben mit dem Funda-Fixture Score 7 (>= SELL_THRESHOLD),
        # damit Stop-Loss-Tests nicht versehentlich am Score-Verkauf scheitern.
        "isin": isin, "wertpapier": name, "empfehlung": "Halten",
        "trend": "Seitwärts", "rsi_14": 45.0, "macd": "Neutral",
        "aktueller_kurs": 100.0, "sma_50": 100.0, "sma_200": 100.0,
        "unterstuetzung": 90.0, "widerstand": 110.0,
        "momentum_12_1": 10.0, "volatility_20d": 2.0,
        "indicators_source": "yahoo:TEST.DE", "begruendung": "",
    }
    item.update(over)
    return item


def make_funda_item(isin, name="Test AG", **over):
    item = {
        "isin": isin, "wertpapier": name, "empfehlung": "Halten",
        "bewertung": "Neutral", "risiko": "Mittel", "begruendung": "",
    }
    item.update(over)
    return item


def make_position(isin, name="Test AG", stueck=10, kaufkurs=100.0, kurs=100.0,
                  score=8, **over):
    p = {
        "isin": isin, "wertpapier": name, "stueck": stueck,
        "kaufkurs": kaufkurs, "boersenkurs": kurs,
        "investiert": round(stueck * kaufkurs, 2),
        "boersenwert": round(stueck * kurs, 2),
        "gewinn_verlust": round(stueck * (kurs - kaufkurs), 2),
        "score": score, "beta": 1.0,
        "dax_ref": 100.0, "stop_ref_kurs": kaufkurs,
    }
    p.update(over)
    return p


class EngineTestCase(unittest.TestCase):
    """Setzt die Modul-Globals der Engine auf einen sauberen Fixture-Zustand."""

    def setUp(self):
        eng.chart_data = {"sektoren": {}}
        eng.funda_data = {"sektoren": {}}
        eng.sentiment_data = {"scores": {}}
        eng.news_data = {"items": {}}
        eng.earnings_data = {"scores": {}}
        eng.isin_to_name = {}
        eng.sector_map = {}
        eng.dax_now = 100.0
        eng.dax_closes = []          # -> get_beta fällt auf BETA_DEFAULT zurück (kein Netz)
        eng._beta_cache = {}
        self._orig_live_price = eng.get_live_price
        eng.get_live_price = lambda isin: None   # Netz-Zugriff im Test verboten

    def tearDown(self):
        eng.get_live_price = self._orig_live_price

    def add_paper(self, isin, sektor="Tech", chart=None, funda=None, name="Test AG"):
        eng.chart_data["sektoren"].setdefault(sektor, []).append(
            chart if chart is not None else make_chart_item(isin, name))
        eng.funda_data["sektoren"].setdefault(sektor, []).append(
            funda if funda is not None else make_funda_item(isin, name))
        eng.isin_to_name[isin] = name
        eng.sector_map[isin] = sektor

    def make_state(self, positions, cash=1000.0, live_prices=None):
        return eng.RunState(
            current_cash=cash, positions=positions, transactions=[],
            initial_tx_count=0, live_prices=dict(live_prices or {}),
        )


class TestChartScoreRobustness(EngineTestCase):
    def test_trend_null_does_not_crash(self):
        # Regression 2026-07-16: trend=None crashte die Engine 9 Tage lang still.
        self.add_paper("DE0000000001", chart=make_chart_item(
            "DE0000000001", empfehlung=None, trend=None, rsi_14=None,
            macd=None, momentum_12_1=None, sma_50=None, sma_200=None))
        score, details = eng.compute_chart_score("DE0000000001")
        self.assertIsInstance(score, (int, float))

    def test_all_inputs_missing_is_neutral(self):
        score, _ = eng.compute_chart_score("XX0000000000")
        self.assertEqual(score, 0)

    def test_momentum_staffelung(self):
        for mom, expected in [(25, 3), (10, 2), (2, 1), (-5, -1), (-15, -2)]:
            eng.chart_data = {"sektoren": {"T": [make_chart_item(
                "DE0000000002", empfehlung=None, trend=None, rsi_14=None,
                macd=None, sma_50=None, sma_200=None, momentum_12_1=mom)]}}
            score, _ = eng.compute_chart_score("DE0000000002")
            self.assertEqual(score, expected, f"momentum {mom}")


class TestSentimentWeighting(EngineTestCase):
    def test_materiality_keine_nullt_sentiment(self):
        isin = "DE0000000003"
        self.add_paper(isin)
        eng.sentiment_data = {"scores": {isin: {
            "sentiment_score": 3, "confidence": 1.0, "event_kategorie": "Keine"}}}
        ts_mit = eng.total_score(isin)[0]
        eng.sentiment_data = {"scores": {}}
        ts_ohne = eng.total_score(isin)[0]
        self.assertEqual(ts_mit, ts_ohne)

    def test_zahlen_event_wirkt_voll(self):
        isin = "DE0000000004"
        self.add_paper(isin)
        eng.sentiment_data = {"scores": {isin: {
            "sentiment_score": 3, "confidence": 1.0, "event_kategorie": "Zahlen"}}}
        ts_mit = eng.total_score(isin)[0]
        eng.sentiment_data = {"scores": {}}
        ts_ohne = eng.total_score(isin)[0]
        self.assertEqual(ts_mit - ts_ohne, 3)

    def test_earnings_summand_gedaempft(self):
        isin = "DE0000000005"
        self.add_paper(isin)
        eng.earnings_data = {"scores": {isin: {
            "earnings_score": 3, "confidence": 1.0, "guidance_richtung": "angehoben"}}}
        ts_mit = eng.total_score(isin)[0]
        eng.earnings_data = {"scores": {}}
        ts_ohne = eng.total_score(isin)[0]
        self.assertEqual(ts_mit - ts_ohne, round(3 * 1.0 * eng.EARNINGS_WEIGHT))

    def test_kaputte_sentiment_werte_crashen_nicht(self):
        isin = "DE0000000006"
        eng.sentiment_data = {"scores": {isin: {
            "sentiment_score": "kaputt", "confidence": None, "veto": False}}}
        s, veto, _, conf, _ = eng.get_sentiment(isin)
        self.assertEqual(s, 0)
        self.assertEqual(conf, eng.DEFAULT_CONFIDENCE)


class TestStopLoss(EngineTestCase):
    def test_absoluter_hard_stop(self):
        isin = "DE0000000010"
        self.add_paper(isin)
        p = make_position(isin, kaufkurs=100.0)
        state = self.make_state([p], live_prices={isin: 79.0})  # -21%
        eng.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("Hard-Stop", state.transactions[0]["notiz"])

    def test_relativer_stop_bei_underperformance(self):
        isin = "DE0000000011"
        self.add_paper(isin)
        # Kurs -10% seit Anker, DAX +5% -> Alpha -15% <= -12% -> Verkauf
        eng.dax_now = 105.0
        p = make_position(isin, kaufkurs=100.0, dax_ref=100.0, stop_ref_kurs=100.0)
        state = self.make_state([p], live_prices={isin: 90.0})
        eng.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("Relativer Stop", state.transactions[0]["notiz"])

    def test_kein_stop_bei_marktbreitem_dip(self):
        isin = "DE0000000012"
        self.add_paper(isin)
        # Kurs -15%, DAX -14% -> Alpha -1% -> KEIN Verkauf (Marktbereinigung)
        eng.dax_now = 86.0
        p = make_position(isin, kaufkurs=100.0, dax_ref=100.0, stop_ref_kurs=100.0)
        state = self.make_state([p], live_prices={isin: 85.0})
        eng.phase_strategic_sell(state)
        self.assertEqual(len(state.positions), 1)

    def test_score_unter_schwelle_verkauft(self):
        isin = "XX0000000013"    # kein Chart/Funda -> Score 0 < SELL_THRESHOLD
        p = make_position(isin)
        state = self.make_state([p], live_prices={isin: 100.0})
        eng.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("Score unter Schwellwert", state.transactions[0]["notiz"])

    def test_trailing_anker_wandert_nach_oben(self):
        isin = "DE0000000014"
        self.add_paper(isin)
        eng.dax_now = 120.0
        p = make_position(isin, kaufkurs=100.0, dax_ref=100.0, stop_ref_kurs=100.0)
        state = self.make_state([p], live_prices={isin: 130.0})
        eng.phase_strategic_sell(state)
        self.assertEqual(state.positions[0]["stop_ref_kurs"], 130.0)
        self.assertEqual(state.positions[0]["dax_ref"], 120.0)


class TestVerkaufsRecord(EngineTestCase):
    def test_steuer_nur_auf_gewinn(self):
        p = make_position("DE1", stueck=10, kaufkurs=100.0)
        tx, net = eng._make_sell_record(p, 120.0, "t", "t")
        gv_brutto = 10 * 120.0 - eng.fee_per_trade - 1000.0
        self.assertAlmostEqual(tx["steuern"], round(gv_brutto * eng.CAP_GAINS_TAX, 2))
        tx2, net2 = eng._make_sell_record(p, 80.0, "t", "t")
        self.assertEqual(tx2["steuern"], 0.0)
        self.assertAlmostEqual(net2, 10 * 80.0 - eng.fee_per_trade)


class TestSektorAbbau(EngineTestCase):
    def test_sektor_ueber_cap_wird_abgebaut(self):
        for i, (isin, sektor, score) in enumerate([
                ("DE0000000020", "Luftfahrt", 2), ("DE0000000021", "Luftfahrt", 9),
                ("DE0000000022", "Energie", 8), ("DE0000000023", "Chemie", 8)]):
            self.add_paper(isin, sektor=sektor)
        positions = [
            make_position("DE0000000020", stueck=20, score=2),   # 2000€ Luftfahrt
            make_position("DE0000000021", stueck=20, score=9),   # 2000€ Luftfahrt
            make_position("DE0000000022", stueck=30, score=8),   # 3000€ Energie
            make_position("DE0000000023", stueck=30, score=8),   # 3000€ Chemie
        ]
        state = self.make_state(positions)   # Luftfahrt = 40% > 33%
        eng.phase_sector_reduction(state)
        pct = eng._sector_pct(state.positions, "Luftfahrt")
        self.assertLessEqual(pct, eng.SEKTOR_SOFT_CAP + 1e-9)
        # Schwächste Position (Score 2) muss zuerst verkauft worden sein.
        self.assertEqual(state.transactions[0]["isin"], "DE0000000020")

    def test_sektor_knapp_ueber_cap_bleibt(self):
        # 31% < Cap+Toleranz (33%) -> Hysterese, kein Eingriff
        for isin, sektor, stueck in [
                ("DE0000000024", "Luftfahrt", 31), ("DE0000000025", "Energie", 25),
                ("DE0000000026", "Chemie", 25), ("DE0000000027", "Utility", 19)]:
            self.add_paper(isin, sektor=sektor)
        positions = [make_position(i, stueck=s) for i, _, s in [
            ("DE0000000024", "", 31), ("DE0000000025", "", 25),
            ("DE0000000026", "", 25), ("DE0000000027", "", 19)]]
        state = self.make_state(positions)
        eng.phase_sector_reduction(state)
        self.assertEqual(len(state.positions), 4)

    def test_capped_budget_bremst_sektor_kauf(self):
        self.add_paper("DE0000000026", sektor="Tech")
        positions = [make_position("DE0000000026", stueck=29)]  # 2900€ Tech
        positions.append(make_position("XX_neutral", stueck=71))  # 7100€ ohne Sektor
        eng.sector_map["DE0000000027"] = "Tech"
        budget = eng.capped_budget(1000.0, "DE0000000027", positions)
        # Erlaubt ist nur x mit (2900+x)/(10000+x) = 30% -> x = 142.86
        self.assertAlmostEqual(budget, (0.30 * 10000 - 2900) / 0.70, places=2)


class TestPositionsCap(EngineTestCase):
    def test_position_ueber_cap_wird_getrimmt(self):
        positions = [make_position("DE0000000040", stueck=30)]   # 3000€ = 30%
        for i, stueck in enumerate([18, 18, 17, 17]):
            positions.append(make_position(f"DE000000004{i+1}", stueck=stueck))
        state = self.make_state(positions)
        eng.phase_position_trim(state)
        tot = sum(p["boersenwert"] for p in state.positions)
        top = max(p["boersenwert"] for p in state.positions)
        self.assertLessEqual(top / tot, eng.MAX_POS_PCT + eng.POS_CAP_TOLERANCE + 0.01)
        # Teilverkauf, kein Ganzverkauf:
        self.assertEqual(len(state.positions), 5)
        self.assertEqual(state.transactions[0]["typ"], "Verkauf")
        self.assertLess(state.transactions[0]["stueck"], 30)

    def test_hysterese_bei_21_prozent(self):
        positions = [make_position("DE0000000042", stueck=21)]   # 21% < 22% Trigger
        for i, stueck in enumerate([20, 20, 20, 19]):
            positions.append(make_position(f"DE000000004{i+3}", stueck=stueck))
        state = self.make_state(positions)
        eng.phase_position_trim(state)
        self.assertEqual(state.transactions, [])

    def test_kein_trim_bei_ausgeduenntem_depot(self):
        # Regression Verkaufsspirale: mit < 5 Positionen ist der 20%-Cap
        # rechnerisch unerreichbar -> Phase greift gar nicht ein.
        positions = [make_position("DE0000000048", stueck=70),
                     make_position("DE0000000049", stueck=30)]
        state = self.make_state(positions)
        eng.phase_position_trim(state)
        self.assertEqual(state.transactions, [])
        self.assertEqual(len(state.positions), 2)

    def test_kaufbudget_wird_auf_cap_gekappt(self):
        positions = [make_position("DE0000000044", stueck=80)]   # 8000€ Portfolio
        capped = eng.position_capped_budget(2500.0, positions)
        self.assertAlmostEqual(capped, eng.MAX_POS_PCT * 8000 / (1 - eng.MAX_POS_PCT), places=2)

    def test_bootstrap_leeres_depot_darf_kaufen(self):
        # Regression: Sektor-/Positions-Cap dürfen ein leeres Depot nicht
        # dauerhaft blockieren (allowed=0-Deadlock).
        eng.sector_map["DE0000000045"] = "Tech"
        self.assertEqual(eng.capped_budget(1000.0, "DE0000000045", []), 1000.0)
        self.assertEqual(eng.position_capped_budget(1000.0, []), 1000.0)


class TestKaufphase(EngineTestCase):
    def test_adaptive_schwelle_fallback_und_perzentil(self):
        self.assertEqual(eng.compute_adaptive_buy_threshold([5, 6]), eng.BUY_FALLBACK_THRESHOLD)
        scores = list(range(1, 21))     # 1..20 -> 80er-Perzentil = 17
        self.assertEqual(eng.compute_adaptive_buy_threshold(scores), 17)

    def test_budget_for_score(self):
        self.assertEqual(eng.budget_for_score(8, 8), eng.BUDGET_BASE)
        self.assertEqual(eng.budget_for_score(12, 8), eng.BUDGET_BASE + 4 * eng.BUDGET_PER_POINT)
        self.assertEqual(eng.budget_for_score(99, 8), eng.BUDGET_MAX)

    def test_vol_size_multiplier_grenzen(self):
        isin = "DE0000000030"
        for vol, expected in [(1.0, eng.VOL_MULT_MAX), (2.0, 1.0), (8.0, eng.VOL_MULT_MIN)]:
            eng.chart_data = {"sektoren": {"T": [make_chart_item(isin, volatility_20d=vol)]}}
            self.assertEqual(eng.vol_size_multiplier(isin), expected, f"vol {vol}")
        eng.chart_data = {"sektoren": {"T": [make_chart_item(isin, volatility_20d=None)]}}
        self.assertEqual(eng.vol_size_multiplier(isin), 1.0)

    def test_kauf_respektiert_cash_reserve(self):
        isin = "DE0000000031"
        self.add_paper(isin)
        eng.sector_map.pop(isin)   # ohne Sektor-Zuordnung greift kein Sektor-Cap
        state = self.make_state([], cash=200.0, live_prices={isin: 10.0})
        state.buy_threshold = 8
        eng.phase_buy(state, [(isin, 10)])
        # Kauf findet statt, aber die Mindest-Barreserve bleibt unangetastet.
        self.assertEqual(len(state.positions), 1)
        self.assertGreaterEqual(state.current_cash, eng.MIN_CASH_RESERVE)

    def test_veto_blockiert_neukauf(self):
        isin = "DE0000000032"
        self.add_paper(isin, chart=make_chart_item(isin, empfehlung="Kaufen",
                                                   trend="Aufwärts", rsi_14=40))
        eng.sentiment_data = {"scores": {isin: {"sentiment_score": -3, "veto": True,
                                                "begruendung": "Bilanzskandal"}}}
        state = self.make_state([])
        eng.phase_plan(state)
        self.assertNotIn(isin, state.target_isins)
        self.assertTrue(any("KI-Veto" in s for s in state.summary))

    def test_watch_kandidat_ohne_sma200_nicht_kaufbar(self):
        isin = "DE0000000033"
        self.add_paper(isin, chart=make_chart_item(isin, empfehlung="Kaufen",
                                                   sma_200=None))
        state = self.make_state([])
        eng.phase_plan(state)
        self.assertNotIn(isin, state.target_isins)


if __name__ == "__main__":
    unittest.main()
