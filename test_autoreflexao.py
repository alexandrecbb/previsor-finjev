"""Ciclo resultado → reflexão → feedback específico, sem rede ou custos de API."""
import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from ibov.decisao_noticias import JevMemoryModel
from ibov.memoria import NewsMemory
from suporte_testes import FakeEmbeddings
from test_memoria import episode


def prepare(memory):
    for key in ("a", "b", "c"):
        memory.add(episode(id=key, event_id=key, text="Notícia contextual " + key, importance=59.))
    memory.predict("Contexto atual", "2020-01-01T13:00:00Z", query_id="q",
                   context={"available_at": "2020-01-01T12:30:00Z", "data": {}},
                   decision_model=lambda _: {"action": "buy"})


def register(memory):
    return memory.register_result("q", outcome=1, outcome_at="2020-01-01T13:05:00Z",
                                  observed_at="2020-01-01T13:06:00Z", net_return=.02)


def review(state):
    return {"lesson": "consistent", "memory_feedback": {"a": 5., "b": -5., "c": 0.},
            "generated_at": "2020-01-01T13:10:00Z"}


class AutomaticReflectionTests(unittest.TestCase):
    def test_cli_prever_processes_pending_before_new_decision_with_separate_budget(self):
        import memoria_noticias
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "memory.sqlite"
            memory = NewsMemory(database, encoder=FakeEmbeddings())
            try:
                prepare(memory)
                register(memory)
            finally:
                memory.close()
            context = Path(folder) / "context.json"
            context.write_text(json.dumps({"available_at": "2020-01-01T12:30:00Z", "data": {}}))
            decision = Mock(return_value={"action": "hold"})
            reflection = Mock(remaining=0)
            reflection.reflect.side_effect = review
            argv = ["memoria_noticias.py", "--database", str(database), "prever", "--text", "Contexto atual",
                    "--context", str(context), "--query-id", "q-next", "--without-finbert", "--event-id", "b"]
            with patch("sys.argv", argv), patch("memoria_noticias.JevMemoryModel", side_effect=[decision, reflection]) as constructor, \
                    patch("memoria_noticias.update_daily_news", return_value={"status": "no_new_news"}) as update_news, \
                    patch("ibov.memoria.SemanticEmbeddings", FakeEmbeddings), \
                    patch("memoria_noticias.datetime") as clock, patch("sys.stdout", new=io.StringIO()) as output:
                clock.now.side_effect = [pd.Timestamp("2020-01-01T13:07:00Z"), pd.Timestamp("2020-01-01T13:12:00Z")]
                memoria_noticias.main()
                result = json.loads(output.getvalue())
            reflection.reflect.assert_called_once()
            update_news.assert_called_once()
            decision.assert_called_once()
            state = decision.call_args.args[0]
            self.assertEqual(len(state["reflections"]), 1)
            self.assertEqual(state["reflections"][0]["review"]["memory_feedback"], {"a": 5., "b": -5., "c": 0.})
            self.assertEqual(state["memories"][0]["id"], "a")
            self.assertNotIn("b", [row["id"] for row in state["memories"]])
            self.assertEqual(state["memories"][0]["layer"], "mid")
            self.assertEqual(result["new_reflection_requests"], 1)
            self.assertEqual([call.kwargs["max_requests"] for call in constructor.call_args_list], [1, 1])

    def test_resume_after_committed_reflection_does_not_reapply_or_call_model(self):
        memory = NewsMemory(":memory:", encoder=FakeEmbeddings())
        try:
            prepare(memory)
            register(memory)
            reflection_id = "auto:" + hashlib.sha256(b"q").hexdigest()
            memory.reflect("q", reflection_id=reflection_id, outcome=1, outcome_at="2020-01-01T13:05:00Z",
                           created_at="2020-01-01T13:07:00Z", net_return=.02, reflection_model=review)
            model = Mock(side_effect=AssertionError("Chamada duplicada"))
            result = memory.process_pending_reflections(model, as_of="2020-01-01T13:15:00Z")
            self.assertEqual(result[0]["id"], reflection_id)
            model.assert_not_called()
            self.assertEqual(memory.db.execute("SELECT COUNT(*) FROM memory_feedback").fetchone()[0], 3)
            self.assertEqual(memory.db.execute("SELECT reflection_id FROM observed_results").fetchone()[0], reflection_id)
        finally:
            memory.close()

    def test_specific_feedback_promotes_and_is_persistent_and_nonretroactive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.sqlite"
            memory = NewsMemory(path, encoder=FakeEmbeddings())
            try:
                prepare(memory)
                before = memory.retrieve("Contexto atual", "2020-01-01T13:09:00Z")
                observation = register(memory)
                self.assertEqual(register(memory), observation)
                model = Mock(side_effect=review)
                results = memory.process_pending_reflections(model, as_of="2020-01-01T13:07:00Z")
                self.assertEqual(results[0]["created_at"], "2020-01-01T13:10:00+00:00")
                self.assertEqual(before, memory.retrieve("Contexto atual", "2020-01-01T13:09:00Z"))
                self.assertEqual(memory.memory_state("a", "2020-01-01T13:10:00Z")["layer"], "short")
                self.assertEqual(memory.memory_state("a", "2020-01-01T13:11:00Z")["layer"], "mid")
                self.assertLess(memory.memory_state("b", "2020-01-01T13:11:00Z")["importance"],
                                memory.memory_state("c", "2020-01-01T13:11:00Z")["importance"])
                self.assertEqual(memory.process_pending_reflections(model, as_of="2020-01-02T00:00:00Z"), [])
                model.assert_called_once()
                self.assertEqual(model.call_args.args[0]["observed_net_return"], .02)
                self.assertEqual(memory.db.execute("SELECT COUNT(*) FROM memory_feedback").fetchone()[0], 3)
                states = []
                memory.predict("Contexto atual", "2020-01-01T13:11:00Z",
                               context={"available_at": "2020-01-01T12:30:00Z", "data": {}},
                               decision_model=lambda state: states.append(state) or {"action": "hold"})
                self.assertEqual(states[0]["reflections"][0]["review"]["memory_feedback"], {"a": 5., "b": -5., "c": 0.})
            finally:
                memory.close()
            restarted = NewsMemory(path, encoder=FakeEmbeddings())
            try:
                self.assertEqual(restarted.process_pending_reflections(Mock(side_effect=AssertionError),
                                                                       as_of="2020-01-02T00:00:00Z"), [])
                self.assertEqual(restarted.memory_state("a", "2020-01-01T13:11:00Z")["layer"], "mid")
            finally:
                restarted.close()

    def test_failure_keeps_job_pending_and_applies_no_partial_feedback(self):
        memory = NewsMemory(":memory:", encoder=FakeEmbeddings())
        try:
            prepare(memory)
            register(memory)
            for bad in (RuntimeError("API indisponível"),
                        {"lesson": "consistent", "memory_feedback": {"a": 5.}},
                        {"lesson": "consistent", "memory_feedback": {"a": 5., "b": float("nan"), "c": 0.}}):
                model = Mock(side_effect=bad) if isinstance(bad, Exception) else Mock(return_value=bad)
                with self.assertRaises((RuntimeError, ValueError)):
                    memory.process_pending_reflections(model, as_of="2020-01-01T13:07:00Z")
                self.assertEqual(memory.db.execute("SELECT COUNT(*) FROM reflections").fetchone()[0], 0)
                self.assertEqual(memory.db.execute("SELECT COUNT(*) FROM memory_feedback").fetchone()[0], 0)
                self.assertIsNone(memory.db.execute("SELECT reflection_id FROM observed_results").fetchone()[0])
            self.assertEqual(len(memory.process_pending_reflections(review, as_of="2020-01-01T13:07:00Z")), 1)
        finally:
            memory.close()

    def test_future_unknown_results_and_double_credit_are_rejected(self):
        memory = NewsMemory(":memory:", encoder=FakeEmbeddings())
        try:
            prepare(memory)
            with self.assertRaises(ValueError):
                memory.register_result("q", outcome=None, outcome_at="2020-01-02T00:00Z", observed_at="2020-01-03T00:00Z")
            register(memory)
            model = Mock(side_effect=review)
            self.assertEqual(memory.process_pending_reflections(model, as_of="2020-01-01T13:05:00Z"), [])
            model.assert_not_called()
            with self.assertRaises(ValueError):
                memory.register_result("q", outcome=0, outcome_at="2020-01-01T13:05:00Z", observed_at="2020-01-01T13:06:00Z")
            memory.record_outcome("q", net_return=.02, outcome_at="2020-01-01T13:05:00Z", created_at="2020-01-01T13:06:00Z")
            with self.assertRaisesRegex(ValueError, "crédito duplo"):
                memory.process_pending_reflections(model, as_of="2020-01-01T13:07:00Z")
            model.assert_not_called()
        finally:
            memory.close()

    def test_jev_questions_map_to_ids_and_cached_reflection_has_specific_feedback(self):
        def answer(choice, names):
            return {"choice": choice, "probabilities": {key: float(key == choice) for key in names}}
        response = {"model": "jev-1.14.0", "answers": {
            "lesson": answer("consistent", ("consistent", "reconsider", "insufficient")),
            **{f"memory_{i}": answer(choice, ("helpful", "misleading", "insufficient"))
               for i, choice in enumerate(("helpful", "misleading", "insufficient"))}}}
        state = {"original": {"memories": [{"id": key} for key in ("a", "b", "c")]},
                 "observed_outcome": 1, "observed_net_return": .02}
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-key"}):
            model = JevMemoryModel(cache_dir=folder)
            with patch("ibov.decisao_noticias.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
                result = model.reflect(state)
                self.assertEqual(result["memory_feedback"], {"a": 5., "b": -5., "c": 0.})
                self.assertEqual(model.reflect(state), result)
                call.assert_called_once()
                questions = json.loads(call.call_args.args[0].data)["questions"]
                self.assertEqual(set(questions), {"lesson", "memory_0", "memory_1", "memory_2"})
                self.assertEqual(result["memory_assessments"]["b"]["choice"], "misleading")
