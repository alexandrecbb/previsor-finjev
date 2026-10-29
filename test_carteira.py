"""Contabilidade e causalidade de ordens fictícias, sem rede."""
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

from ibov.avaliacao_noticias import prepare_episodes
from ibov.carteira import PaperPortfolio, simulate_portfolio
from ibov.sentimento import FinBertSentiment, enrich_news
from test_historico_noticias import prices, document
from test_sentimento import scores


from unittest.mock import patch as patch_embeddings
from suporte_testes import FakeEmbeddings

_embedding_patch = patch_embeddings("ibov.memoria.SemanticEmbeddings", FakeEmbeddings)


def setUpModule():
    _embedding_patch.start()


def tearDownModule():
    _embedding_patch.stop()


class PortfolioTests(unittest.TestCase):
    def test_fees_conservation_hold_and_no_short_or_leverage(self):
        portfolio = PaperPortfolio(1000., .01)
        self.assertEqual(portfolio.execute("sell", 100)["status"], "no_position")
        bought = portfolio.execute("buy", 100)
        self.assertAlmostEqual(bought["gross"] + bought["fee"], 1000.)
        self.assertEqual(portfolio.cash, 0)
        self.assertEqual(portfolio.execute("buy", 100)["status"], "no_cash")
        units = portfolio.units
        self.assertEqual(portfolio.execute("hold", 120)["status"], "hold")
        self.assertEqual(portfolio.units, units)
        sold = portfolio.execute("sell", 120)
        self.assertAlmostEqual(portfolio.cash, units * 120 * .99)
        self.assertEqual(portfolio.units, 0)
        self.assertAlmostEqual(portfolio.total_fees, bought["fee"] + sold["fee"])
        self.assertEqual(portfolio.execute("sell", 120)["quantity"], 0)
        with self.assertRaises(ValueError):
            portfolio.execute("buy", float("nan"))
        with self.assertRaises(ValueError):
            PaperPortfolio(-100)
        with self.assertRaises(ValueError):
            PaperPortfolio(100, 1)

    def test_next_open_no_future_prices_persisted_restart(self):
        data = prices()
        data["open"] = data["close"] - .5
        docs = [document(d.date().isoformat(), str(i)) for i, d in enumerate(data.index[30::30])]
        episodes, _ = prepare_episodes(docs, data)
        states = []
        def model(state):
            states.append(state)
            date = pd.Timestamp(state["current_context"]["data"]["base_date"])
            self.assertEqual(state["current_context"]["data"]["close"], data.loc[date, "close"])
            self.assertNotIn("open", state["current_context"]["data"])
            self.assertNotIn("outcome", state["current_context"]["data"])
            return {"action": "buy" if len(states) == 1 else "sell"}
        with tempfile.TemporaryDirectory() as directory:
            report = simulate_portfolio(episodes, data, model, directory=directory, sample_size=2)
            self.assertTrue(report["complete"])
            self.assertEqual(report["completed_decisions"], 2)
            self.assertEqual(report["filled_orders"], 2)
            self.assertEqual(report["units"], 0)
            self.assertEqual(report["orders"][0]["price"], data.loc[report["orders"][0]["date"], "open"])
            for decision in report["decisions"]:
                date = pd.Timestamp(decision["execution_date"])
                self.assertGreater(date, pd.Timestamp(states[report["decisions"].index(decision)]["current_context"]["data"]["base_date"]))
            again = simulate_portfolio(episodes, data, lambda _: self.fail("Chamada repetida"),
                                       directory=directory, sample_size=2)
            self.assertEqual(report, again)
            self.assertEqual(states[0]["current_context"]["data"]["position"]["exposure"], 0)
            self.assertAlmostEqual(states[1]["current_context"]["data"]["position"]["exposure"], 1)

    def test_finbert_full_text_hash_is_preserved_and_tail_unknown(self):
        data = prices()
        doc = document("2017-02-03")
        doc["text"] *= 100
        with tempfile.TemporaryDirectory() as cache:
            enriched = enrich_news([doc], FinBertSentiment(cache_dir=cache, predictor=scores))
            episodes, _ = prepare_episodes(enriched, data, text_limit=None)
            self.assertEqual(episodes[0]["text"], doc["text"])
            self.assertEqual(episodes[0]["sentiment"], enriched[0]["sentiment"])
            self.assertNotIn("outcome", episodes[0]["query_context"]["data"])
            with self.assertRaises(ValueError):
                prepare_episodes(enriched, data)

    def test_api_error_stops_without_inventing_a_hold_or_trade(self):
        data = prices()
        data["open"] = data["close"]
        docs = [document(d.date().isoformat(), str(i)) for i, d in enumerate(data.index[30::30])]
        episodes, _ = prepare_episodes(docs, data)
        with tempfile.TemporaryDirectory() as directory:
            report = simulate_portfolio(episodes, data, Mock(side_effect=RuntimeError("Falha de API")),
                                        directory=directory, sample_size=2)
            self.assertFalse(report["complete"])
            self.assertEqual(report["completed_decisions"], 0)
            self.assertEqual(report["orders"], [])
            self.assertEqual(report["final_equity"], 100000.)
            self.assertEqual(report["errors"][0]["error"], "Falha de API")


if __name__ == "__main__":
    unittest.main()
