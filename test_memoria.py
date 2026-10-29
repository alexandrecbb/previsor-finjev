"""Regressões temporais da memória, sem rede."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ibov.memoria import NewsMemory, directional_outcomes


from unittest.mock import patch as patch_embeddings
from suporte_testes import FakeEmbeddings

_embedding_patch = patch_embeddings("ibov.memoria.SemanticEmbeddings", FakeEmbeddings)


def setUpModule():
    _embedding_patch.start()


def tearDownModule():
    _embedding_patch.stop()


def episode(**changes):
    return dict(dict(id="1", event_id="copom-1", text="Banco Central eleva juros Selic",
                     published_at="2020-01-01T12:00:00Z", available_at="2020-01-01T12:01:00Z",
                     classified_at="2020-01-01T12:02:00Z", outcome_at="2020-01-07T21:00:00Z",
                     outcome=0, asset="^BVSP", horizon=3, model="jev-1.14.0",
                     prompt_version="ibov-news-v1"), **changes)


class MemoryTests(unittest.TestCase):
    def test_observed_return_feedback_sign_time_and_idempotency(self):
        for action, net_return in [("buy", .02), ("sell", -.01), ("hold", 0.)]:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "feedback.sqlite"
                memory = NewsMemory(path)
                memory.add(episode())
                memory.add(episode(id="unused", event_id="unused", text="Clima futebol", asset="OUTRO"))
                memory.predict("Banco Central eleva juros Selic", "2020-01-02T00:00Z", query_id="q",
                               context={"data": {}, "available_at": "2020-01-01T22:00Z"},
                               decision_model=lambda _: {"action": action})
                args = dict(net_return=net_return, outcome_at="2020-01-03T00:00Z",
                            created_at="2020-01-03T01:00Z")
                before = memory.memory_state("1", args["created_at"])
                future_before = memory.memory_state("1", "2020-01-03T02:00Z")
                row = memory.record_outcome("q", **args)
                self.assertEqual(row["memory_ids"], ["1"])
                self.assertEqual(row, memory.record_outcome("q", **args))
                self.assertEqual(before, memory.memory_state("1", args["created_at"]))
                after = memory.memory_state("1", "2020-01-03T02:00Z")
                self.assertAlmostEqual(after["importance"] - future_before["importance"],
                                       row["delta"] * .92 ** (1 / 24))
                for invalid in [float("nan"), float("inf"), True]:
                    with self.assertRaises(ValueError):
                        memory.record_outcome("q", **{**args, "net_return": invalid})
                with self.assertRaises(ValueError):
                    memory.record_outcome("q", **{**args, "net_return": 3.})
                with self.assertRaises(ValueError):
                    memory.record_outcome("q", **{**args, "outcome_at": "2020-01-01T00:00Z"})
                memory.close()
                memory = NewsMemory(path)
                self.assertEqual(after, memory.memory_state("1", "2020-01-03T02:00Z"))
                self.assertEqual(row, memory.record_outcome("q", **args))
                memory.close()

    def test_observed_feedback_conflict_rolls_back(self):
        self.memory.add(episode())
        self.memory.predict("Banco Central eleva juros Selic", "2020-01-02T00:00Z", query_id="q",
                            context={"data": {}, "available_at": "2020-01-01T22:00Z"},
                            decision_model=lambda _: {"action": "buy"})
        self.memory.reflect("q", reflection_id="r", outcome=1, outcome_at="2020-01-03T00:00Z",
                            created_at="2020-01-03T01:00Z",
                            reflection_model=lambda _: {"memory_feedback": {"1": 5.}})
        with self.assertRaises(sqlite3.IntegrityError):
            self.memory.record_outcome("q", net_return=.01, outcome_at="2020-01-03T00:00Z",
                                       created_at="2020-01-03T02:00Z")
        self.assertEqual(self.memory.db.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0], 0)

    def setUp(self):
        self.memory = NewsMemory(":memory:")

    def tearDown(self):
        self.memory.close()

    def test_maturity_classification_and_future_do_not_leak(self):
        self.memory.add(episode(classified_at="2025-01-01T00:00:00Z"))
        query = "Banco Central eleva juros Selic"
        self.assertIsNone(self.memory.retrieve(query, "2020-01-07T21:00:00Z", retrospective=True)["memories"][0]["outcome"])
        self.assertEqual(self.memory.retrieve(query, "2020-01-08T00:00:00Z")["n_events"], 0)
        self.assertEqual(self.memory.retrieve(query, "2020-01-08T00:00:00Z", retrospective=True)["n_events"], 1)
        before = self.memory.retrieve(query, "2020-01-08T00:00:00Z", retrospective=True)
        self.memory.add(episode(id="future", event_id="future", published_at="2030-01-01T00:00:00Z",
                                available_at="2030-01-01T00:00:00Z", outcome_at="2030-01-08T00:00:00Z"))
        self.assertEqual(before, self.memory.retrieve(query, "2020-01-08T00:00:00Z", retrospective=True))

    def test_event_and_text_duplicates_do_not_multiply_evidence(self):
        self.memory.add(episode())
        self.memory.add(episode(id="2", text="Banco Central eleva juros Selic novamente"))
        self.memory.add(episode(id="3", event_id="republicacao"))
        result = self.memory.retrieve("Banco Central eleva juros Selic", "2020-01-10T00:00:00Z")
        self.assertEqual(result["n_events"], 1)
        self.assertEqual(result["memories"][0]["outcome"], 0)

    def test_context_model_overrides_historical_direction_and_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.sqlite"
            memory = NewsMemory(path)
            for i in range(3):
                memory.add(episode(id=str(i), event_id=str(i), text=f"Banco Central eleva juros Selic evento {i}"))
            memory.close()
            memory = NewsMemory(path)
            try:
                result = memory.predict("Banco Central eleva juros Selic", "2020-01-10T00:00:00Z",
                                        context={"data": {"expectations": "alta esperada"}, "available_at": "2020-01-09T00:00:00Z"},
                                        decision_model=lambda state: {"direction": "up"}, query_id="q1")
                self.assertEqual(result["prediction"], 1)
                self.assertEqual(result["n_events"], 3)
                self.assertEqual(memory.db.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0], 1)
                self.assertTrue(all(r["outcome"] == 0 for r in result["memories"]))
            finally:
                memory.close()

    def test_immutable_and_invalid_inputs(self):
        self.memory.add(episode())
        self.memory.add(episode())
        with self.assertRaises(ValueError):
            self.memory.add(episode(outcome=1))
        with self.assertRaises(ValueError):
            self.memory.add(episode(available_at="2020-01-01"))
        with self.assertRaises(ValueError):
            self.memory.add(episode(outcome_at="2019-01-01T00:00:00Z"))

    def test_trading_records_and_unknown_tail(self):
        dates = pd.to_datetime(["2020-01-03T21:00Z", "2020-01-06T21:00Z", "2020-01-07T21:00Z", "2020-01-08T21:00Z"])
        result = directional_outcomes(pd.Series([100, 99, 98, 101], index=dates))
        self.assertEqual(result.iloc[0]["outcome"], 1)
        self.assertEqual(result.iloc[0]["outcome_at"], dates[3])
        self.assertTrue(result.iloc[1:]["outcome"].isna().all())
        self.assertTrue(result.iloc[1:]["outcome_at"].isna().all())

    def test_reflections_available_only_after_creation(self):
        self.memory.add(episode(layer="long", importance=100.))
        context = {"data": {"juros": "surpresa abaixo da expectativa"}, "available_at": "2020-01-09T00:00:00Z"}
        states = []
        def model(state):
            states.append(state)
            return {"direction": "abstain"}
        self.memory.predict("Banco Central eleva juros Selic", "2020-01-10T00:00:00Z",
                            context=context, decision_model=model, query_id="q")
        with self.assertRaises(ValueError):
            self.memory.reflect("q", reflection_id="bad", outcome=1, outcome_at="2020-01-14T00:00:00Z",
                                created_at="2020-01-12T00:00:00Z", reflection_model=lambda _: {})
        self.memory.reflect("q", reflection_id="r", outcome=1, outcome_at="2020-01-14T00:00:00Z",
                            created_at="2020-01-15T00:00:00Z", reflection_model=lambda _: {"lesson": "insufficient"})
        for date in ["2020-01-15T00:00:00Z", "2020-01-16T00:00:00Z"]:
            self.memory.predict("Banco Central eleva juros Selic", date, context=context, decision_model=model)
        self.assertEqual(states[-2]["reflections"], [])
        self.assertEqual(states[-1]["reflections"][0]["id"], "r")

    def test_layer_lifecycle_and_logical_deletion(self):
        self.memory.add(episode(importance=90.))
        state = self.memory.memory_state("1", "2020-01-03T12:02:00Z")
        self.assertEqual(state["layer"], "long")
        self.assertEqual([t["to"] for t in state["transitions"]], ["mid", "long"])
        self.memory.add(episode(id="weak", layer="mid", importance=55.))
        self.assertEqual(self.memory.memory_state("weak", "2020-01-02T00:00Z")["layer"], "short")
        self.assertTrue(self.memory.memory_state("weak", "2020-02-01T00:00Z")["deleted"])
        self.assertFalse(self.memory.memory_state("weak", "2020-01-02T00:00Z")["deleted"])
        self.assertEqual(self.memory.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0], 2)

    def test_feedback_is_persistent_nonretroactive_and_not_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.sqlite"
            memory = NewsMemory(path)
            try:
                memory.add(episode())
                query = "Banco Central eleva juros Selic"
                before = memory.retrieve(query, "2020-01-03T00:00Z")
                memory.predict(query, "2020-01-02T00:00Z", query_id="q",
                               context={"data": {}, "available_at": "2020-01-01T22:00Z"},
                               decision_model=lambda _: {"action": "buy"})
                memory.reflect("q", reflection_id="r", outcome=1,
                               outcome_at="2020-01-03T00:00Z", created_at="2020-01-03T01:00Z",
                               reflection_model=lambda _: {"lesson": "consistent", "memory_feedback": {"1": 40.}})
                self.assertEqual(before, memory.retrieve(query, "2020-01-03T00:00Z"))
                at = memory.memory_state("1", "2020-01-03T01:00Z")
                after = memory.memory_state("1", "2020-01-03T02:00Z")
                self.assertEqual(at["layer"], "short")
                self.assertEqual(after["layer"], "mid")
                self.assertGreater(after["importance"], at["importance"])
                with self.assertRaises(sqlite3.IntegrityError):
                    memory.feedback("1", feedback_id="duplicate", query_id="q", delta=5.,
                                    created_at="2020-01-03T02:00Z")
                repeated = memory.retrieve(query, "2020-01-03T02:00Z")
                self.assertEqual(repeated, memory.retrieve(query, "2020-01-03T02:00Z"))
            finally:
                memory.close()
            memory = NewsMemory(path)
            try:
                self.assertEqual(repeated, memory.retrieve(query, "2020-01-03T02:00Z"))
            finally:
                memory.close()

    def test_invalid_feedback_rolls_back_reflection_and_negative_feedback_removes(self):
        self.memory.add(episode())
        self.memory.predict("Banco Central eleva juros Selic", "2020-01-02T00:00Z", query_id="q",
                            context={"data": {}, "available_at": "2020-01-01T22:00Z"},
                            decision_model=lambda _: {"action": "buy"})
        args = dict(outcome=0, outcome_at="2020-01-03T00:00Z", created_at="2020-01-03T01:00Z")
        with self.assertRaises(ValueError):
            self.memory.reflect("q", reflection_id="bad", **args,
                                reflection_model=lambda _: {"memory_feedback": {"future": 10.}})
        self.assertEqual(self.memory.db.execute("SELECT COUNT(*) FROM reflections").fetchone()[0], 0)
        self.memory.reflect("q", reflection_id="r", **args,
                            reflection_model=lambda _: {"memory_feedback": {"1": -100.}})
        self.assertTrue(self.memory.memory_state("1", "2020-01-03T02:00Z")["deleted"])
        self.assertFalse(self.memory.memory_state("1", "2020-01-03T00:00Z")["deleted"])
        with self.assertRaisesRegex(ValueError, "crédito duplo"):
            self.memory.reflect("q", reflection_id="duplicate", **args,
                                reflection_model=lambda _: {"memory_feedback": {"1": 10.}})
        self.assertEqual(self.memory.db.execute("SELECT COUNT(*) FROM reflections").fetchone()[0], 1)

    def test_layer_forgetting_rates_and_low_importance(self):
        for layer in ("short", "mid", "long"):
            self.memory.add(episode(id=layer, layer=layer, importance=100. if layer == "long" else 50.))
        short = self.memory.memory_state("short", "2020-01-02T00:00Z")
        long = self.memory.memory_state("long", "2020-01-02T00:00Z")
        self.assertLess(short["importance"] / 50., long["importance"] / 100.)
        self.memory.add(episode(id="zero", importance=0.))
        self.assertTrue(self.memory.memory_state("zero", "2020-01-02T00:00Z")["deleted"])

    def test_context_from_future_is_rejected_and_no_model_called(self):
        from unittest.mock import Mock
        model = Mock()
        with self.assertRaises(ValueError):
            self.memory.predict("notícia", "2020-01-01T00:00:00Z", decision_model=model,
                                context={"data": {}, "available_at": "2020-01-02T00:00:00Z"})
        model.assert_not_called()
