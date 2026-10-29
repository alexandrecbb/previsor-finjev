"""Comparação exploratória pareada dos mercados externos com e sem Selic."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from avaliar_configuracoes import evaluate
from ibov.config import EXTERNAL_TICKERS
from ibov.dados import fetch_data, fetch_external_data, fetch_interest_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.horizon < 1:
        parser.error("O horizonte deve ser positivo.")
    output = args.output or ("avaliacao_juros.json" if args.horizon == 3
                             else f"avaliacao_juros_{args.horizon}pregoes.json")
    # Mesmo corte da avaliação anterior; o teste já consultado é exploratório.
    end = pd.Timestamp("2026-10-28")
    start = end - pd.Timedelta(days=365 * 10)
    raw = fetch_data("^BVSP", start, end)
    external = fetch_external_data(start - pd.Timedelta(days=90), end)
    external["selic"] = fetch_interest_data(start - pd.Timedelta(days=90), end)
    configurations = {
        "sem_externos": {},
        "quatro_mercados": {"external": True, "external_names": list(EXTERNAL_TICKERS)},
        "quatro_mercados_selic": {"external": True},
    }
    report = evaluate(raw, external, horizon=args.horizon, n_iter=10, n_jobs=2,
                      configurations=configurations, test_all=True)
    report["exploratory"] = True
    report["sources"] = {"ibov": "^BVSP", **EXTERNAL_TICKERS, "selic": "BCB SGS 432 (% a.a.)"}
    report["download_end_exclusive"] = str(end.date())
    report["data_sha256"] = {name: hashlib.sha256(frame.to_csv().encode()).hexdigest()
                             for name, frame in {"ibov": raw, **external}.items()}
    Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["test"], indent=2), flush=True)


if __name__ == "__main__":
    main()
