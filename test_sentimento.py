"""Sentimento e decisões de negociação com dados sintéticos, sem rede."""
from contextlib import nullcontext
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from ibov.sentimento import FinBertSentiment, enrich_news, validate_sentiment
from ibov.memoria import NewsMemory
from ibov.avaliacao_noticias import prepare_episodes, evaluate_news
from test_memoria import episode
from test_historico_noticias import prices, document


from unittest.mock import patch as patch_embeddings
from suporte_testes import FakeEmbeddings

_embedding_patch = patch_embeddings("ibov.memoria.SemanticEmbeddings", FakeEmbeddings)


def setUpModule():
    _embedding_patch.start()


def tearDownModule():
    _embedding_patch.stop()


def scores(texts):
    return [{"positive": .8, "negative": .1, "neutral": .1} for _ in texts]


class SentimentTests(unittest.TestCase):
    def test_cli_imports_collected_news_and_keeps_unknown_tail(self):
        import memoria_noticias
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            data = prices()
            docs = [document("2017-02-03", "known"), document(data.index[-1].date().isoformat(), "tail")]
            source = folder / "news.jsonl"
            source.write_text("\n".join(json.dumps(row) for row in docs))
            prices_path = folder / "prices.csv"
            data.to_csv(prices_path)
            db = folder / "memory.sqlite"
            classifier = FinBertSentiment(cache_dir=folder / "cache", predictor=scores)
            args = ["memoria_noticias.py", "--database", str(db), "importar", str(source),
                    "--prices", str(prices_path)]
            with patch("sys.argv", args), patch("memoria_noticias.FinBertSentiment", return_value=classifier), patch("sys.stdout", new=io.StringIO()):
                memoria_noticias.main()
            memory = NewsMemory(db)
            try:
                rows = {row["id"]: json.loads(row["payload"]) for row in memory.db.execute("SELECT id,payload FROM episodes")}
                self.assertEqual(set(rows), {"known", "tail"})
                self.assertIsNone(rows["tail"]["outcome"])
                self.assertIsNone(rows["tail"]["outcome_at"])
                self.assertEqual(rows["known"]["sentiment"]["label"], "positive")
                self.assertNotIn("outcome", rows["known"]["context"])
                self.assertEqual(pd.Timestamp(rows["known"]["available_at"]),
                                 pd.Timestamp(docs[0]["historical_available_at"]))
                self.assertNotIn("sentiment", json.loads(source.read_text().splitlines()[0]))
            finally:
                memory.close()

    def test_checkpoint_mapping_softmax_and_inference_mode(self):
        tokenizer = Mock(return_value={"input_ids": "tokens"})
        model = Mock()
        model.config.id2label = {0: "POSITIVE", 1: "NEGATIVE", 2: "NEUTRAL"}
        model.return_value.logits.softmax.return_value.cpu.return_value.tolist.return_value = [[.1, .8, .1]]
        torch = SimpleNamespace(inference_mode=Mock(return_value=nullcontext()))
        transformers = SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=Mock(return_value=tokenizer)),
            AutoModelForSequenceClassification=SimpleNamespace(from_pretrained=Mock(return_value=model)))
        with tempfile.TemporaryDirectory() as cache, patch.dict("sys.modules", {"torch": torch, "transformers": transformers}):
            result = FinBertSentiment(cache_dir=cache)("Empresa registra prejuízo")
            self.assertEqual(result["label"], "negative")
            model.eval.assert_called_once()
            model.to.assert_called_once_with("cpu")
            torch.inference_mode.assert_called_once()
            model.return_value.logits.softmax.assert_called_once_with(dim=-1)
            tokenizer.assert_called_once_with(["Empresa registra prejuízo"], return_tensors="pt",
                                              padding=True, truncation=True, max_length=512)

    def test_batch_cache_preserves_order_and_separates_revision(self):
        with tempfile.TemporaryDirectory() as cache:
            predictor = Mock(side_effect=scores)
            classifier = FinBertSentiment(cache_dir=cache, batch_size=1, predictor=predictor)
            result = classifier.classify_many(["Selic cai", "Bolsa sobe", "Selic cai"])
            self.assertEqual(predictor.call_count, 2)
            self.assertEqual(result[0], result[2])
            self.assertEqual(result[0]["label"], "positive")
            self.assertEqual(classifier.classify_many(["Selic cai"])[0], result[0])
            self.assertEqual(predictor.call_count, 2)
            FinBertSentiment(cache_dir=cache, revision="outra-revisao", predictor=predictor)("Selic cai")
            self.assertEqual(predictor.call_count, 3)
            for file in classifier.cache_dir.glob("*.json"):
                self.assertNotIn("Selic cai", file.read_text())

    def test_bad_scores_and_text_do_not_become_neutral(self):
        with tempfile.TemporaryDirectory() as cache:
            classifier = FinBertSentiment(cache_dir=cache, predictor=lambda _: [{"positive": 2}])
            with self.assertRaises(ValueError):
                classifier("Notícia")
            with self.assertRaises(ValueError):
                classifier(" ")
            self.assertEqual(list(classifier.cache_dir.glob("*.json")), [])

    def test_sentiment_timestamps_do_not_rewrite_availability(self):
        with tempfile.TemporaryDirectory() as cache:
            classifier = FinBertSentiment(cache_dir=cache, predictor=scores)
            original = episode()
            row = enrich_news([original], classifier)[0]
            self.assertEqual(row["text"], original["text"])
            self.assertEqual(row["available_at"], original["available_at"])
            self.assertEqual(row["published_at"], original["published_at"])
            self.assertGreater(pd.Timestamp(row["classified_at"]), pd.Timestamp(original["classified_at"]))
            self.assertNotIn("sentiment", original)
            self.assertEqual(enrich_news([original], classifier)[0], row)
            with self.assertRaises(ValueError):
                validate_sentiment(row["sentiment"], "Outro texto")
            memory = NewsMemory(":memory:")
            try:
                memory.add(row)
                query = dict(retrospective=False)
                self.assertEqual(memory.retrieve(row["text"], "2020-01-10T00:00:00Z", **query)["n_events"], 0)
                retrieved = memory.retrieve(row["text"], "2020-01-02T00:00:00Z", retrospective=True)
                self.assertEqual(retrieved["memories"][0]["sentiment"], row["sentiment"])
                self.assertIsNone(retrieved["memories"][0]["outcome"])
                with self.assertRaises(ValueError):
                    memory.add({**row, "id": "bad", "classified_at": original["classified_at"]})
            finally:
                memory.close()

    def test_jev_receives_sentiment_and_chooses_action_independently(self):
        with tempfile.TemporaryDirectory() as cache:
            classifier = FinBertSentiment(cache_dir=cache, predictor=scores)
            text = "Banco Central eleva juros Selic"
            sentiment = classifier(text)
            memory = NewsMemory(":memory:")
            try:
                memory.add(enrich_news([episode()], classifier)[0])
                states = []
                def model(state):
                    states.append(state)
                    return {"action": "sell"}
                result = memory.predict(text, "2020-01-10T00:00:00Z", context={"data": {},
                                        "available_at": "2020-01-09T00:00:00Z"}, sentiment=sentiment,
                                        retrospective=True, decision_model=model)
                self.assertEqual(states[0]["current_sentiment"], sentiment)
                self.assertEqual(states[0]["memories"][0]["sentiment"]["label"], "positive")
                self.assertEqual(result["action"], "sell")
                self.assertEqual(result["action_pt"], "vender")
                self.assertEqual(result["prediction"], 0)
                excerpt = memory.predict(text, "2020-01-10T00:00:00Z", context={"data": {},
                                         "available_at": "2020-01-09T00:00:00Z"}, sentiment=sentiment,
                                         retrospective=True, max_text_chars=10, decision_model=model)
                self.assertEqual(excerpt["state"]["current_news"], text[:10])
                self.assertEqual(excerpt["state"]["current_sentiment"], sentiment)
                self.assertEqual(excerpt["state"]["current_news_original_length"], len(text))
                self.assertEqual(excerpt["state"]["memories"][0]["text"], text[:10])
                self.assertEqual(excerpt["memories"][0]["text"], text)
                future_model = Mock()
                with self.assertRaisesRegex(ValueError, "Sentimento atual"):
                    memory.predict(text, "2020-01-10T00:00:00Z", context={"data": {},
                                   "available_at": "2020-01-09T00:00:00Z"}, sentiment=sentiment,
                                   decision_model=future_model)
                future_model.assert_not_called()
                result = memory.predict(text, "2020-01-10T00:00:00Z", context={"data": {},
                                        "available_at": "2020-01-09T00:00:00Z"},
                                        decision_model=lambda _: {"action": "hold"}, retrospective=True)
                self.assertEqual(result["action"], "hold")
                self.assertIsNone(result["prediction"])
            finally:
                memory.close()

    def test_paired_finbert_evaluation_keeps_targets_out_and_reports_hold(self):
        data = prices()
        docs = [document(d.date().isoformat(), str(i)) for i, d in enumerate(data.index[30::3])]
        episodes, _ = prepare_episodes(docs, data)
        states = []
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as directory:
            classifier = FinBertSentiment(cache_dir=cache, predictor=scores)
            episodes = enrich_news(episodes, classifier)
            def model(state):
                states.append(state)
                self.assertIsNotNone(state["current_sentiment"])
                self.assertNotIn("outcome", state["current_context"]["data"])
                return {"action": "hold"}
            report = evaluate_news(episodes, model, directory=directory, sample_size=2)
            self.assertEqual(report["completed_pairs"], 2)
            self.assertEqual(report["metrics"]["with_memory"]["n_hold"], 2)
            self.assertIsNone(report["metrics"]["with_memory"]["accuracy_answered"])
            self.assertEqual(states[0]["current_sentiment"], states[1]["current_sentiment"])
            self.assertEqual(states[0]["memories"], [])
            self.assertTrue(states[1]["memories"])


if __name__ == "__main__":
    unittest.main()
