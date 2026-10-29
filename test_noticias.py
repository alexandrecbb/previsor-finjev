"""Testes de notícias e API sem rede e sem credenciais reais."""
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import pandas as pd

from ibov import noticias


def source():
    return pd.DataFrame([dict(id="1", text="Texto econômico sintético.",
                             published_at="2026-10-20T15:00:00-03:00",
                             available_at="2026-10-20T15:10:00-03:00")])


def response():
    return {"model": "jev-1.14.0", "answers": {
        "sentiment": {"probabilities": {"positive": 0.6, "negative": 0.1, "neutral": 0.3}},
        **{k: {"noul": 0.4} for k in noticias.VALUES[3:]}}}


def classified():
    return source().assign(positive=0.6, negative=0.1, neutral=0.3,
                           interest=0.4, inflation=0.2, fiscal=0.1,
                           classified_at="2026-10-22T10:00:00-03:00",
                           model="jev-1.14.0", prompt_version=noticias.PROMPT_VERSION)


class NewsTests(unittest.TestCase):
    def test_request_cache_and_no_secret(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-secret"}):
            with patch.object(noticias, "urlopen", return_value=io.BytesIO(json.dumps(response()).encode())) as call:
                actual = noticias.classify_news(source(), cache_dir=cache)
                again = noticias.classify_news(source(), cache_dir=cache)
                self.assertEqual(call.call_count, 1)
                request = call.call_args.args[0]
                self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
                self.assertEqual(json.loads(request.data)["state"], source().iloc[0]["text"])
                pd.testing.assert_frame_equal(actual, again)
                for file in noticias.Path(cache).glob("*"):
                    self.assertNotIn("test-secret", file.read_text())
                    self.assertNotIn("Texto econômico", file.read_text())

    def test_error_does_not_leak_response_or_key(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-secret"}):
            error = HTTPError(noticias.ENDPOINT, 401, "test-secret", {}, None)
            with patch.object(noticias, "urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
                    noticias.classify_news(source(), cache_dir=cache)
                self.assertNotIn("test-secret", str(caught.exception))

    def test_invalid_probability_and_request_budget(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-secret"}):
            with patch.object(noticias, "urlopen") as call:
                with self.assertRaisesRegex(ValueError, "Limite"):
                    noticias.classify_news(source(), cache_dir=cache, max_requests=0)
                call.assert_not_called()
            bad = response()
            bad["answers"]["sentiment"]["probabilities"]["positive"] = 2
            with patch.object(noticias, "urlopen", return_value=io.BytesIO(json.dumps(bad).encode())):
                with self.assertRaisesRegex(ValueError, "Resposta"):
                    noticias.classify_news(source(), cache_dir=cache)
            self.assertEqual(list(noticias.Path(cache).glob("*.json")), [])

    def test_timestamp_availability_and_expiration(self):
        dates = pd.date_range("2026-10-20", "2026-10-29")
        data = classified()
        actual = noticias.news_features(dates, data)
        self.assertEqual(actual.loc["2026-10-22", "news_count_7d"], 0)
        self.assertEqual(actual.loc["2026-10-23", "news_count_7d"], 1)
        self.assertEqual(actual.loc["2026-10-28", "news_count_7d"], 0)
        retro = noticias.news_features(dates, data, retrospective=True)
        self.assertEqual(retro.loc["2026-10-20", "news_count_7d"], 0)
        self.assertEqual(retro.loc["2026-10-21", "news_count_7d"], 1)
        changed = data.copy()
        changed["positive"], changed["negative"] = 0.1, 0.6
        pd.testing.assert_frame_equal(actual.iloc[:3], noticias.news_features(dates, changed).iloc[:3])
        data["published_at"] = "2026-10-20"
        with self.assertRaisesRegex(ValueError, "fuso"):
            noticias.news_features(dates, data)

    def test_comparison_uses_news_only_in_requested_variant(self):
        from avaliar_configuracoes import prepare_datasets
        from test_previsor import historical_data
        raw = historical_data()
        data = classified()
        for field in ["published_at", "available_at", "classified_at"]:
            data[field] = raw.index[100].tz_localize("America/Sao_Paulo").isoformat()
        frames = prepare_datasets(raw, None, {"base": {}, "jev": {"news": True}}, news_data=data)
        self.assertNotIn("news_count_7d", frames["base"])
        self.assertGreater(frames["jev"]["news_count_7d"].sum(), 0)
        pd.testing.assert_index_equal(frames["base"].index, frames["jev"].index)
        with self.assertRaisesRegex(ValueError, "news_data"):
            prepare_datasets(raw, None, {"jev": {"news": True}})

    def test_pipeline_with_news_preserves_return(self):
        from test_previsor import historical_data
        from ibov import run_ibov_pipeline
        from contextlib import redirect_stdout
        raw = historical_data()
        data = classified()
        date = raw.index[0].tz_localize("America/Sao_Paulo")
        for field in ["published_at", "available_at", "classified_at"]:
            data[field] = date.isoformat()
        with redirect_stdout(io.StringIO()):
            metrics, prediction, probability = run_ibov_pipeline(
                raw_data=raw, news_data=data, n_iter=1, n_jobs=1, show_plots=False)
        self.assertIn("accuracy", metrics)
        self.assertEqual(prediction.shape, (1,))
        self.assertEqual(probability.shape, (1, 2))


if __name__ == "__main__":
    unittest.main()
