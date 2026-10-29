"""Configurações padrão e espaço de busca dos modelos."""

TICKER = "^BVSP"
ALPHA_SMOOTH = 0.7
HORIZON_DAYS = 3
FEATURE_IMPORTANCE_THRESHOLD = 0.04
RANDOM_STATE = 42
N_ITER_RANDOM_SEARCH = 50
FEATURES = [
    "macd", "macd_signal", "adx", "psar", "ema_21", "ema_50", "rsi",
    "stoch_k", "stoch_d", "bb_h", "bb_l", "atr", "obv", "cmf",
]
PARAM_GRID = {
    "n_estimators": [200, 500, 1000],             # Limite para a parada antecipada.
    "learning_rate": [0.01, 0.05, 0.1],             # Passos bem lentos
    "max_depth": [2, 3, 4],                         # A "Poda" agressiva (árvores rasas)
    "subsample": [0.5, 0.7, 0.9],                   # Usa apenas uma fração dos dias em cada árvore
    "colsample_bytree": [0.5, 0.7, 0.9],            # Usa apenas uma fração dos indicadores
    "gamma": [0, 0.1, 1, 5],
    "min_child_weight": [1, 5, 10, 20],
    "reg_alpha": [0, 0.1, 1, 10],
    "reg_lambda": [1, 10, 50]                       # Regularização L2 (Suaviza o peso dos indicadores bons)
}
EXTERNAL_TICKERS = {"usdbrl": "BRL=X", "sp500": "^GSPC", "vix": "^VIX", "brent": "BZ=F"}
