"""Acrescenta sentimento FinBERT-PT-BR a notícias ou episódios JSONL locais."""
import argparse
import json
from pathlib import Path

from ibov.sentimento import FinBertSentiment, FINBERT_REVISION, enrich_news


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSONL contendo text e metadados originais")
    parser.add_argument("--output", default="dados_noticias/noticias_finbert.jsonl")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--revision", default=FINBERT_REVISION)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    source, output = Path(args.input), Path(args.output)
    if source.resolve() == output.resolve():
        parser.error("A saída deve ser diferente do arquivo original.")
    classifier = FinBertSentiment(revision=args.revision, batch_size=args.batch_size,
                                  local_files_only=args.local_files_only)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = enrich_news(rows, classifier)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as target:
        for row in result:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(result)} notícias enriquecidas com FinBERT; saída: {output}")


if __name__ == "__main__":
    main()
