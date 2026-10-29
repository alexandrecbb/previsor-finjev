"""Regressões sem rede da coleta dos portais."""
import unittest
from coletar_portais_noticias import parse_article


class PortaisTests(unittest.TestCase):
    def page(self, published='2026-01-02T10:00:00-03:00'):
        import json
        data = {'@type': 'NewsArticle', 'headline': 'Teste', 'datePublished': published,
                'dateModified': '2026-01-03T12:00:00-03:00'}
        return '<script type="application/ld+json">' + json.dumps(data) + '</script><nav>Ruído</nav><article class="im-article"><p>' + ('Conteúdo econômico. ' * 30) + '</p></article><p>Rodapé</p>'

    def test_preserva_revisao_e_disponibilidade_real(self):
        row = parse_article(self.page(), 'https://exemplo.com/a', 'teste', '2026-10-28T12:00:00+00:00')
        self.assertEqual(row['historical_available_at'], '2026-01-03T15:00:00+00:00')
        self.assertEqual(row['available_at'], row['collected_at'])
        self.assertNotIn('Ruído', row['text'])
        self.assertNotIn('Rodapé', row['text'])

    def test_rejeita_fuso_ausente(self):
        with self.assertRaises(ValueError):
            parse_article(self.page('2026-01-02'), 'https://exemplo.com/a', 'teste', '2026-10-28')

    def test_rejeita_titulo_sem_texto(self):
        with self.assertRaises(ValueError):
            parse_article(self.page().replace('Conteúdo econômico. ' * 30, ''), 'https://exemplo.com/a', 'teste', '2026-10-28')

class ApiTests(unittest.TestCase):
    def test_paginacao_periodo_e_texto_protegido(self):
        import json
        import tempfile
        from pathlib import Path
        from coletar_portais_noticias import collect_wordpress
        from ibov.coleta_noticias import Archive
        def item(day, protected=False):
            return dict(link='https://www.moneytimes.com.br/' + day,
                        date_gmt=day+'T12:00:00', modified_gmt=day+'T13:00:00',
                        title={'rendered': 'Ibovespa'},
                        content={'rendered': '<p>' + 'Notícia. '*40 + '</p>', 'protected': protected})
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(directory)
            archive.fetch = lambda *a, **k: (json.dumps([item('2025-10-27'), item('2025-10-28'), item('2026-10-28'), item('2026-01-01', True)]).encode(), '2026-10-28T12:00:00+00:00')
            try:
                result = collect_wordpress('moneytimes', archive, '2025-10-28', '2026-10-28')
                self.assertTrue(result['complete'])
                self.assertEqual(result['saved'], 1)
                self.assertEqual(len(result['errors']), 1)
                self.assertEqual(archive.documents()[0]['publication_date'], '2025-10-28')
                self.assertTrue((Path(directory)/'moneytimes_collection.json').exists())
            finally:
                archive.close()

    def test_falha_na_pagina_seguinte_preserva_textos_e_incompletude(self):
        import json
        import tempfile
        from coletar_portais_noticias import collect_wordpress
        from ibov.coleta_noticias import Archive
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(directory)
            items = [dict(link=f'https://www.moneytimes.com.br/noticia-{i}',
                          date_gmt='2026-01-02T12:00:00', modified_gmt='2026-01-03T12:00:00',
                          title={'rendered': 'Ibovespa'}, content={'rendered': 'Notícia. '*40})
                     for i in range(100)]
            def fetch(url, **kwargs):
                if '&page=1&' in url:
                    return json.dumps(items).encode(), '2026-10-28T12:00:00+00:00'
                raise RuntimeError('HTTP 429 simulado')
            archive.fetch = fetch
            try:
                result = collect_wordpress('moneytimes', archive, '2025-10-28', '2026-10-28')
                self.assertFalse(result['complete'])
                self.assertEqual(result['saved'], 100)
                self.assertEqual(len(archive.documents()), 100)
                self.assertIn('429', result['errors'][0]['error'])
                collect_wordpress('moneytimes', archive, '2025-10-28', '2026-10-28')
                self.assertEqual(len(archive.documents()), 100)
            finally:
                archive.close()
