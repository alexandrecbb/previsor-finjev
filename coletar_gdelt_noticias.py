"""Recupera corpos editoriais a partir de uma amostra histórica auditável do GDELT."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import io
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlparse, unquote
from urllib.robotparser import RobotFileParser
import zipfile

import pandas as pd
from ibov.coleta_noticias import Archive, html_text, next_midnight

TOPICS = re.compile(r'ibovespa|bovespa|copom|selic|inflacao|ipca|petrobras|vale3|petr4|(?:^|[-/])juros|dolar|bolsa-de-valores|mercado-financeiro|politica-monetaria')
EXCLUDED = ('agenciabrasil.ebc.com.br',)


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs = dict(attrs)
            self.meta[attrs.get('property') or attrs.get('name') or ''] = attrs.get('content') or ''


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', unquote(value).lower()) if not unicodedata.combining(c))


def validate_scope(row):
    title = normalized(row['title'])
    if not re.search(r'ibovespa|bovespa|copom|selic|ipca|petrobras|\bvale\b|dolar|inflacao|juros|bolsa|banco central|federal reserve|\bfed\b|\bpib\b|fiscal|petroleo|commodit|mercado financeiro|economi|credito|safra|exporta|importa|tarifa|balanco|acoes|investimento', title):
        raise ValueError('Título sem tema econômico identificado; candidato não incluído no corpus.')
    text = normalized(row['text'])
    if 'agencia brasil' in text or 'agenciabrasil.ebc.com.br' in text or re.search(r'\b(?:com|fonte:?|da|por)\s+abr\b', text):
        raise ValueError('Agência Brasil excluída do escopo, inclusive crédito ABR.')


def permitted_source(url):
    host = (urlparse(url).hostname or '').lower()
    return bool(host) and not any(host == h or host.endswith('.' + h) for h in EXCLUDED)


def parse_gkg(data, archive_url):
    """O horário GKG é observação do índice e nunca substitui a publicação."""
    rows, count = [], 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            with z.open(name) as stream:
                for line in stream:
                    fields = line.decode('utf-8', errors='replace').rstrip('\r\n').split('\t')
                    count += 1
                    if len(fields) < 27 or fields[2] != '1' or 'srclc:por' not in fields[25]:
                        continue
                    url = fields[4].replace('http://', 'https://', 1)
                    financial_theme = bool(set(fields[7].split(';')).intersection(('ECON_STOCKMARKET', 'ECON_INFLATION', 'ECON_INTEREST_RATES', 'ECON_CURRENCY_EXCHANGE_RATE')))
                    if not permitted_source(url) or not (TOPICS.search(normalized(url)) or financial_theme):
                        continue
                    rows.append(dict(url=url, publisher=fields[3], gdelt_id=fields[0],
                                     gdelt_seen_at=datetime.strptime(fields[1], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).isoformat(),
                                     gdelt_archive=archive_url, language='por', themes=fields[7]))
    return count, rows


def extract_article(html, url, collected):
    """Só aceita corpo editorial; não preenche texto a partir de título ou resumo."""
    from lxml import html as lxml_html
    meta = MetadataParser()
    meta.feed(html)
    articles = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kinds = value.get('@type', [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if set(kinds).intersection(('NewsArticle', 'Article', 'ReportageNewsArticle', 'AnalysisNewsArticle')):
                articles.append(value)
            if '@graph' in value:
                visit(value['@graph'])
    for script in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            visit(json.loads(script))
        except ValueError:
            continue
    article = articles[0] if articles else {}
    # Datas heurísticas extraídas da URL ou do rodapé não são usadas como publicação.
    published = article.get('datePublished') or meta.meta.get('article:published_time') or meta.meta.get('datePublished')
    modified = article.get('dateModified') or meta.meta.get('article:modified_time')
    if not published:
        raise ValueError('Publicação explícita ausente; observação GDELT não é publicação.')
    pub = pd.Timestamp(published)
    date_only = pub.tzinfo is None
    if date_only:
        date = pub.date().isoformat()
        historical = next_midnight(date)
        published_at = None
    else:
        date = pub.tz_convert('America/Sao_Paulo').date().isoformat()
        historical, published_at = pub.tz_convert('UTC').isoformat(), pub.isoformat()
    if modified:
        revision = pd.Timestamp(modified)
        revision_time = next_midnight(revision.date().isoformat()) if revision.tzinfo is None else revision.tz_convert('UTC').isoformat()
        historical = max(pd.Timestamp(historical), pd.Timestamp(revision_time)).isoformat()
    # Recusa páginas que declaram restrição; não aceita um teaser como texto integral.
    if article.get('isAccessibleForFree') in (False, 'False', 'false'):
        raise ValueError('Página declara conteúdo restrito.')
    text = html_text(article.get('articleBody', ''))
    if not text:
        tree = lxml_html.fromstring(html)
        for unwanted in tree.xpath('//script|//style|//nav|//footer|//aside|//form'):
            unwanted.drop_tree()
        containers = tree.xpath('//*[@itemprop="articleBody"]')
        if not containers:
            tokens = ('entry-content', 'article-content', 'post-content', 'td-post-content',
                      'materia-conteudo', 'corpo-noticia', '_noticiaMateria', 'article-body', 'news-content')
            containers = tree.xpath('//*[' + ' or '.join('contains(@class, "' + token + '") or @id="' + token + '"' for token in tokens) + ']')
        if not containers:
            containers = tree.xpath('//article')
        if not containers:
            raise ValueError('Contêiner editorial não identificado; não usar texto da página inteira.')
        container = max(containers, key=lambda element: len(element.text_content()))
        for element in list(container.iterdescendants()):
            if not isinstance(element.tag, str):
                continue
            classes = (element.get('class') or '').lower()
            if any(token in classes for token in ('newsletter', 'advert', 'relacionad', 'coment', 'social', 'compartilh', 'related', 'maislidas')):
                if element.getparent() is not None:
                    element.drop_tree()
        paragraphs = container.xpath('.//p')
        text = '\n'.join(' '.join(element.text_content().split()) for element in paragraphs if element.text_content().strip())
        if not text:
            text = html_text(lxml_html.tostring(container, encoding='unicode'))
    if len(text) < 600 or len(text.split()) < 90:
        raise ValueError('Texto editorial curto ou ausente; não contabilizado como corpo recuperado.')
    word_count = article.get('wordCount')
    if word_count and str(word_count).isdigit() and len(text.split()) < int(word_count) * .8:
        raise ValueError('Texto significativamente menor que wordCount declarado; possível trecho incompleto.')
    credits = normalized(json.dumps(article.get('author', []), ensure_ascii=False) + '\n' + text)
    if 'agencia brasil' in credits or 'agenciabrasil.ebc.com.br' in credits or re.search(r'\babr\b', normalized(json.dumps(article.get('author', [])))):
        raise ValueError('Agência Brasil excluída do escopo, inclusive crédito no conteúdo.')
    title = html_text(article.get('headline', '') or meta.meta.get('og:title', ''))
    if not title:
        raise ValueError('Título editorial ausente.')
    row = dict(source=urlparse(url).netloc.removeprefix('www.'), url=url, event_id=url,
                title=title, text=text, publication_date=date, published_at=published_at,
                modified_at=modified, available_at=collected, collected_at=collected,
                historical_available_at=historical,
                timestamp_quality='date_only_next_midnight' if date_only else 'publisher_metadata',
                version_quality='current_page_unverified_original', text_completeness='automated_body_not_manually_verified')
    validate_scope(row)
    return row


def discover(archive, start, end, interval_days=7, hour=21):
    dates = []
    day, stop = datetime.fromisoformat(start), datetime.fromisoformat(end)
    while day < stop:
        dates.append(day.strftime('%Y%m%d') + f'{hour:02d}0000')
        day += timedelta(days=interval_days)
    urls = ['https://data.gdeltproject.org/gdeltv2/' + date + '.translation.gkg.csv.zip' for date in dates]
    result = dict(start=start, end_exclusive=end, sampling_interval_days=interval_days, sample_hour_utc=hour,
                  files_requested=len(urls), files_read=0, metadata_processed=0, candidates={}, errors=[])
    def fetch(url):
        connection = Archive(archive.directory)
        try:
            raw, collected = connection.fetch(url)
            count, rows = parse_gkg(raw, url)
            return url, count, rows, None
        except (RuntimeError, ValueError, zipfile.BadZipFile) as exc:
            return url, 0, [], str(exc)[:300]
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (url, count, rows, error) in enumerate(pool.map(fetch, urls), 1):
            if error:
                result['errors'].append(dict(url=url, error=error))
            else:
                result['files_read'] += 1
                result['metadata_processed'] += count
                for row in rows:
                    result['candidates'].setdefault(row['url'], []).append(row)
            print('GKG', i, '/', len(urls), 'URLs candidatas', len(result['candidates']), flush=True)
    (archive.directory / 'gdelt_discovery.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def collect(archive, discovery, start, end, existing_directory):
    existing = {}
    path = Path(existing_directory) / 'fontes.sqlite'
    if path.exists():
        db = sqlite3.connect(path)
        for (payload,) in db.execute('SELECT payload FROM documents'):
            row = json.loads(payload)
            if row['url'] not in existing or row['collected_at'] > existing[row['url']]['collected_at']:
                existing[row['url']] = row
        db.close()
    result = dict(start=start, end_exclusive=end, candidates=len(discovery['candidates']),
                  saved=0, reused_existing=0, new_texts=0, errors=[], excluded_outside_period=0,
                  sampling_interval_days=discovery['sampling_interval_days'], exhaustive=False)
    groups = defaultdict(list)
    for url, provenance in discovery['candidates'].items():
        groups[urlparse(url).netloc].append((url, provenance))

    def recover_group(host, entries):
        connection = Archive(archive.directory)
        recovered = []
        robot = None
        robot_checked = False
        suspended = None
        network_failures = 0
        try:
            for url, provenance in entries:
                try:
                    if url in existing:
                        row = dict(existing[url])
                        if 'agencia brasil' in normalized(row['text']):
                            raise ValueError('Agência Brasil excluída do escopo.')
                        reused = True
                    else:
                        if suspended:
                            raise ValueError('Acesso suspenso neste domínio: ' + suspended)
                        if not robot_checked:
                            try:
                                data, _ = connection.fetch('https://' + host + '/robots.txt', delay=1)
                                if b'<html' in data.lower():
                                    raise ValueError('robots retornou HTML; acesso não confirmado.')
                                robot = RobotFileParser()
                                robot.parse(data.decode(errors='replace').replace('\\r\\n', '\n').splitlines())
                                robot_checked = True
                            except (RuntimeError, ValueError) as exc:
                                if '404' in str(exc):
                                    robot_checked = True
                                else:
                                    suspended = str(exc)[:300]
                                    raise
                        if robot is not None and not robot.can_fetch('IbovResearch', url):
                            raise ValueError('Acesso vedado por robots.txt.')
                        delay = max(1, (robot.crawl_delay('IbovResearch') or robot.crawl_delay('*') or 0) if robot else 0)
                        raw, collected = connection.fetch(url, delay=delay)
                        row = extract_article(raw.decode('utf-8', errors='replace'), url, collected)
                        reused = False
                    validate_scope(row)
                    if not start <= row['publication_date'] < end:
                        recovered.append(('outside', url))
                        continue
                    row.update(discovery_source='gdelt_gkg', gdelt_provenance=provenance)
                    recovered.append(('reused' if reused else 'new', row))
                except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, RuntimeError):
                        network_failures += 1
                        if '429' in str(exc) or '403' in str(exc) or network_failures >= 2:
                            suspended = str(exc)[:300]
                    recovered.append(('error', dict(url=url, error=str(exc)[:300])))
        finally:
            connection.close()
        return recovered

    processed = 0
    accepted_urls = set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(recover_group, host, entries) for host, entries in sorted(groups.items())]
        for future in as_completed(futures):
            for status, value in future.result():
                processed += 1
                if status == 'error':
                    result['errors'].append(value)
                elif status == 'outside':
                    result['excluded_outside_period'] += 1
                else:
                    archive.save(value)
                    accepted_urls.add(value['url'])
                    result['saved'] += 1
                    result['reused_existing' if status == 'reused' else 'new_texts'] += 1
            print('Textos', processed, '/', result['candidates'], 'salvos', result['saved'], 'novos', result['new_texts'], flush=True)
            (archive.directory / 'gdelt_collection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (archive.directory / 'gdelt_collection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    latest = {}
    for row in archive.documents():
        if row['url'] in accepted_urls and start <= row['publication_date'] < end:
            if row['url'] not in latest or row['collected_at'] > latest[row['url']]['collected_at']:
                latest[row['url']] = row
    rows = sorted(latest.values(), key=lambda r: (r['publication_date'], r['url']))
    snapshot = archive.directory / 'noticias_gdelt.jsonl'
    snapshot.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    result['candidate_processing_finished'] = True
    result['snapshot_documents'] = len(rows)
    result['snapshot_sha256'] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    (archive.directory / 'gdelt_collection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2025-10-28')
    parser.add_argument('--end', default='2026-10-28')
    parser.add_argument('--interval-days', type=int, default=7)
    parser.add_argument('--hour', type=int, default=21)
    parser.add_argument('--directory', default='dados_noticias/gdelt_12_meses')
    parser.add_argument('--existing-directory', default='dados_noticias/portais_12_meses')
    parser.add_argument('--index-only', action='store_true')
    parser.add_argument('--reuse-index', action='store_true')
    args = parser.parse_args()
    if args.interval_days < 1 or not 0 <= args.hour <= 23 or args.start >= args.end:
        parser.error('Intervalo e horário inválidos.')
    archive = Archive(args.directory)
    try:
        if args.reuse_index:
            discovery = json.loads((archive.directory / 'gdelt_discovery.json').read_text())
            if discovery['start'] != args.start or discovery['end_exclusive'] != args.end:
                parser.error('O índice salvo pertence a outro período.')
        else:
            discovery = discover(archive, args.start, args.end, args.interval_days, args.hour)
        if not args.index_only:
            result = collect(archive, discovery, args.start, args.end, args.existing_directory)
            print(json.dumps({k: v for k, v in result.items() if k != 'errors'}, ensure_ascii=False), flush=True)
    finally:
        archive.close()


if __name__ == '__main__':
    main()
