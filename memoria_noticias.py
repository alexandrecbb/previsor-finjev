"""Importa episódios JSONL e consulta a memória local de notícias."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ibov.memoria import NewsMemory
from ibov.decisao_noticias import JevMemoryModel
from ibov.sentimento import FinBertSentiment, FINBERT_REVISION, enrich_news
from ibov.avaliacao_noticias import prepare_episodes
from ibov.atualizacao_noticias import update_daily_news


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="dados_noticias/memoria_finbert.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("importar")
    load.add_argument("input", help="Arquivo JSONL de episódios documentados no README")
    load.add_argument("--without-finbert", action="store_true", help="Importar sem nova classificação")
    load.add_argument("--finbert-revision", default=FINBERT_REVISION)
    load.add_argument("--prices", help="CSV de preços para preparar episódios a partir de notícias brutas JSONL")
    load.add_argument("--horizon", type=int, default=3)
    load.add_argument("--model", default="jev-1.14.0")
    query = commands.add_parser("prever")
    query.add_argument("--text", required=True)
    query.add_argument("--event-id", help="Evento da notícia atual, excluído das memórias para evitar autorreferência")
    query.add_argument("--cutoff", default="now", help="Horário com fuso ou now (padrão, após classificar)")
    query.add_argument("--query-id", required=True, help="Identificador único para auditoria")
    query.add_argument("--retrospective", action="store_true")
    query.add_argument("--context", required=True, help="JSON com data e available_at do contexto atual")
    query.add_argument("--horizon", type=int, default=3)
    query.add_argument("--asset", default="^BVSP")
    query.add_argument("--model", default="jev-1.14.0")
    query.add_argument("--max-requests", type=int, default=1)
    query.add_argument("--without-finbert", action="store_true", help="Ablação sem sentimento atual")
    query.add_argument("--finbert-revision", default=FINBERT_REVISION)
    query.add_argument("--news-directory", default="dados_noticias/diarias",
                       help="Arquivo incremental das três fontes, consultadas antes de cada previsão")
    query.add_argument("--max-reflection-requests", type=int, default=1,
                       help="Orçamento separado para reflexões pendentes antes da previsão; 0 desativa")
    reflect = commands.add_parser("refletir")
    reflect.add_argument("--query-id", required=True)
    reflect.add_argument("--reflection-id", required=True)
    reflect.add_argument("--outcome", required=True, type=int, choices=[0, 1])
    reflect.add_argument("--outcome-at", required=True)
    reflect.add_argument("--created-at", required=True)
    reflect.add_argument("--model", default="jev-1.14.0")
    reflect.add_argument("--max-requests", type=int, default=1)
    feedback = commands.add_parser("feedback", help="Registrar resultado líquido observado sem chamada ao Jev")
    feedback.add_argument("--query-id", required=True)
    feedback.add_argument("--net-return", required=True, type=float)
    feedback.add_argument("--outcome-at", required=True)
    feedback.add_argument("--created-at", required=True)
    result = commands.add_parser("resultado", help="Registrar resultado observado e refletir automaticamente")
    result.add_argument("--query-id", required=True)
    result.add_argument("--outcome", required=True, type=int, choices=[0, 1])
    result.add_argument("--outcome-at", required=True)
    result.add_argument("--observed-at", required=True)
    result.add_argument("--net-return", type=float)
    update = commands.add_parser("atualizar", help="Processar resultados e reflexões pendentes")
    update.add_argument("--results", help="JSONL de query_id,outcome,outcome_at,observed_at e net_return opcional")
    for command in (result, update):
        command.add_argument("--model", default="jev-1.14.0")
        command.add_argument("--max-requests", type=int, default=1)
    args = parser.parse_args()
    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    memory = NewsMemory(args.database)
    try:
        if args.command == "importar":
            count = 0
            with open(args.input, encoding="utf-8") as source:
                rows = [json.loads(line) for line in source if line.strip()]
            if args.prices:
                if any(row.get("source") not in ("infomoney", "moneytimes", "bcb") for row in rows):
                    raise ValueError("Notícias brutas contêm fontes fora do escopo ativo.")
                prices = pd.read_csv(args.prices, index_col=0, parse_dates=True)
                rows, excluded = prepare_episodes(rows, prices, horizon=args.horizon, model=args.model)
                print(f"{len(excluded)} documentos excluídos por contexto insuficiente.")
                rows = [{k: v for k, v in row.items() if k not in ("query_context", "cutoff", "base_position")}
                        for row in rows]
            if not args.without_finbert:
                rows = enrich_news(rows, FinBertSentiment(revision=args.finbert_revision))
            for row in rows:
                memory.add(row)
                count += 1
            print(f"{count} registros processados; reimportações idênticas são ignoradas.")
        elif args.command == "feedback":
            result = memory.record_outcome(args.query_id, net_return=args.net_return,
                                           outcome_at=args.outcome_at, created_at=args.created_at)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command in ("resultado", "atualizar"):
            query_ids = None
            if args.command == "resultado":
                memory.register_result(args.query_id, outcome=args.outcome, outcome_at=args.outcome_at,
                                       observed_at=args.observed_at, net_return=args.net_return)
                query_ids = (args.query_id,)
            elif args.results:
                with Path(args.results).open(encoding="utf-8") as source:
                    for line in source:
                        if line.strip():
                            row = json.loads(line)
                            memory.register_result(row["query_id"], outcome=row["outcome"],
                                                   outcome_at=row["outcome_at"], observed_at=row["observed_at"],
                                                   net_return=row.get("net_return"))
            model = JevMemoryModel(model=args.model, max_requests=args.max_requests)
            result = memory.process_pending_reflections(model.reflect, as_of=datetime.now(timezone.utc).isoformat(),
                                                        limit=args.max_requests, query_ids=query_ids)
            print(json.dumps({"reflections": result, "new_requests": args.max_requests - model.remaining},
                             ensure_ascii=False, indent=2))
        else:
            model = JevMemoryModel(model=args.model, max_requests=args.max_requests)
            if args.command == "prever":
                context = json.loads(Path(args.context).read_text(encoding="utf-8"))
                news_update = update_daily_news(
                    memory, directory=args.news_directory, model=args.model, asset=args.asset,
                    horizon=args.horizon, classifier=FinBertSentiment(revision=args.finbert_revision))
                reflection_model = JevMemoryModel(model=args.model, max_requests=args.max_reflection_requests)
                # Em consultas históricas, novas reflexões não podem entrar no passado.
                review_cutoff = datetime.now(timezone.utc).isoformat() if args.cutoff == "now" else args.cutoff
                automatic = memory.process_pending_reflections(reflection_model.reflect, as_of=review_cutoff,
                                                               limit=args.max_reflection_requests)
                sentiment = None if args.without_finbert else FinBertSentiment(revision=args.finbert_revision)(args.text)
                cutoff = datetime.now(timezone.utc).isoformat() if args.cutoff == "now" else args.cutoff
                result = memory.predict(args.text, cutoff, context=context, decision_model=model,
                                        sentiment=sentiment,
                                        query_id=args.query_id, horizon=args.horizon, asset=args.asset,
                                        exclude_event_ids=(args.event_id,) if args.event_id else (),
                                        model=args.model, retrospective=args.retrospective)
                result["automatic_reflections"] = [row["id"] for row in automatic]
                result["news_update"] = news_update
                result["new_reflection_requests"] = args.max_reflection_requests - reflection_model.remaining
            else:
                result = memory.reflect(args.query_id, reflection_id=args.reflection_id,
                                        outcome=args.outcome, outcome_at=args.outcome_at,
                                        created_at=args.created_at, reflection_model=model.reflect)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        memory.close()


if __name__ == "__main__":
    main()
