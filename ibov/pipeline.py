"""Coordena os dados, o treinamento, a avaliação e a previsão recente."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sklearn.base import clone

from .config import TICKER, HORIZON_DAYS, ALPHA_SMOOTH, N_ITER_RANDOM_SEARCH
from .dados import fetch_data, fetch_external_data
from .atributos import prepare_features, external_features, make_target
from .modelo import fit_temporal_model
from .noticias import news_features
from .avaliacao import temporal_partitions, calculate_metrics, plot_evaluation


def run_ibov_pipeline(*, raw_data=None, n_iter=N_ITER_RANDOM_SEARCH, show_plots=True,
                      n_jobs=-1, horizon=HORIZON_DAYS, alpha=ALPHA_SMOOTH,
                      feature_set="relative", select_features=False, model_type="xgb",
                      tune_threshold=True, early_stopping=True, max_train_size=None,
                      use_external=False, external_data=None,
                      news_data=None, retrospective_news=False):
    """Retorna métricas históricas, previsão (1 linha) e probabilidades mais recentes."""
    # Coleta de dados do Yahoo Finance
    # O limite final é exclusivo: exclui o pregão de hoje, ainda possivelmente aberto.
    end = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start = end - timedelta(days=365 * 10)
    raw = fetch_data(TICKER, start, end) if raw_data is None else raw_data.copy()
    if not raw.index.is_monotonic_increasing or raw.index.has_duplicates:
        raise ValueError("O histórico deve estar em ordem cronológica e sem datas duplicadas.")
    feature_data = prepare_features(raw, alpha=alpha, feature_set=feature_set)
    if news_data is not None:
        feature_data = feature_data.join(news_features(
            raw.index, news_data, retrospective=retrospective_news))
    if use_external or external_data is not None:
        if external_data is None:
            external_data = fetch_external_data(raw.index[0] - pd.Timedelta(days=90), end)
        feature_data = feature_data.join(external_features(raw.index, external_data))
    latest = feature_data.iloc[[-1]]
    if latest.isna().any().any():
        raise ValueError("Os indicadores do último pregão estão incompletos; previsão indisponível.")
    data = feature_data.join(make_target(raw, horizon)).dropna()

    X, y = data.drop("target", axis=1), data["target"].astype(int)
    if max_train_size is not None and (isinstance(max_train_size, bool) or
                                       not isinstance(max_train_size, int) or max_train_size < 100):
        raise ValueError("max_train_size deve ser inteiro de pelo menos 100 pregões.")
    X_train, X_test, y_train, y_test, _ = temporal_partitions(X, y, horizon, max_train_size)
    best_xgb, threshold, best_params = fit_temporal_model(
        X_train, y_train, horizon=horizon, n_iter=n_iter, n_jobs=n_jobs,
        select_features=select_features, model_type=model_type,
        tune_threshold=tune_threshold, early_stopping=early_stopping,
        max_train_size=max_train_size,
    )
    y_prob = best_xgb.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= threshold).astype(int)

    metrics = calculate_metrics(y_train, y_test, y_pred, y_prob, threshold)
    print("--- RESULTADOS HISTÓRICOS ---")
    print("Horizonte (pregões):", horizon)
    print("Limiar escolhido no treino:", threshold)
    print("Melhores parâmetros:", best_params)
    print("Métricas:", metrics)

    if show_plots:
        plot_evaluation(y_test, y_prob, metrics)

    # Só após a avaliação, reajusta em todo o histórico com alvo conhecido.
    # Os últimos horizon pregões continuam fora desse treino.
    final_X = X if max_train_size is None else X.iloc[-max_train_size:]
    forecast_model = clone(best_xgb).fit(final_X, y.loc[final_X.index])
    print("Data-base da previsão:", latest.index[-1].date())
    probability = forecast_model.predict_proba(latest)
    return metrics, (probability[:, 1] >= threshold).astype(int), probability
