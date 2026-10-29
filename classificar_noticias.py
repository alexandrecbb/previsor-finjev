"""Classifica um CSV de notícias via Jev e salva atributos sem textos nem credenciais."""
import argparse
from pathlib import Path

import pandas as pd

from ibov.noticias import classify_news


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="CSV com id,text,published_at,available_at")
    parser.add_argument("--output", default="dados_noticias/classificadas.csv")
    parser.add_argument("--model", default="jev-1.14.0")
    parser.add_argument("--max-requests", type=int, default=100)
    args = parser.parse_args()
    result = classify_news(pd.read_csv(args.input, dtype={"id": str}),
                           model=args.model, max_requests=args.max_requests)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    print(f"{len(result)} notícias classificadas; saída: {output}")


if __name__ == "__main__":
    main()
