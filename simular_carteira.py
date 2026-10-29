"""Simula ordens fictícias do Jev com notícias classificadas pelo FinBERT."""
import argparse
import json
from pathlib import Path

import pandas as pd

from ibov.avaliacao_noticias import prepare_episodes
from ibov.carteira import simulate_portfolio
from ibov.decisao_noticias import JevMemoryModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", default="dados_noticias/portais_12_meses/noticias_finbert.jsonl")
    parser.add_argument("--prices", default="dados_noticias/historico/precos_ibov.csv")
    parser.add_argument("--directory", default="dados_noticias/simulacao_carteira_semantica")
    parser.add_argument("--initial-cash", type=float, default=100000.)
    parser.add_argument("--fee-rate", type=float, default=.001)
    parser.add_argument("--sample-size", type=int, default=24)
    parser.add_argument("--warmup-days", type=int, default=90)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--model", default="jev-1.14.0")
    parser.add_argument("--max-requests", type=int, default=24)
    args = parser.parse_args()
    documents = [json.loads(line) for line in Path(args.documents).read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(doc.get("source") not in ("infomoney", "moneytimes") or not doc.get("sentiment") for doc in documents):
        raise ValueError("Forneça apenas notícias classificadas das duas fontes ativas.")
    prices = pd.read_csv(args.prices, index_col=0, parse_dates=True)
    episodes, excluded = prepare_episodes(documents, prices, horizon=args.horizon, model=args.model, text_limit=None)
    model = JevMemoryModel(model=args.model, max_requests=args.max_requests, transport="curl")
    report = simulate_portfolio(episodes, prices, model,
                                directory=args.directory, sample_size=args.sample_size, warmup_days=args.warmup_days,
                                initial_cash=args.initial_cash, fee_rate=args.fee_rate)
    report["excluded_documents"] = excluded
    report["new_jev_requests_attempted_this_run"] = args.max_requests - model.remaining
    (Path(args.directory) / "simulacao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("decisions", "orders")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
