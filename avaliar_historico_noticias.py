"""Executa piloto cronológico pareado de notícias reais com Jev."""
import argparse
import json
from pathlib import Path

import pandas as pd

from ibov.avaliacao_noticias import evaluate_news, prepare_episodes
from ibov.dados import fetch_data
from ibov.decisao_noticias import JevMemoryModel
from ibov.sentimento import FinBertSentiment, FINBERT_REVISION, enrich_news


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="dados_noticias/avaliacao_portais_semantica")
    parser.add_argument("--sample-size", type=int, default=12)
    parser.add_argument("--max-requests", type=int, default=24)
    parser.add_argument("--model", default="jev-1.14.0")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--warmup-days", type=int, default=90)
    parser.add_argument("--documents", default="dados_noticias/portais_12_meses/noticias_12_meses.jsonl",
                        help="Consolidado JSONL; use diretório separado para preservar o piloto anterior.")
    parser.add_argument("--prices", help="CSV local de preços reais, com índice de datas.")
    parser.add_argument("--without-finbert", action="store_true", help="Ablação sem sentimento FinBERT")
    parser.add_argument("--finbert-revision", default=FINBERT_REVISION)
    parser.add_argument("--finbert-batch-size", type=int, default=8)
    args = parser.parse_args()
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    documents = [json.loads(line) for line in Path(args.documents).read_text().splitlines() if line.strip()]
    documents = [r for r in documents if r["source"] in ("infomoney", "moneytimes")]
    prices_path = Path(args.prices) if args.prices else directory / "precos_ibov.csv"
    if prices_path.exists():
        prices = pd.read_csv(prices_path, index_col=0, parse_dates=True)
    else:
        prices = fetch_data("^BVSP", "2016-09-01", "2026-10-28")
        prices.to_csv(prices_path)
    snapshot = directory / "evaluation_snapshot.json"
    if snapshot.exists():
        documents = json.loads(snapshot.read_text())
        if any(r["source"] not in ("infomoney", "moneytimes") for r in documents):
            raise ValueError("Snapshot contém fontes fora do escopo ativo; use outro diretório.")
    else:
        snapshot.write_text(json.dumps(documents, ensure_ascii=False, indent=2))
    text_limit = None if not args.without_finbert and any(doc.get("sentiment") for doc in documents) else 4000
    episodes, excluded = prepare_episodes(documents, prices, horizon=args.horizon, model=args.model,
                                         text_limit=text_limit)
    if not args.without_finbert:
        episodes = enrich_news(episodes, FinBertSentiment(revision=args.finbert_revision,
                                                        batch_size=args.finbert_batch_size))
    report = evaluate_news(episodes, JevMemoryModel(model=args.model, max_requests=args.max_requests, transport="curl"),
                           directory=directory, sample_size=args.sample_size, warmup_days=args.warmup_days)
    report["documents_collected"] = len(documents)
    report["episodes_prepared"] = len(episodes)
    report["excluded_documents"] = excluded
    (directory / "avaliacao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ("results", "sample_ids", "excluded_documents")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
