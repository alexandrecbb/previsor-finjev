"""Comparação exploratória de indicadores suavizados, originais e combinados."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from avaliar_configuracoes import evaluate
from ibov.config import TICKER
from ibov.dados import fetch_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.horizon < 1:
        parser.error("O horizonte deve ser positivo.")
    output = args.output or ("avaliacao_suavizacao.json" if args.horizon == 3
                             else f"avaliacao_suavizacao_{args.horizon}pregoes.json")
    # Mesmo corte da avaliação anterior; o teste já consultado é exploratório.
    end = pd.Timestamp("2026-10-28")
    start = end - pd.Timedelta(days=365 * 10)
    raw = fetch_data("^BVSP", start, end)
    configurations = {
        "suavizados": {},
        "sem_suavizacao": {"alpha": None},
        "combinados": {"feature_set": "dual_smoothing"},
    }
    report = evaluate(raw, None, horizon=args.horizon, n_iter=10, n_jobs=2,
                      configurations=configurations, test_all=True)
    report["exploratory"] = True
    report["sources"] = {"ibov": TICKER}
    report["download_end_exclusive"] = str(end.date())
    report["data_sha256"] = {name: hashlib.sha256(frame.to_csv().encode()).hexdigest()
                             for name, frame in {"ibov": raw}.items()}
    Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["test"], indent=2), flush=True)


if __name__ == "__main__":
    main()
