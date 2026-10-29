"""Regressões da descoberta GDELT e extração editorial sem rede."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from coletar_gdelt_noticias import collect, extract_article, parse_gkg
from ibov.coleta_noticias import Archive


class GdeltTests(unittest.TestCase):
    def archive(self, rows):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('gkg.csv', '\n'.join('\t'.join(row) for row in rows))
        return buffer.getvalue()

    def row(self, url, language='por', collection='1'):
        fields = [''] * 27
        fields[0:5] = ['20260102210000-T1', '20260102210000', collection, 'teste.com.br', url]
        fields[25] = 'srclc:' + language + ';eng:google;'
        return fields

    def page(self, **overrides):
        article = dict(headline='Ibovespa e juros', datePublished='2026-01-02T10:00:00-03:00',
                       dateModified='2026-01-03T12:00:00-03:00', **{'@type': 'NewsArticle'})
        article.update(overrides)
        return '<script type="application/ld+json">' + json.dumps(article) + '</script><nav>Ruído</nav><article><p>' + ('O mercado financeiro avaliou a inflação e os juros no Brasil. ' * 20) + '</p></article><footer>Rodapé</footer>'

    def test_filtra_metadados_sem_inventar_texto_publicacao(self):
        rows = [self.row('https://teste.com.br/ibovespa'),
                self.row('https://agenciabrasil.ebc.com.br/ibovespa'),
                self.row('https://teste.com.br/ibovespa', 'eng'),
                self.row('https://teste.com.br/ibovespa', collection='2'),
                self.row('https://teste.com.br/esporte')]
        count, candidates = parse_gkg(self.archive(rows), 'https://data.gdeltproject.org/a.zip')
        self.assertEqual(count, 5)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['gdelt_seen_at'], '2026-01-02T21:00:00+00:00')
        self.assertNotIn('publication_date', candidates[0])
        self.assertNotIn('text', candidates[0])

    def test_extrai_editorial_e_preserva_revisao(self):
        row = extract_article(self.page(), 'https://teste.com.br/ibovespa', '2026-10-28T12:00:00+00:00')
        self.assertNotIn('Ruído', row['text'])
        self.assertNotIn('Rodapé', row['text'])
        self.assertEqual(row['historical_available_at'], '2026-01-03T15:00:00+00:00')
        self.assertEqual(row['available_at'], row['collected_at'])

    def test_sem_fuso_usa_proxima_meia_noite(self):
        row = extract_article(self.page(datePublished='2026-01-02 10:00:00', dateModified=None), 'https://teste.com.br/ibovespa', '2026-10-28')
        self.assertIsNone(row['published_at'])
        self.assertEqual(row['historical_available_at'], '2026-01-03T03:00:00+00:00')

    def test_rejeita_resumo_sem_data_paywall_e_credito_ebc(self):
        pages = [self.page(datePublished=None), self.page(isAccessibleForFree=False),
                 self.page(articleBody='Um resumo curto.'),
                 self.page(author={'name': 'Agência Brasil'}), self.page(wordCount=5000)]
        for page in pages:
            with self.subTest(page=page[:70]), self.assertRaises(ValueError):
                extract_article(page, 'https://teste.com.br/ibovespa', '2026-10-28')

    def test_reutilizacao_nao_conta_como_texto_novo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = Archive(root / 'anterior')
            row = extract_article(self.page(), 'https://teste.com.br/ibovespa', '2026-10-28T12:00:00+00:00')
            previous.save(row)
            previous.close()
            archive = Archive(root / 'novo')
            archive.fetch = lambda *a, **k: self.fail('Não deve baixar matéria já conhecida.')
            discovery = dict(candidates={row['url']: [{'gdelt_seen_at': '2026-01-02T21:00:00+00:00'}]}, sampling_interval_days=7)
            try:
                result = collect(archive, discovery, '2025-10-28', '2026-10-28', root / 'anterior')
                self.assertEqual(result['saved'], 1)
                self.assertEqual(result['reused_existing'], 1)
                self.assertEqual(result['new_texts'], 0)
                self.assertFalse(result['exhaustive'])
                self.assertEqual(archive.documents()[0]['discovery_source'], 'gdelt_gkg')
            finally:
                archive.close()

    def test_rejeita_credito_abr_e_titulo_fora_do_tema(self):
        for page in (self.page(articleBody='O mercado avaliou a inflação. '*50 + '\nCom ABR'),
                     self.page(headline='Festival de música reúne artistas')):
            with self.assertRaises(ValueError):
                extract_article(page, 'https://teste.com.br/ibovespa', '2026-10-28')

    def test_comentarios_html_e_atributos_vazios(self):
        page = self.page().replace('<article>', '<article class><!-- comentário -->')
        row = extract_article(page, 'https://teste.com.br/ibovespa', '2026-10-28')
        self.assertGreater(len(row['text']), 600)
