"""Coleta retomável de notícias de mercado por APIs editoriais e sitemaps públicos."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlparse, urlencode

import pandas as pd
from ibov.coleta_noticias import Archive, EbcParser, html_text

FONTES = {
    'infomoney': 'https://www.infomoney.com.br/sitemap_index.xml',
    'moneytimes': 'https://www.moneytimes.com.br/sitemap_index.xml',
    'investing': 'https://br.investing.com/sitemap.xml',
    'advfn': 'https://br.advfn.com/common/sitemaps/sitemapIndex.xml',
}
TEMA = re.compile(r'ibovespa|copom|selic|ipca|inflacao|juros|petrobras|vale-|dolar|fiscal|commodit|federal-reserve')


class EditorialParser(HTMLParser):
    """Extrai parágrafos do contêiner editorial, sem usar a página inteira."""
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.paragraph = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.depth and ('im-article' in attrs.get('class', '').split() or attrs.get('itemprop') == 'articleBody'):
            self.depth = 1
        elif self.depth and tag not in ('br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'wbr'):
            self.depth += 1
        if self.depth and tag == 'p':
            self.paragraph = True
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'p':
            self.paragraph = False
        if self.depth and tag not in ('br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'wbr'):
            self.depth -= 1

    def handle_data(self, value):
        if self.depth and self.paragraph:
            self.parts.append(value)


def parse_article(html, url, source, collected):
    metadata = EbcParser()
    metadata.feed(html)
    nodes = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if 'NewsArticle' in str(value.get('@type', '')) or value.get('@type') == 'Article':
                nodes.append(value)
            if '@graph' in value:
                visit(value['@graph'])
    for script in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            visit(json.loads(script))
        except ValueError:
            continue
    node = nodes[0] if nodes else {}
    published = node.get('datePublished') or metadata.meta.get('article:published_time')
    modified = node.get('dateModified') or metadata.meta.get('article:modified_time')
    if not published:
        raise ValueError('Publicação ausente.')
    pub = pd.Timestamp(published)
    revision = pd.Timestamp(modified) if modified else pub
    if pub.tzinfo is None or revision.tzinfo is None:
        raise ValueError('Data sem fuso explícito.')
    parser = EditorialParser()
    parser.feed(html)
    text = html_text(node.get('articleBody', '')) or '\n'.join(' '.join(p.split()) for p in ''.join(parser.parts).splitlines() if p.strip())
    if len(text) < 200:
        raise ValueError('Corpo editorial ausente ou curto; não usar título como texto.')
    return dict(source=source, url=url, event_id=url, title=node.get('headline') or metadata.meta.get('og:title', ''),
                text=text, publication_date=pub.tz_convert('America/Sao_Paulo').date().isoformat(),
                published_at=pub.isoformat(), modified_at=modified, collected_at=collected,
                available_at=collected, historical_available_at=max(pub, revision).tz_convert('UTC').isoformat(),
                timestamp_quality='publisher_metadata', version_quality='current_page_unverified_original')


def collect(source, archive, start, end):
    result = dict(source=source, start=start, end_exclusive=end, discovered=0, saved=0, skipped=0, errors=[])
    domain = urlparse(FONTES[source]).netloc
    pending = [FONTES[source]]
    seen, urls = set(), set()
    while pending:
        page = pending.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            raw, _ = archive.fetch(page, delay=.5)
            root = ET.fromstring(raw)
            if root.tag.endswith('sitemapindex'):
                for item in root.findall('{*}sitemap'):
                    loc = item.findtext('{*}loc', '')
                    # O mês no nome é publicação; lastmod é revisão e não serve para excluir notícias.
                    month = re.search(r'(20\d{2}-\d{2})', loc)
                    if source == 'infomoney' and not re.search(r'msm-post-sitemap-20\d{2}-\d{2}\.xml$', loc):
                        continue
                    if urlparse(loc).netloc == domain and (not month or start[:7] <= month[1] <= end[:7]):
                        pending.append(loc)
            elif root.tag.endswith('urlset'):
                for item in root.findall('{*}url'):
                    loc = item.findtext('{*}loc', '')
                    if urlparse(loc).netloc == domain and TEMA.search(loc):
                        urls.add(loc)
            else:
                raise ValueError('Resposta não é sitemap XML.')
        except (RuntimeError, ValueError, ET.ParseError) as exc:
            result['errors'].append(dict(url=page, error=str(exc)[:300]))
    result['discovered'] = len(urls)
    manifest = archive.directory / (source + '_urls.json')
    manifest.write_text(json.dumps(sorted(urls), ensure_ascii=False, indent=2))
    existing = {r['url'] for r in archive.documents() if r['source'] == source and start <= r['publication_date'] < end}
    for i, url in enumerate(sorted(urls)):
        try:
            if url in existing:
                result['saved'] += 1
                continue
            raw, collected = archive.fetch(url, delay=1)
            row = parse_article(raw.decode('utf-8', errors='replace'), url, source, collected)
            if start <= row['publication_date'] < end:
                archive.save(row)
                result['saved'] += 1
            else:
                result['skipped'] += 1
        except (RuntimeError, ValueError) as exc:
            result['errors'].append(dict(url=url, error=str(exc)[:300]))
        if i % 50 == 0:
            print(source, i + 1, '/', len(urls), 'salvos', result['saved'], flush=True)
            (archive.directory / (source + '_collection.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (archive.directory / (source + '_collection.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(source, 'concluído', result['saved'], 'textos;', len(result['errors']), 'falhas', flush=True)
    return result


def collect_wordpress(source, archive, start, end, workers=1):
    """API pública WordPress: busca Ibovespa no conteúdo, com paginação auditada."""
    result = dict(source=source, start=start, end_exclusive=end, query='ibovespa',
                  saved=0, discovered=0, errors=[], complete=False, method='wordpress_rest')
    page = 1
    urls = []
    # A consulta histórica permanece fixa; no máximo quatro páginas em voo.
    after = (datetime.fromisoformat(start) - timedelta(seconds=1)).isoformat()
    base = 'https://' + urlparse(FONTES[source]).netloc
    def page_url(number):
        query = urlencode(dict(search='ibovespa', after=after, before=end+'T00:00:00',
                               per_page=100, page=number, order='asc', orderby='date'))
        return base + '/wp-json/wp/v2/posts?' + query
    def fetch_page(number):
        if workers == 1:
            return archive.fetch(page_url(number), delay=1)
        connection = Archive(archive.directory)
        try:
            return connection.fetch(page_url(number))
        finally:
            connection.close()
    pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    pending = {number: pool.submit(fetch_page, number) for number in range(1, workers + 1)} if pool else {}
    while True:
        url = page_url(page)
        try:
            raw, collected = pending.pop(page).result() if pool else fetch_page(page)
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError('API não retornou lista de matérias.')
            for item in items:
                result['discovered'] += 1
                urls.append(item['link'])
                text = html_text(item['content']['rendered'])
                if item['content'].get('protected') or len(text) < 200:
                    result['errors'].append(dict(url=item['link'], error='Corpo ausente, curto ou protegido.'))
                    continue
                pub = pd.Timestamp(item['date_gmt'] + '+00:00')
                modified = pd.Timestamp(item['modified_gmt'] + '+00:00')
                date = pub.tz_convert('America/Sao_Paulo').date().isoformat()
                if not start <= date < end:
                    continue
                archive.save(dict(source=source, url=item['link'], event_id=item['link'],
                    title=html_text(item['title']['rendered']), text=text, publication_date=date,
                    published_at=pub.isoformat(), modified_at=modified.isoformat(), available_at=collected,
                    collected_at=collected, historical_available_at=max(pub, modified).isoformat(),
                    timestamp_quality='publisher_metadata', version_quality='current_page_unverified_original'))
                result['saved'] += 1
            print(source, 'página', page, 'textos', result['saved'], flush=True)
            if len(items) < 100:
                result['complete'] = True
                break
            if pool:
                pending[page + workers] = pool.submit(fetch_page, page + workers)
            page += 1
        except (RuntimeError, ValueError, KeyError) as exc:
            result['errors'].append(dict(url=url, error=str(exc)[:300]))
            break
        finally:
            (archive.directory / (source + '_collection.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if pool:
        pool.shutdown(wait=True, cancel_futures=True)
    (archive.directory / (source + '_api_urls.json')).write_text(json.dumps(urls, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2025-10-28')
    parser.add_argument('--end', default='2026-10-28')
    parser.add_argument('--directory', default='dados_noticias/portais_12_meses')
    parser.add_argument('--source', choices=list(FONTES), required=True)
    args = parser.parse_args()
    if args.start >= args.end:
        parser.error('O início precisa anteceder o fim exclusivo.')
    archive = Archive(args.directory)
    try:
        if args.source in ('moneytimes', 'infomoney'):
            collect_wordpress(args.source, archive, args.start, args.end, workers=4)
        else:
            collect(args.source, archive, args.start, args.end)
    finally:
        archive.close()


if __name__ == '__main__':
    main()
