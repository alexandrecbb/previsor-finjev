"""Coletores e avaliação com dados sintéticos e transportes simulados."""
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from ibov.coleta_noticias import Archive, next_midnight, parse_ebc
from ibov.avaliacao_noticias import prepare_episodes, sample_episodes, market_context, metrics, evaluate_news


from unittest.mock import patch as patch_embeddings
from suporte_testes import FakeEmbeddings

_embedding_patch = patch_embeddings("ibov.memoria.SemanticEmbeddings", FakeEmbeddings)


def setUpModule():
    _embedding_patch.start()


def tearDownModule():
    _embedding_patch.stop()


def prices():
    index = pd.bdate_range('2017-01-01', periods=800)
    return pd.DataFrame({'close': [100 + i % 13 for i in range(len(index))]}, index=index)


def document(date, id_='d'):
    return {'id': id_, 'event_id': id_, 'source': 'bcb', 'url': 'https://example.com/'+id_,
            'text': 'Banco Central decide juros e inflação na reunião de política monetária.',
            'published_at': date+'T18:00:00-03:00', 'historical_available_at': date+'T19:00:00-03:00',
            'collected_at': '2026-10-28T12:00:00Z'}


class HistoricalTests(unittest.TestCase):
    def test_date_only_is_next_local_midnight(self):
        self.assertEqual(next_midnight('2020-01-08'), '2020-01-09T03:00:00+00:00')
        # Horário de verão histórico é respeitado.
        self.assertEqual(next_midnight('2018-01-08'), '2018-01-09T02:00:00+00:00')

    def test_article_body_and_update_timestamp(self):
        html = '''<meta property="article:published_time" content="2020-01-01T12:00:00-03:00">
        <meta property="article:modified_time" content="2020-01-02T12:00:00-03:00">
        <div>Texto externo</div><div class="field field-name-body"><div><p>''' + 'Conteúdo editorial. '*20 + '</p></div></div><p>Rodapé</p>'
        row = parse_ebc(html, 'https://example.com', '2026-10-28T12:00:00Z')
        self.assertNotIn('Texto externo', row['text'])
        self.assertNotIn('Rodapé', row['text'])
        self.assertEqual(row['historical_available_at'], '2020-01-02T15:00:00+00:00')
        with self.assertRaises(ValueError):
            parse_ebc('<title>Só título</title>', 'https://example.com', '2026-10-28T12:00:00Z')

    def test_targets_in_trading_records_and_causal_context(self):
        data = prices()
        doc = document('2017-02-03')
        episodes, excluded = prepare_episodes([doc], data)
        self.assertFalse(excluded)
        row = episodes[0]
        pos = row['base_position']
        self.assertEqual(row['query_context']['data']['base_date'], '2017-02-03')
        self.assertEqual(row['outcome'], int(data.close.iloc[pos+3] > data.close.iloc[pos]))
        changed = data.copy()
        changed.iloc[pos+1:, 0] *= 10
        self.assertEqual(row['query_context'], prepare_episodes([doc], changed)[0][0]['query_context'])
        self.assertEqual(market_context(data, '2017-02-04T12:00:00Z')['data']['base_date'], '2017-02-03')
        tail = document(data.index[-1].date().isoformat(), 'tail')
        self.assertIsNone(prepare_episodes([tail], data)[0][0]['outcome'])

    def test_nonoverlapping_selection_does_not_use_outcomes(self):
        data = prices()
        docs = [document(d.date().isoformat(), str(i)) for i, d in enumerate(data.index[30::4])]
        episodes, _ = prepare_episodes(docs, data)
        selected = sample_episodes(episodes)
        for a,b in zip(selected, selected[1:]):
            self.assertGreater(b['base_position'], a['base_position']+3)
        before = [r['id'] for r in selected]
        for row in episodes:
            if row['outcome'] is not None:
                row['outcome'] = 1-row['outcome']
        self.assertEqual(before, [r['id'] for r in sample_episodes(episodes)])

    def test_metrics_preserve_abstentions(self):
        result = metrics([{'prediction':1,'outcome':1}, {'prediction':None,'outcome':0}])
        self.assertEqual(result['accuracy_answered'], 1)
        self.assertEqual(result['coverage'], .5)
        self.assertEqual(result['correct_over_all'], .5)

    def test_short_corpus_requires_explicit_warmup(self):
        data = prices().iloc[:180]
        docs = [document(d.date().isoformat(), str(i)) for i, d in enumerate(data.index[30::4])]
        episodes, _ = prepare_episodes(docs, data)
        self.assertEqual(sample_episodes(episodes), [])
        selected = sample_episodes(episodes, size=8, warmup_days=90)
        self.assertTrue(selected)
        start = pd.Timestamp(episodes[0]['available_at']) + pd.Timedelta(days=90)
        self.assertTrue(all(pd.Timestamp(r['cutoff']) >= start for r in selected))
        for a, b in zip(selected, selected[1:]):
            self.assertGreater(b['base_position'], a['base_position'] + 3)
        with self.assertRaises(ValueError):
            sample_episodes(episodes, warmup_days=-1)

    def test_paired_evaluation_sends_no_target_and_restarts_without_calls(self):
        data = prices()
        docs = [document(d.date().isoformat(), str(i)) for i,d in enumerate(data.index[30::3])]
        episodes, _ = prepare_episodes(docs, data)
        states = []
        def model(state):
            states.append(state)
            self.assertNotIn('outcome', state['current_context']['data'])
            return {'direction': 'up'}
        with tempfile.TemporaryDirectory() as directory:
            report = evaluate_news(episodes, model, directory=directory, sample_size=2)
            self.assertEqual(report['completed_pairs'], 2)
            self.assertEqual(len(states), 4)
            self.assertEqual(states[0]['memories'], [])
            self.assertTrue(states[1]['memories'])
            self.assertEqual(states[0]['current_context'], states[1]['current_context'])
            again = evaluate_news(episodes, lambda _: self.fail('Chamada duplicada'), directory=directory, sample_size=2)
            self.assertEqual(again['results'], report['results'])

    def test_network_failure_is_recorded_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(directory)
            try:
                with patch('ibov.coleta_noticias.subprocess.run') as run:
                    run.return_value.returncode = 22
                    run.return_value.stderr = b'HTTP 429'
                    result = archive.probe_gdelt('2016-10-28', '2026-10-28')
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(archive.documents(), [])
            finally:
                archive.close()

    def test_copom_null_html_uses_pdf_without_inventing_time(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(directory)
            def fetch(url, delay=0):
                now = '2026-10-28T12:00:00Z'
                if '/comunicados?' in url:
                    return b'{"conteudo": []}', now
                if '/atas?' in url:
                    return json.dumps({'conteudo': [{'nroReuniao': 203, 'dataReferencia': '2016-11-30',
                                                      'dataPublicacao': '2016-12-06'}]}).encode(), now
                if '/atas_detalhes?' in url:
                    return json.dumps({'conteudo': [{'textoAta': None, 'urlPdfAta': 'https://www.bcb.gov.br/a.pdf'}]}).encode(), now
                return b'PDF simulado', now
            try:
                with patch.object(archive, 'fetch', side_effect=fetch), patch('ibov.coleta_noticias.PdfReader') as reader:
                    reader.return_value.pages = [Mock(extract_text=lambda: 'Ata de política monetária. '*20)]
                    result = archive.collect_bcb('2016-10-28', '2026-10-28')
                self.assertEqual(result['saved'], 1)
                row = archive.documents()[0]
                self.assertEqual(row['text_format'], 'pdf')
                self.assertIsNone(row['published_at'])
                self.assertEqual(row['historical_available_at'], next_midnight('2016-12-06'))
            finally:
                archive.close()

    def test_midnight_on_historical_daylight_saving_transitions(self):
        self.assertEqual(next_midnight('2018-11-03'), '2018-11-04T03:00:00+00:00')
        self.assertEqual(next_midnight('2019-02-16'), '2019-02-17T03:00:00+00:00')
        data = prices()
        episode = prepare_episodes([document('2019-02-16')], data)[0][0]
        self.assertEqual(episode['cutoff'], '2019-02-17T03:00:00+00:00')
