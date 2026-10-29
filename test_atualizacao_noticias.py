"""Atualização diária incremental com fontes simuladas, sem rede."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ibov.atualizacao_noticias import SOURCES, update_daily_news
from ibov.coleta_noticias import Archive
from ibov.memoria import NewsMemory
from ibov.sentimento import FinBertSentiment
from suporte_testes import FakeEmbeddings


def document(source, text=None):
    return dict(source=source, url="https://" + source + ".com/noticia", event_id=source,
                text=text or "Ibovespa e política monetária. " * 20,
                publication_date="2026-10-27", published_at="2026-10-27T12:00:00Z",
                historical_available_at="2026-10-27T12:00:00Z",
                available_at="2026-10-28T12:00:00Z", collected_at="2026-10-28T12:00:00Z")


class DailyNewsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.memory = NewsMemory(self.root / "memory.sqlite", encoder=FakeEmbeddings())
        self.addCleanup(self.memory.close)
        self.predictor = Mock(side_effect=lambda texts: [dict(positive=.8, negative=.1, neutral=.1) for _ in texts])
        self.classifier = FinBertSentiment(cache_dir=self.root / "cache", predictor=self.predictor)
        self.rows = {source: [document(source)] for source in SOURCES}
        self.calls = []
        def collect(source, archive, start, end):
            self.calls.append((source, str(archive.directory), start, end))
            for row in self.rows[source]:
                archive.save(row)
            return {"errors": [], "complete": True}
        self.collect = collect
        self.wp = patch("ibov.atualizacao_noticias.collect_wordpress", side_effect=collect).start()
        self.addCleanup(patch.stopall)
        patch.object(Archive, "collect_bcb", lambda archive, start, end: collect("bcb", archive, start, end)).start()

    def update(self, **kwargs):
        return update_daily_news(self.memory, directory=self.root / "daily", classifier=self.classifier,
                                 now="2026-10-28T18:00:00Z", **kwargs)

    def episodes(self):
        return [json.loads(r[0]) for r in self.memory.db.execute("SELECT payload FROM episodes ORDER BY id")]

    def test_three_sources_new_only_and_no_writes_when_unchanged(self):
        first = self.update()
        self.assertEqual(first["new_documents"], 3)
        self.assertEqual(first["new_episodes"], 3)
        self.assertEqual({row["source"] for row in self.episodes()}, set(SOURCES))
        before = (self.root / "memory.sqlite").read_bytes()
        archive_before = (self.root / "daily/fontes.sqlite").read_bytes()
        predictions = self.predictor.call_count
        second = self.update()
        self.assertEqual(second["status"], "no_new_news")
        self.assertEqual(second["new_documents"], 0)
        self.assertEqual(second["new_episodes"], 0)
        self.assertEqual((self.root / "memory.sqlite").read_bytes(), before)
        self.assertEqual((self.root / "daily/fontes.sqlite").read_bytes(), archive_before)
        self.assertEqual(self.predictor.call_count, predictions)
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(len({call[1] for call in self.calls}), 6)

    def test_empty_sources_do_not_classify_or_insert(self):
        self.rows = {source: [] for source in SOURCES}
        result = self.update()
        self.assertEqual(result["status"], "no_new_news")
        self.assertEqual(self.episodes(), [])
        self.predictor.assert_not_called()

    def test_news_already_in_memory_is_not_reimported_into_another_archive(self):
        self.update()
        before = (self.root / "memory.sqlite").read_bytes()
        calls = self.predictor.call_count
        result = update_daily_news(self.memory, directory=self.root / "another_archive",
                                   classifier=self.classifier, now="2026-10-28T18:00:00Z")
        self.assertEqual(result["new_documents"], 0)
        self.assertEqual(result["new_episodes"], 0)
        self.assertEqual(self.predictor.call_count, calls)
        self.assertEqual((self.root / "memory.sqlite").read_bytes(), before)

    def test_new_version_preserves_old_episode_and_unknown_outcome(self):
        self.update()
        original = self.episodes()
        self.rows["infomoney"] = [document("infomoney", "Texto revisado sobre o Ibovespa. " * 20)]
        result = self.update()
        self.assertEqual(result["new_documents"], 1)
        self.assertEqual(result["new_episodes"], 1)
        self.assertEqual(len(self.episodes()), 4)
        for old in original:
            self.assertIn(old, self.episodes())
        for row in self.episodes():
            self.assertIsNone(row["outcome"])
            self.assertIsNone(row["outcome_at"])
            self.assertEqual(row["available_at"], "2026-10-28T12:00:00+00:00")
        self.assertEqual(self.memory.retrieve("Ibovespa", "2026-10-27T18:00:00Z")["n_events"], 0)

    def test_source_failure_is_reported_and_other_sources_continue(self):
        self.wp.side_effect = lambda source, *args: (_ for _ in ()).throw(RuntimeError("fonte indisponível"))
        result = self.update()
        self.assertEqual(result["new_episodes"], 1)
        self.assertTrue(result["sources"]["infomoney"]["errors"])
        self.assertFalse(result["sources"]["infomoney"]["complete"])
        self.assertEqual(self.episodes()[0]["source"], "bcb")

    def test_all_sources_failed_is_not_reported_as_no_news(self):
        self.wp.side_effect = RuntimeError("indisponível")
        with patch.object(Archive, "collect_bcb", side_effect=RuntimeError("indisponível")):
            result = self.update()
        self.assertEqual(result["status"], "source_errors")
        self.predictor.assert_not_called()

    def test_failed_classification_can_resume_from_archive(self):
        self.predictor.side_effect = RuntimeError("modelo indisponível")
        with self.assertRaisesRegex(RuntimeError, "modelo indisponível"):
            self.update()
        self.assertEqual(self.episodes(), [])
        self.rows = {source: [] for source in SOURCES}
        self.predictor.side_effect = lambda texts: [dict(positive=.8, negative=.1, neutral=.1) for _ in texts]
        result = self.update()
        self.assertEqual(result["new_documents"], 0)
        self.assertEqual(result["new_episodes"], 3)

    def test_overlap_catches_up_after_days_without_running(self):
        self.update()
        update_daily_news(self.memory, directory=self.root / "daily", classifier=self.classifier,
                          now="2026-11-10T18:00:00Z")
        for source, folder, start, end in self.calls[3:]:
            self.assertEqual(start, "2026-10-25")
            self.assertEqual(end, "2026-11-11")
