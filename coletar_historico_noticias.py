"""Coleta documentos do Copom, matérias de economia da Agência Brasil e audita GDELT."""
import argparse
import json
from pathlib import Path

from ibov.coleta_noticias import Archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=["bcb", "ebc", "gdelt"])
    parser.add_argument("--start", default="2016-10-28")
    parser.add_argument("--end", default="2026-10-28")
    parser.add_argument("--directory", default="dados_noticias/historico")
    parser.add_argument("--max-documents", type=int)
    parser.add_argument("--url-file", help="JSON com lista de URLs oficiais EBC adicionais")
    parser.add_argument("--gkg-file", help="Importa ZIP GKG já baixado, sem tratá-lo como texto integral")
    parser.add_argument("--per-year", type=int, default=2, help="Amostra determinística EBC; 0 coleta todas as URLs")
    args = parser.parse_args()
    archive = Archive(args.directory)
    try:
        if args.source == "bcb":
            result = archive.collect_bcb(args.start, args.end, max_documents=args.max_documents)
        elif args.source == "gdelt":
            result = archive.index_gkg(args.gkg_file) if args.gkg_file else archive.probe_gdelt(args.start, args.end)
        else:
            discovered = {"urls": json.loads(Path(args.url_file).read_text()), "errors": []} if args.url_file else archive.discover_ebc(args.start, args.end)
            urls = discovered["urls"]
            if args.per_year and not args.url_file:
                years = sorted({u.split("/noticia/")[1][:4] for u in urls})
                sampled = []
                for year in years:
                    group = [u for u in urls if f"/noticia/{year}-" in u]
                    # Espalha a amostra no ano sem selecionar pelo teor ou resultado.
                    positions = [round(i * (len(group) - 1) / max(1, args.per_year - 1)) for i in range(args.per_year)]
                    sampled.extend(group[i] for i in sorted(set(positions)))
                urls = sampled
            if args.max_documents is not None:
                urls = urls[:args.max_documents]
            result = {"discovered": len(discovered["urls"]), "discovery_errors": discovered["errors"],
                      "sampling_per_year": None if args.url_file else args.per_year, **archive.collect_ebc(urls)}
        path = Path(args.directory) / ("gdelt_archive.json" if args.gkg_file else args.source + ("_additional" if args.url_file else "") + "_collection.json")
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
    finally:
        archive.close()


if __name__ == "__main__":
    main()
