"""Atualização incremental das três fontes antes das previsões atuais."""
import contextlib
import io
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from coletar_portais_noticias import collect_wordpress
from .coleta_noticias import Archive
from .noticias import timestamp
from .sentimento import FinBertSentiment, enrich_news

SOURCES = ("infomoney", "moneytimes", "bcb")


def update_daily_news(memory, *, directory="dados_noticias/diarias", classifier=None,
                      model="jev-1.14.0", asset="^BVSP", horizon=3, now=None):
    """Consulta fontes frescas, preserva versões e classifica só episódios ausentes.

    A janela sobrepõe dois dias à última publicação; a primeira coleta cobre
    sete dias. O arquivo de fontes também permite retomar uma classificação
    interrompida. Nenhuma decisão, resultado futuro ou preço é inventado.
    """
    now = timestamp(now or datetime.now(timezone.utc).isoformat())
    today = now.tz_convert("America/Sao_Paulo").date()
    archive = Archive(directory)
    report = {"sources": {}, "new_documents": 0, "new_episodes": 0}
    try:
        previous = archive.documents()
        existing = {r[0] for r in memory.db.execute("SELECT id FROM episodes")}
        known = {row["id"] for row in previous} | existing
        for source in SOURCES:
            dates = [row["publication_date"] for row in previous if row["source"] == source]
            latest = memory.db.execute(
                "SELECT MAX(json_extract(payload, '$.published_at')) FROM episodes "
                "WHERE json_extract(payload, '$.source')=?", (source,)).fetchone()[0]
            if latest:
                dates.append(timestamp(latest).tz_convert("America/Sao_Paulo").date().isoformat())
            start = (min(today, datetime.fromisoformat(max(dates)).date()) - timedelta(days=2)
                     if dates else today - timedelta(days=7))
            end = (today + timedelta(days=1)).isoformat()
            # Um arquivo temporário novo impede que sitemaps/APIs em cache
            # ocultem notícias publicadas desde a execução anterior.
            with tempfile.TemporaryDirectory(prefix="ibov-noticias-") as folder:
                fresh = Archive(folder)
                try:
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):
                            if source == "bcb":
                                status = fresh.collect_bcb(start.isoformat(), end)
                            else:
                                status = collect_wordpress(source, fresh, start.isoformat(), end)
                    except (RuntimeError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
                        status = {"errors": [{"error": str(exc)[:300]}], "complete": False}
                    added = 0
                    for row in fresh.documents():
                        if row["id"] not in known:
                            archive.save(row)
                            known.add(row["id"])
                            added += 1
                    if added:
                        shutil.copytree(Path(folder) / "raw", archive.directory / "raw", dirs_exist_ok=True)
                    report["sources"][source] = {
                        "new_documents": added, "errors": status.get("errors", []),
                        "complete": status.get("complete", not status.get("errors") and not status.get("limited")),
                        "start": start.isoformat(), "end_exclusive": end,
                    }
                    report["new_documents"] += added
                finally:
                    fresh.close()

        pending = [row for row in archive.documents() if row["id"] not in existing]
        episodes = []
        for row in pending:
            if row["source"] not in SOURCES:
                continue
            published = row.get("published_at") or row["historical_available_at"]
            available = max(timestamp(row["collected_at"]), timestamp(published),
                            timestamp(row.get("modified_at") or published))
            episodes.append({"id": row["id"], "event_id": row["event_id"], "text": row["text"],
                             "published_at": published, "available_at": available.isoformat(),
                             "classified_at": row["collected_at"], "model": model,
                             "prompt_version": "ibov-news-v1", "asset": asset, "horizon": horizon,
                             "context": {}, "outcome": None, "outcome_at": None,
                             "source": row["source"], "url": row["url"],
                             "collected_at": row["collected_at"]})
        if episodes:
            for episode in enrich_news(episodes, classifier if classifier is not None else FinBertSentiment()):
                memory.add(episode)
                report["new_episodes"] += 1
        report["status"] = ("updated" if report["new_episodes"] else
                            "source_errors" if any(not r["complete"] or r["errors"]
                                                   for r in report["sources"].values()) else "no_new_news")
        return report
    finally:
        archive.close()
