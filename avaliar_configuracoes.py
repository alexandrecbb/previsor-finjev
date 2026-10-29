"""Compara configurações em validação temporal e avalia uma vencedora no teste."""
import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from ibov.config import TICKER, EXTERNAL_TICKERS
from ibov.dados import fetch_data, fetch_external_data
from ibov.atributos import external_features, prepare_features, make_target
from ibov.modelo import fit_temporal_model
from ibov.noticias import news_features

CONFIGURATIONS = {
    "relativos": {},
    "relativos_externos": {"external": True},
    "sem_suavizacao": {"alpha": None},
    "sem_suavizacao_externos": {"alpha": None, "external": True},
    "com_seletor": {"select_features": True},
    "indicadores_originais": {"feature_set": "legacy", "select_features": True},
    "limiar_fixo": {"tune_threshold": False},
    "janela_756": {"max_train_size": 756},
    "logistica": {"model_type": "logistic"},
    "logistica_externos": {"model_type": "logistic", "external": True},
}


def prepare_datasets(raw, external, configurations, *, news_data=None, retrospective_news=False):
    """Todas as alternativas compartilham exatamente as mesmas datas elegíveis."""
    frames = {}
    context = (external_features(raw.index, external)
               if any(c.get("external", False) for c in configurations.values()) else None)
    for name, config in configurations.items():
        frame = prepare_features(raw, alpha=config.get("alpha", 0.7),
                                   feature_set=config.get("feature_set", "relative"))
        if config.get("news", False):
            if news_data is None:
                raise ValueError("Forneça news_data para comparar notícias.")
            frame = frame.join(news_features(raw.index, news_data, retrospective=retrospective_news))
        if config.get("external", False):
            selected = config.get("external_names")
            columns = [c for c in context if selected is None or any(c.startswith(f"ext_{name}_") for name in selected)]
            frame = frame.join(context[columns])
        frames[name] = frame
    common = raw.index
    for frame in frames.values():
        common = common.intersection(frame.dropna().index)
    return {name: frame.loc[common] for name, frame in frames.items()}


def train(X, y, config, horizon, n_iter, n_jobs):
    options = {key: value for key, value in config.items()
               if key not in {"alpha", "feature_set", "external", "external_names", "news"}}
    window = options.get("max_train_size")
    if window is not None:
        X, y = X.iloc[-window:], y.iloc[-window:]
    return fit_temporal_model(X, y, horizon=horizon, n_iter=n_iter, n_jobs=n_jobs, **options)


def scores(y, probability, threshold):
    prediction = (probability >= threshold).astype(int)
    return {"accuracy": float(accuracy_score(y, prediction)),
            "balanced_accuracy": float(balanced_accuracy_score(y, prediction)),
            "roc_auc": float(roc_auc_score(y, probability)),
            "predicted_up_fraction": float(prediction.mean()), "threshold": threshold}


def bootstrap_difference(y, prediction, baseline, block_size=10):
    """Intervalo descritivo por blocos para diferenças pareadas de acerto."""
    difference = (prediction == np.asarray(y)).astype(float) - (baseline == np.asarray(y)).astype(float)
    rng = np.random.default_rng(42)
    n = len(y)
    starts = rng.integers(0, n, size=(2000, int(np.ceil(n / block_size))))
    indices = ((starts[:, :, None] + np.arange(block_size)) % n).reshape(2000, -1)[:, :n]
    return np.quantile(difference[indices].mean(axis=1), [0.025, 0.975]).tolist()


