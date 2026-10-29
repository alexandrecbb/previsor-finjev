"""Entrada de execução e compatibilidade com os imports do arquivo original.

A implementação está no pacote ibov. Importar este módulo não executa o pipeline.
"""

from ibov.config import (
    TICKER, ALPHA_SMOOTH, HORIZON_DAYS, FEATURE_IMPORTANCE_THRESHOLD,
    RANDOM_STATE, N_ITER_RANDOM_SEARCH, FEATURES, PARAM_GRID, EXTERNAL_TICKERS,
)
from ibov.dados import fetch_data, fetch_external_data
from ibov.atributos import (
    exp_smooth, apply_smoothing, compute_indicators, prepare_features,
    external_features, make_target,
)
from ibov.modelo import TreeFeatureSelector, TemporalEarlyStoppingPipeline, fit_temporal_model
from ibov.avaliacao import temporal_partitions
from ibov.pipeline import run_ibov_pipeline


def prever_tendencia(res, prob, horizon=HORIZON_DAYS):
    last_prob = prob[-1][1]
    if res == 1:
        print(f"📈 Tendência prevista: ALTA em {horizon} pregões (probabilidade estimada: {last_prob:.2%})")
    else:
        print(f"📉 Tendência prevista: BAIXA OU ESTABILIDADE em {horizon} pregões (probabilidade estimada: {1-last_prob:.2%})")


def main():
    """Executa a previsão com os parâmetros padrão e apresenta o resultado."""
    metrics, y_pred, y_prob = run_ibov_pipeline()
    prever_tendencia(y_pred[-1], y_prob)


if __name__ == "__main__":
    main()
