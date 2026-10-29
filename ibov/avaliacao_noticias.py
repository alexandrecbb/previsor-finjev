"""Avaliação retrospectiva pareada de notícias reais, com alvos em pregões."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .memoria import NewsMemory, RETRIEVAL_CONFIG
from .coleta_noticias import next_midnight
from .noticias import timestamp
from .decisao_noticias import VERSION as DECISION_VERSION
from .sentimento import validate_sentiment

TEXT_LIMIT = 4000


def market_context(prices, cutoff):
    """Somente fechamentos de datas anteriores ao dia local do corte."""
    cutoff = timestamp(cutoff)
    date = cutoff.tz_convert("America/Sao_Paulo").tz_localize(None).normalize()
    known = prices.loc[prices.index < date, "close"]
    if len(known) < 21:
        raise ValueError("Contexto exige pelo menos 21 fechamentos anteriores.")
    return {"available_at": (known.index[-1] + pd.Timedelta(days=1)).tz_localize("America/Sao_Paulo").isoformat(),
            "data": {"base_date": known.index[-1].date().isoformat(), "close": float(known.iloc[-1]),
                     "return_5": float(known.iloc[-1] / known.iloc[-6] - 1),
                     "return_20": float(known.iloc[-1] / known.iloc[-21] - 1),
                     "volatility_20": float(known.pct_change().iloc[-20:].std())}}


def prepare_episodes(documents, prices, *, horizon=3, model="jev-1.14.0", text_limit=TEXT_LIMIT):
    """Prepara rótulos isolados, sem embuti-los no contexto do episódio."""
    if (prices.empty or not isinstance(prices.index, pd.DatetimeIndex) or prices.index.tz is not None
            or prices.index.has_duplicates or not prices.index.is_monotonic_increasing):
        raise ValueError("Preços devem conter datas locais ordenadas e únicas, sem fuso.")
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("Horizonte deve ser inteiro positivo.")
    if not np.isfinite(prices["close"]).all() or (prices["close"] <= 0).any():
        raise ValueError("Preços inválidos.")
    if text_limit is not None and (isinstance(text_limit, bool) or not isinstance(text_limit, int) or text_limit < 1):
        raise ValueError("Limite de texto deve ser inteiro positivo ou None.")
    episodes, excluded = [], []
    for doc in documents:
        available = timestamp(doc["historical_available_at"])
        # Usa o texto no dia seguinte à disponibilidade declarada. Isso evita
        # inferir um horário de fechamento histórico ou negociar antes da notícia.
        cutoff = timestamp(next_midnight(available.tz_convert("America/Sao_Paulo").date()))
        try:
            context = market_context(prices, cutoff)
            original_context = market_context(prices, available)
        except ValueError as exc:
            excluded.append({"id": doc["id"], "reason": str(exc)})
            continue
        base_date = pd.Timestamp(context["data"]["base_date"])
        position = prices.index.get_loc(base_date)
        future = position + horizon
        outcome, outcome_at = None, None
        if future < len(prices):
            outcome = int(prices["close"].iloc[future] > prices["close"].iloc[position])
            outcome_at = (prices.index[future] + pd.Timedelta(days=1)).tz_localize("America/Sao_Paulo").tz_convert("UTC").isoformat()
        episode = {"id": doc["id"], "event_id": doc["event_id"], "text": doc["text"][:text_limit],
                   "published_at": doc.get("published_at") or doc["historical_available_at"],
                   "available_at": doc["historical_available_at"], "classified_at": doc["collected_at"],
                   "classification_mode": "raw_text_no_sentiment_classification",
                   "model": model, "prompt_version": "ibov-news-v1", "asset": "^BVSP", "horizon": horizon,
                   "context": original_context["data"], "outcome": outcome, "outcome_at": outcome_at,
                   "source": doc["source"], "url": doc["url"], "cutoff": cutoff.isoformat(),
                   "query_context": context, "base_position": position}
        if doc.get("sentiment") is not None:
            # Não associe o hash de um texto completo a outro texto truncado.
            validate_sentiment(doc["sentiment"], episode["text"])
            episode["sentiment"] = doc["sentiment"]
            episode["classified_at"] = max(timestamp(doc["collected_at"]),
                                            timestamp(doc["sentiment"]["classified_at"])).isoformat()
            episode["classification_mode"] = "finbert_sentiment"
        episodes.append(episode)
    return sorted(episodes, key=lambda r: (r["cutoff"], r["id"])), excluded


def sample_episodes(episodes, *, size=12, warmup_days=365):
    """Seleção determinística por tempo, sem usar direção ou magnitude do alvo."""
    if size < 1:
        raise ValueError("Tamanho da amostra deve ser positivo.")
    if isinstance(warmup_days, bool) or not isinstance(warmup_days, int) or warmup_days < 0:
        raise ValueError("Aquecimento deve ser inteiro não negativo.")
    if not episodes:
        return []
    start = min(timestamp(r["available_at"]) for r in episodes) + pd.Timedelta(days=warmup_days)
    eligible = [r for r in episodes if timestamp(r["cutoff"]) >= start and r["outcome"] is not None]
    sources = sorted({r["source"] for r in eligible})
    desired = []
    for i, source in enumerate(sources):
        group = [r for r in eligible if r["source"] == source]
        count = min(len(group), size // len(sources) + int(i < size % len(sources)))
        desired.extend(group[j] for j in np.linspace(0, len(group)-1, count, dtype=int))
    selected = []
    def accept(row):
        if all(abs(row["base_position"] - old["base_position"]) > row["horizon"] for old in selected):
            selected.append(row)
    for row in sorted(desired, key=lambda r: (r["cutoff"], r["id"])):
        accept(row)
    # Preenche conflitos por uma ordem temporal fixa e distribuída.
    if len(selected) < size and eligible:
        for index in np.linspace(0, len(eligible)-1, len(eligible), dtype=int):
            if len(selected) == size:
                break
            accept(eligible[index])
    return sorted(selected, key=lambda r: (r["cutoff"], r["id"]))



def metrics(rows):
    """Abstenções reduzem cobertura; não entram como acertos nem desaparecem."""
    answered = [r for r in rows if r["prediction"] is not None]
    n = len(answered)
    correct = sum(r["prediction"] == r["outcome"] for r in answered)
    accuracy = correct / n if n else None
    interval = None
    if n:
        z = 1.959963984540054
        centre = (accuracy + z*z/(2*n)) / (1 + z*z/n)
        half = z * math.sqrt(accuracy*(1-accuracy)/n + z*z/(4*n*n)) / (1+z*z/n)
        interval = [centre-half, centre+half]
    recalls = [sum(r["prediction"] == c for r in answered if r["outcome"] == c) /
               sum(r["outcome"] == c for r in answered)
               for c in (0, 1) if any(r["outcome"] == c for r in answered)]
    return {"n_total": len(rows), "n_answered": n, "n_abstained": len(rows)-n,
            "n_hold": sum(r.get("action") == "hold" for r in rows),
            "coverage": n/len(rows) if rows else 0., "accuracy_answered": accuracy,
            "balanced_accuracy_answered": sum(recalls)/2 if len(recalls) == 2 else None,
            "wilson_95_answered": interval, "correct_over_all": correct/len(rows) if rows else None,
            "up_outcomes": sum(r["outcome"] == 1 for r in rows)}


def evaluate_news(episodes, decision_model, *, directory, sample_size=12, warmup_days=365):
    """Piloto pareado com/sem memória. Cada estado é salvo para auditoria.

    O modelo é fixo; não ajusta hiperparâmetros no teste. Nenhuma reflexão criada
    hoje é retroagida para o passado. O pré-treinamento pode contaminar o estudo.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sample = sample_episodes(episodes, size=sample_size, warmup_days=warmup_days)
    if not sample:
        raise ValueError("Não há amostra madura após o aquecimento configurado.")
    signature = hashlib.sha256(json.dumps({"episodes": episodes, "decision_version": DECISION_VERSION,
                                         "retrieval_config": RETRIEVAL_CONFIG},
                                         sort_keys=True).encode()).hexdigest()[:16]
    path = directory / f"avaliacao_{signature}.sqlite"
    memory = NewsMemory(path)
    for row in episodes:
        memory.add({k: v for k, v in row.items() if k not in ("query_context", "cutoff", "base_position")})
    results, errors = [], []
    try:
        for episode in sample:
            for arm in ("without_memory", "with_memory"):
                query_id = f'{episode["id"]}:{arm}'
                stored = memory.db.execute("SELECT result FROM retrievals WHERE query_id=?", (query_id,)).fetchone()
                try:
                    if stored:
                        result = json.loads(stored[0])
                    else:
                        result = memory.predict(episode["text"], episode["cutoff"],
                                                sentiment=episode.get("sentiment"),
                                                context=episode["query_context"], decision_model=decision_model,
                                                max_text_chars=TEXT_LIMIT,
                                                query_id=query_id, retrospective=True, top_k=3,
                                                model=episode["model"], horizon=episode["horizon"],
                                                exclude_event_ids=tuple(r["event_id"] for r in episodes) if arm == "without_memory" else (episode["event_id"],))
                    results.append({"id": episode["id"], "arm": arm, "source": episode["source"],
                                    "cutoff": episode["cutoff"], "outcome": episode["outcome"],
                                    "prediction": result["prediction"], "decision": result["decision"],
                                    "action": result["action"],
                                    "n_memories": result["n_events"] if arm == "with_memory" else 0})
                except (ValueError, RuntimeError) as exc:
                    errors.append({"id": episode["id"], "arm": arm, "error": str(exc)})
                    # Não avança após falha: permite retomar exatamente a amostra.
                    break
            if errors:
                break
        by_arm = {arm: metrics([r for r in results if r["arm"] == arm]) for arm in ("without_memory", "with_memory")}
        complete_ids = {r["id"] for r in results if r["arm"] == "without_memory"} & {r["id"] for r in results if r["arm"] == "with_memory"}
        paired = {arm: metrics([r for r in results if r["arm"] == arm and r["id"] in complete_ids]) for arm in by_arm}
        common_ids = {id_ for id_ in complete_ids if all(r["prediction"] is not None for r in results if r["id"] == id_)}
        common = {arm: metrics([r for r in results if r["arm"] == arm and r["id"] in common_ids]) for arm in by_arm}
        baseline = [{"outcome": r["outcome"], "prediction": 1} for r in sample]
        report = {"exploratory": True, "signature": signature, "warmup_days": warmup_days,
                  "decision_version": DECISION_VERSION,
                  "retrieval_config": RETRIEVAL_CONFIG,
                  "metric_scope": "Proxy direcional: buy=alta, sell=baixa/igual; hold fora da acurácia. Não mede retorno de carteira.",
                  "planned_n": len(sample), "completed_pairs": len(complete_ids),
                  "text_limit": TEXT_LIMIT, "sample_ids": [r["id"] for r in sample], "errors": errors,
                  "metrics": by_arm, "paired_metrics": paired, "both_answered_metrics": common,
                  "always_up_planned": metrics(baseline),
                  "always_up_paired": metrics([{"outcome": r["outcome"], "prediction": 1} for r in sample if r["id"] in complete_ids]),
                  "always_up_both_answered": metrics([{"outcome": r["outcome"], "prediction": 1} for r in sample if r["id"] in common_ids]),
                  "results": results,
                  "limitations": ["Textos atuais recuperados hoje, sem garantia da versão original.",
                                  "Pré-treinamento Jev pode incluir eventos posteriores aos cortes.",
                                  "Amostra pequena e seleção por disponibilidade das fontes.",
                                  "Reflexões atuais não são retroagidas; piloto não mede aprendizado por reflexões históricas.",
                                  "Intervalo de Wilson descritivo; não corrige dependência de mercado."]}
        (directory / "avaliacao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return report
    finally:
        memory.close()