def evaluate(raw, external, *, horizon=3, n_iter=10, n_jobs=2, configurations=None, test_all=False,
             news_data=None, retrospective_news=False):
    """Seleciona no desenvolvimento; test_all abre comparações exploratórias no teste."""
    configurations = CONFIGURATIONS if configurations is None else configurations
    frames = prepare_datasets(raw, external, configurations, news_data=news_data,
                              retrospective_news=retrospective_news)
    target = make_target(raw, horizon).dropna().astype(int)
    dates = next(iter(frames.values())).index.intersection(target.index)
    target = target.loc[dates]
    frames = {name: frame.loc[dates] for name, frame in frames.items()}
    cut = int(len(dates) * 2 / 3)
    dev_dates, test_dates = dates[:cut - horizon], dates[cut:]
    folds = list(TimeSeriesSplit(n_splits=3, gap=horizon).split(dev_dates))
    rows = []
    for name, config in configurations.items():
        fold_results = []
        for number, (train_indices, validation_indices) in enumerate(folds, 1):
            train_dates, val_dates = dev_dates[train_indices], dev_dates[validation_indices]
            model, threshold, _ = train(frames[name].loc[train_dates], target.loc[train_dates],
                                         config, horizon, n_iter, n_jobs)
            result = scores(target.loc[val_dates], model.predict_proba(frames[name].loc[val_dates])[:, 1], threshold)
            majority = int(target.loc[train_dates].mean() > 0.5)
            result.update(start=str(val_dates[0].date()), end=str(val_dates[-1].date()),
                          baseline_accuracy=float((target.loc[val_dates] == majority).mean()))
            fold_results.append(result)
            print(f"{name}: divisão {number}/3, acurácia={result['accuracy']:.4f}", flush=True)
        rows.append({"name": name, "config": config, "folds": fold_results,
                     "mean_accuracy": float(np.mean([r["accuracy"] for r in fold_results])),
                     "std_accuracy": float(np.std([r["accuracy"] for r in fold_results]))})
    rows.sort(key=lambda row: -row["mean_accuracy"])
    winner = rows[0]["name"]
    print(f"Configuração escolhida antes de abrir o teste: {winner}", flush=True)
    # A referência é definida antes da avaliação; não se troca a vencedora pelo teste.
    test_results = {}
    for name in (list(frames) if test_all else dict.fromkeys([winner, "relativos"] if "relativos" in frames else [winner])):
        model, threshold, params = train(frames[name].loc[dev_dates], target.loc[dev_dates],
                                         configurations[name], horizon, n_iter, n_jobs)
        probability = model.predict_proba(frames[name].loc[test_dates])[:, 1]
        result = scores(target.loc[test_dates], probability, threshold)
        baseline = np.full(len(test_dates), int(target.loc[dev_dates].mean() > 0.5))
        result.update(baseline_accuracy=float(accuracy_score(target.loc[test_dates], baseline)),
                      accuracy_gain_ci95=bootstrap_difference(target.loc[test_dates],
                          (probability >= threshold).astype(int), baseline, max(10, horizon)),
                      best_params=params)
        test_results[name] = result
    return {"horizon": horizon, "n_iter": n_iter, "seed": 42,
            "raw_start": str(raw.index[0].date()), "raw_end": str(raw.index[-1].date()),
            "raw_rows": len(raw), "common_labeled_rows": len(dates),
            "development_end": str(dev_dates[-1].date()),
            "test_start": str(test_dates[0].date()), "test_end": str(test_dates[-1].date()),
            "test_rows": len(test_dates), "ranking": rows, "winner": winner, "test": test_results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--n-iter", type=int, default=10)
    parser.add_argument("--n-jobs", type=int, default=2)
    parser.add_argument("--end", default=str(datetime.now(ZoneInfo("America/Sao_Paulo")).date()))
    parser.add_argument("--output", default="avaliacao_real.json")
    args = parser.parse_args()
    end = pd.Timestamp(args.end).date()
    start = end - timedelta(days=365 * 10)
    raw = fetch_data(TICKER, start, end)
    external = fetch_external_data(start - timedelta(days=90), end)
    report = evaluate(raw, external, horizon=args.horizon, n_iter=args.n_iter, n_jobs=args.n_jobs)
    report["sources"] = {"ibov": TICKER, **EXTERNAL_TICKERS}
    report["download_end_exclusive"] = str(end)
    report["data_sha256"] = {name: hashlib.sha256(frame.to_csv().encode()).hexdigest()
                             for name, frame in {"ibov": raw, **external}.items()}
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["test"], indent=2), flush=True)


if __name__ == "__main__":
    main()
