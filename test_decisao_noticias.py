"""Contrato da decisão Jev com respostas simuladas, sem consumo de API."""
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from ibov.decisao_noticias import JevMemoryModel


def response():
    return {"model": "jev-1.14.0", "answers": {
        "action": {"choice": "buy", "probabilities": {"buy": .7, "sell": .2, "hold": .1}},
        "basis": {"choice": "differences", "probabilities": {"context": .1, "analogies": .1,
                                                              "differences": .7, "insufficient": .1}}}}


class ContextModelTests(unittest.TestCase):
    def test_invalid_responses_explain_reason_without_caching(self):
        cases = [
            (lambda r: r.update(model="outro"), "modelo ou versão"),
            (lambda r: r["answers"].pop("action"), "estrutura incompleta"),
            (lambda r: r["answers"].update(action=None), "estrutura incompleta"),
            (lambda r: r["answers"]["action"].update(choice="up"), "action: classes"),
            (lambda r: r["answers"]["action"]["probabilities"].update(buy=2), "action: probabilidades fora"),
            (lambda r: r["answers"]["action"]["probabilities"].update(buy=.69), "action: probabilidades não somam"),
            (lambda r: r["answers"]["basis"].update(choice="context"), "basis: escolha diverge"),
        ]
        for change, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as cache, patch.dict(
                    "os.environ", {"TYPESAFE_API_KEY": "test-key"}):
                bad = response()
                change(bad)
                model = JevMemoryModel(cache_dir=cache)
                with patch("ibov.decisao_noticias.urlopen", return_value=io.BytesIO(json.dumps(bad).encode())):
                    with self.assertRaisesRegex(ValueError, reason):
                        model({"current_news": "texto sintético"})
                self.assertEqual(list(model.cache_dir.glob("*.json")), [])

    def test_old_direction_response_is_not_a_trading_action(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-key"}):
            old = response()
            old["answers"]["direction"] = old["answers"].pop("action")
            model = JevMemoryModel(cache_dir=cache)
            with patch("ibov.decisao_noticias.urlopen", return_value=io.BytesIO(json.dumps(old).encode())):
                with self.assertRaisesRegex(ValueError, "inválida"):
                    model({"current_news": "texto"})
            self.assertEqual(list(model.cache_dir.glob("*.json")), [])

    def test_context_sent_cache_budget_and_no_text_in_cache(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-key"}):
            model = JevMemoryModel(cache_dir=cache)
            with patch("ibov.decisao_noticias.urlopen", return_value=io.BytesIO(json.dumps(response()).encode())) as call:
                state = {"current_news": "texto atual", "current_context": {"juros": 10}, "memories": [{"outcome": 0}]}
                first = model(state)
                self.assertEqual(first["action"], "buy")
                self.assertEqual(model(state), first)
                self.assertEqual(call.call_count, 1)
                sent = json.loads(call.call_args.args[0].data)
                self.assertEqual(json.loads(sent["state"]), state)
                with self.assertRaisesRegex(ValueError, "Limite"):
                    model({"other": True})
                for file in model.cache_dir.glob("*.json"):
                    self.assertNotIn("test-key", file.read_text())
                    self.assertNotIn("texto atual", file.read_text())

    def test_invalid_response_not_cached(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-key"}):
            bad = response()
            bad["answers"]["action"]["probabilities"]["buy"] = 5
            model = JevMemoryModel(cache_dir=cache)
            with patch("ibov.decisao_noticias.urlopen", return_value=io.BytesIO(json.dumps(bad).encode())):
                with self.assertRaisesRegex(ValueError, "inválida"):
                    model({"context": "sintético"})
            self.assertEqual(list(model.cache_dir.glob("*")), [])

    def test_curl_credentials_not_in_process_arguments(self):
        from unittest.mock import Mock
        from pathlib import Path
        def run(args, **kwargs):
            self.assertNotIn('private-test-key', ' '.join(args))
            path = Path(args[args.index('--header')+1][1:])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('private-test-key', path.read_text())
            self.assertEqual(json.loads(kwargs['input'])['model'], 'jev-1.14.0')
            return Mock(returncode=0, stdout=json.dumps(response()).encode())
        with tempfile.TemporaryDirectory() as cache, patch.dict('os.environ', {'TYPESAFE_API_KEY': 'private-test-key'}):
            model = JevMemoryModel(cache_dir=cache, transport='curl')
            with patch('ibov.decisao_noticias.subprocess.run', side_effect=run):
                self.assertEqual(model({'context': 'teste'})['action'], 'buy')
