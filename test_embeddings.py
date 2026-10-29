"""Cache semântico e ranking temporal com vetores controlados, sem rede."""
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ibov.embeddings import SemanticEmbeddings
from ibov.memoria import NewsMemory
from test_memoria import episode
from suporte_testes import FakeEmbeddings


class EmbeddingTests(unittest.TestCase):
    def test_cache_deduplicates_normalizes_and_restarts_without_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            encoder = SemanticEmbeddings(cache_dir=folder)
            vectors = np.zeros((2, 384), dtype=np.float32)
            vectors[0, 0], vectors[1, 1] = 3., 4.
            vectors[0, :3] = [1., 2., 3.]
            with patch.object(encoder, "_infer", return_value=vectors) as infer:
                actual = encoder.encode(["Selic recua", "Bolsa sobe", "Selic recua"])
            self.assertEqual(infer.call_count, 1)
            self.assertEqual(len(infer.call_args.args[0]), 2)
            np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1.)
            np.testing.assert_array_equal(actual[0], actual[2])
            restarted = SemanticEmbeddings(cache_dir=folder)
            with patch.object(restarted, "_infer", side_effect=AssertionError("Rede/inferência duplicada")):
                np.testing.assert_array_equal(restarted.encode(["Selic recua"])[0], actual[0])
            for path in encoder.cache_dir.glob("*.json"):
                self.assertNotIn("Selic recua", path.read_text())
            encoder.metadata = {**encoder.metadata, "revision": "outra-revisao"}
            with patch.object(encoder, "_infer", return_value=vectors[:1]) as infer:
                encoder.encode(["Selic recua"])
            infer.assert_called_once()

    def test_invalid_vectors_are_not_cached(self):
        for value in (np.zeros((1, 384)), np.full((1, 384), np.nan), np.ones((1, 2))):
            with tempfile.TemporaryDirectory() as folder:
                encoder = SemanticEmbeddings(cache_dir=folder)
                with patch.object(encoder, "_infer", return_value=value), self.assertRaises(ValueError):
                    encoder.encode(["Texto"])
                self.assertEqual(list(encoder.cache_dir.glob("*.json")), [])

    def test_semantic_paraphrase_wins_and_future_documents_are_not_encoded(self):
        # Os vetores simulam um encoder que aproxima paráfrases mesmo sem
        # palavras compartilhadas. Não são evidência de qualidade do modelo real.
        encoder = FakeEmbeddings()
        seen = []
        def encode(texts):
            seen.extend(texts)
            matrix = np.zeros((len(texts), 384))
            for i, text in enumerate(texts):
                matrix[i, 0 if text in ("Selic recua", "Autoridade monetária reduz juros") else 1] = 1
            return matrix
        encoder.encode = encode
        memory = NewsMemory(":memory:", encoder=encoder)
        try:
            memory.add(episode(id="semantic", event_id="semantic", text="Autoridade monetária reduz juros"))
            memory.add(episode(id="irrelevant", event_id="irrelevant", text="Selic aparece em reportagem sobre futebol"))
            memory.add(episode(id="future", event_id="future", text="Texto futuro oculto",
                               published_at="2030-01-01T00:00:00Z", available_at="2030-01-01T00:00:00Z",
                               outcome=None, outcome_at=None))
            result = memory.retrieve("Selic recua", "2020-01-03T00:00:00Z", top_k=1)
            self.assertEqual(result["memories"][0]["id"], "semantic")
            self.assertIsNone(result["memories"][0]["outcome"])
            self.assertNotIn("Texto futuro oculto", seen)
            self.assertEqual(result["retrieval_config"]["version"], "semantic_cosine_recency_importance_v2_layered")
        finally:
            memory.close()

    def test_recency_importance_and_temporal_maturity_still_apply(self):
        memory = NewsMemory(":memory:", encoder=FakeEmbeddings())
        try:
            memory.add(episode(id="older", event_id="older", text="Episódio antigo", importance=0))
            memory.add(episode(id="recent", event_id="recent", text="Episódio recente", importance=100,
                               published_at="2020-01-02T12:00:00Z", available_at="2020-01-02T12:01:00Z",
                               classified_at="2020-01-02T12:02:00Z"))
            result = memory.retrieve("Consulta", "2020-01-03T00:00:00Z")
            self.assertEqual(result["memories"][0]["id"], "recent")
            self.assertEqual(result["n_events"], 1)
            self.assertTrue(memory.memory_state("older", "2020-01-03T00:00:00Z")["deleted"])
            self.assertTrue(all(row["outcome"] is None for row in result["memories"]))
        finally:
            memory.close()
