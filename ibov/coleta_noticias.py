"""Coleta auditável de documentos públicos; caches e textos ficam fora do Git."""
import hashlib
import io
import json
import re
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse

import pandas as pd
from pypdf import PdfReader
from pypdf.errors import PyPdfError


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.ignore = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1
        if tag in ("p", "br", "div", "h1", "h2", "h3", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignore = max(0, self.ignore - 1)

    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)


def html_text(value):
    parser = TextParser()
    parser.feed(value or "")
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())


def next_midnight(value):
    """Data sem hora: disponibilidade conservadora após o término do dia local."""
    date = pd.Timestamp(str(value)[:10])
    return (date + pd.Timedelta(days=1)).tz_localize("America/Sao_Paulo", nonexistent="shift_forward").tz_convert("UTC").isoformat()


class Archive:
    def __init__(self, directory="dados_noticias/historico"):
        self.directory = Path(directory)
        (self.directory / "raw").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "fontes.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, source TEXT, url TEXT,
                publication_date TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS gdelt_index (gkg_id TEXT PRIMARY KEY,
                snapshot_at TEXT, url TEXT, publisher TEXT, themes TEXT, brazil INTEGER);
            CREATE TABLE IF NOT EXISTS attempts (url TEXT, collected_at TEXT, status TEXT, detail TEXT);
        ''')
        self.last_request = {}

    def close(self):
        self.db.close()

    def fetch(self, url, delay=0):
        """curl limita o tempo total, inclusive DNS/TLS; não contorna erros 429."""
        digest = hashlib.sha256(url.encode()).hexdigest()
        path = self.directory / "raw" / digest
        metadata = path.with_suffix(".json")
        if path.exists() and metadata.exists():
            return path.read_bytes(), json.loads(metadata.read_text())["collected_at"]
        domain = urlparse(url).netloc
        wait = delay - (time.monotonic() - self.last_request.get(domain, 0))
        if wait > 0:
            time.sleep(wait)
        collected = datetime.now(timezone.utc).isoformat()
        self.last_request[domain] = time.monotonic()
        result = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--location",
                                 "--max-time", "25", "--connect-timeout", "8", "--user-agent", "IbovResearch/1.0",
                                 "--proto", "=https", "--proto-redir", "=https", url],
                                capture_output=True, timeout=30)
        if result.returncode:
            detail = result.stderr.decode(errors="replace")[:500]
            with self.db:
                self.db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?)", (url, collected, "error", detail))
            raise RuntimeError(detail)
        path.write_bytes(result.stdout)
        metadata.write_text(json.dumps({"url": url, "collected_at": collected,
                                        "sha256": hashlib.sha256(result.stdout).hexdigest()}))
        with self.db:
            self.db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?)", (url, collected, "ok", str(len(result.stdout))))
        return result.stdout, collected

    def save(self, row):
        """Versão do texto identificada por URL + hash, preservando versões anteriores."""
        row = dict(row)
        row["content_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
        row["id"] = hashlib.sha256((row["url"] + row["content_sha256"]).encode()).hexdigest()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO documents VALUES (?, ?, ?, ?, ?)",
                            (row["id"], row["source"], row["url"], row["publication_date"], json.dumps(row, ensure_ascii=False)))
        return row

    def documents(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM documents ORDER BY publication_date, id")]

    def collect_bcb(self, start, end, *, max_documents=None):
        count, errors = 0, []
        base = "https://www.bcb.gov.br/api/servico/sitebcb/copom/"
        for kind in ("comunicados", "atas"):
            data, _ = self.fetch(base + kind + "?quantidade=300")
            listing = json.loads(data)["conteudo"]
            for item in sorted(listing, key=lambda r: r.get("dataPublicacao", r["dataReferencia"])):
                date = item.get("dataPublicacao", item["dataReferencia"])
                if not start <= date < end:
                    continue
                if max_documents is not None and count >= max_documents:
                    return {"saved": count, "errors": errors, "limited": True}
                meeting = item.get("nroReuniao", item.get("nro_reuniao"))
                url = base + kind + "_detalhes?" + urlencode({"nro_reuniao": meeting})
                try:
                    content, collected = self.fetch(url, delay=.5)
                    record = json.loads(content)["conteudo"][0]
                    text = html_text(record.get("textoAta", record.get("textoComunicado", "")))
                    text_format = "html"
                    if len(text) < 100 and record.get("urlPdfAta"):
                        pdf_url = record["urlPdfAta"]
                        if not pdf_url.startswith("https://www.bcb.gov.br/"):
                            raise ValueError("PDF fora do domínio oficial esperado.")
                        pdf, pdf_collected = self.fetch(pdf_url, delay=.5)
                        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
                        text_format, collected = "pdf", max(collected, pdf_collected)
                    if len(text) < 100:
                        raise ValueError("Texto ausente ou curto; não substituir por título.")
                    self.save({"source": "bcb", "url": url, "event_id": f"copom-{meeting}-{kind}",
                               "title": record.get("titulo", item.get("titulo", "")), "text": text,
                               "publication_date": date, "published_at": None,
                               "available_at": collected, "historical_available_at": next_midnight(date),
                               "collected_at": collected, "timestamp_quality": "date_only_next_midnight",
                               "version_quality": "current_official_document_unverified_original", "kind": kind, "text_format": text_format})
                    count += 1
                except (RuntimeError, ValueError, KeyError, IndexError, TypeError, PyPdfError) as exc:
                    errors.append({"url": url, "error": str(exc)[:300]})
        return {"saved": count, "errors": errors, "limited": False}

    def discover_ebc(self, start, end):
        data, _ = self.fetch("https://agenciabrasil.ebc.com.br/sitemap.xml", delay=10)
        pages = [e.text.replace("http://", "https://") for e in ET.fromstring(data).findall(".//{*}loc")]
        urls, errors = set(), []
        for page in pages:
            try:
                content, _ = self.fetch(page, delay=10)
                for element in ET.fromstring(content).findall(".//{*}loc"):
                    url = element.text.replace("http://", "https://")
                    match = re.search(r"/economia/noticia/(\d{4}-\d{2})/", url)
                    if match and start[:7] <= match[1] <= end[:7]:
                        urls.add(url)
            except (RuntimeError, ET.ParseError) as exc:
                errors.append({"url": page, "error": str(exc)[:300]})
        result = {"urls": sorted(urls), "errors": errors, "sitemap_pages": len(pages)}
        (self.directory / "ebc_urls.json").write_text(json.dumps(result, ensure_ascii=False))
        return result

    def collect_ebc(self, urls):
        errors, saved = [], 0
        for url in urls:
            try:
                raw, collected = self.fetch(url, delay=10)
                row = parse_ebc(raw.decode("utf-8", errors="replace"), url, collected)
                self.save(row)
                saved += 1
            except (RuntimeError, ValueError) as exc:
                errors.append({"url": url, "error": str(exc)[:300]})
        return {"saved": saved, "errors": errors}

    def index_gkg(self, path):
        """Importa metadados do arquivo público; não inventa texto nem publicação."""
        inserted = brazil = 0
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".csv"):
                    continue
                with archive.open(name) as source, self.db:
                    for line in source:
                        fields = line.decode("utf-8", errors="replace").rstrip("\n").split("\t")
                        if len(fields) < 13 or fields[2] != "1":
                            continue
                        related = int("Brazil" in "\t".join(fields[9:13]))
                        self.db.execute("INSERT OR IGNORE INTO gdelt_index VALUES (?, ?, ?, ?, ?, ?)",
                                        (fields[0], fields[1], fields[4], fields[3], fields[7], related))
                        inserted += 1
                        brazil += related
        result = {"metadata_processed": inserted, "brazil_mentions": brazil,
                  "full_texts_collected": 0, "archive": str(path),
                  "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        (self.directory / "gdelt_archive.json").write_text(json.dumps(result, indent=2))
        return result

    def probe_gdelt(self, start, end):
        """Audita a API DOC; metadados e títulos não contam como textos completos."""
        query = urlencode({"query": "Brazil economy", "mode": "artlist", "format": "json",
                           "startdatetime": start.replace("-", "") + "000000",
                           "enddatetime": end.replace("-", "") + "000000", "maxrecords": 5})
        url = "https://api.gdeltproject.org/api/v2/doc/doc?" + query
        try:
            raw, _ = self.fetch(url)
            result = json.loads(raw)
            return {"status": "metadata_only", "articles_returned": len(result.get("articles", [])),
                    "full_texts_collected": 0, "url": url}
        except (RuntimeError, ValueError) as exc:
            return {"status": "unavailable", "error": str(exc)[:400], "full_texts_collected": 0, "url": url}


class EbcParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.body, self.depth, self.active = {}, [], 0, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("property", attrs.get("name", ""))] = attrs.get("content", "")
        # Corpo editorial Drupal; não usa texto da página inteira como notícia.
        if not self.active and {"field-name-body", "conteudo-noticia"}.intersection(attrs.get("class", "").split()):
            self.active, self.depth = True, 1
        elif self.active and tag not in ("br", "img", "hr", "input", "meta", "link", "source"):
            self.depth += 1
        if self.active and tag in ("p", "br", "div"):
            self.body.append("\n")

    def handle_endtag(self, tag):
        if self.active:
            self.depth -= 1
            if self.depth == 0:
                self.active = False

    def handle_data(self, data):
        if self.active:
            self.body.append(data)


def parse_ebc(html, url, collected):
    parser = EbcParser()
    parser.feed(html)
    text = "\n".join(" ".join(s.split()) for s in "".join(parser.body).splitlines() if s.strip())
    published = parser.meta.get("article:published_time")
    modified = parser.meta.get("article:modified_time")
    if not published or len(text) < 100:
        raise ValueError("Texto editorial ou horário de publicação ausente; requer revisão do extrator.")
    pub = pd.Timestamp(published)
    if pub.tzinfo is None:
        raise ValueError("Publicação sem fuso explícito.")
    # A versão recuperada hoje não prova qual era o texto original. Revisões têm
    # prioridade para a simulação exploratória, sem confundir com coleta real.
    candidate = max(pub, pd.Timestamp(modified)) if modified else pub
    if candidate.tzinfo is None:
        raise ValueError("Atualização sem fuso explícito.")
    return {"source": "agencia_brasil", "url": url, "event_id": url,
            "title": parser.meta.get("og:title", ""), "text": text,
            "publication_date": pub.tz_convert("America/Sao_Paulo").date().isoformat(),
            "published_at": pub.isoformat(), "modified_at": modified, "available_at": collected,
            "historical_available_at": candidate.tz_convert("UTC").isoformat(), "collected_at": collected,
            "timestamp_quality": "publisher_metadata", "version_quality": "current_page_unverified_original"}
