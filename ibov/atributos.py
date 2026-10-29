"""Transformações causais, indicadores técnicos e definição do alvo."""

import numpy as np
import pandas as pd
from ta.volatility import BollingerBands, AverageTrueRange
from ta.momentum import StochasticOscillator, RSIIndicator
from ta.volume import OnBalanceVolumeIndicator, ChaikinMoneyFlowIndicator
from ta.trend import MACD, ADXIndicator, EMAIndicator, PSARIndicator

from .config import ALPHA_SMOOTH, FEATURES


def exp_smooth(series, alpha=0.7):
    return series.ewm(alpha=alpha, adjust=False).mean()


def apply_smoothing(df, alpha):
    df = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[f"{col}_s"] = df[col] if alpha is None else exp_smooth(df[col], alpha)
    return df


def compute_indicators(df):
    if len(df) < 50:
        raise ValueError("São necessários pelo menos 50 pregões para calcular os indicadores.")
    d = df.copy()
    high, low, close, volume = d["high_s"], d["low_s"], d["close_s"], d["volume_s"]

    # Tendência
    macd = MACD(close=close)
    d["macd"], d["macd_signal"] = macd.macd(), macd.macd_signal()
    d["adx"] = ADXIndicator(high=high, low=low, close=close, window=14).adx()
    d["psar"] = PSARIndicator(high=high, low=low, close=close).psar()
    d["ema_21"] = EMAIndicator(close=close, window=21).ema_indicator()
    d["ema_50"] = EMAIndicator(close=close, window=50).ema_indicator()

    # Momento
    d["rsi"] = RSIIndicator(close=close, window=14).rsi()
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    d["stoch_k"], d["stoch_d"] = stoch.stoch(), stoch.stoch_signal()

    # Volatilidade
    bb = BollingerBands(close=close, window=20, window_dev=2)
    d["bb_h"], d["bb_l"] = bb.bollinger_hband(), bb.bollinger_lband()
    d["atr"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    # Volume
    d["obv"] = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    d["cmf"] = ChaikinMoneyFlowIndicator(high=high, low=low, close=close, volume=volume, window=20).chaikin_money_flow()

    return d


def prepare_features(raw, *, alpha=ALPHA_SMOOTH, feature_set="relative"):
    """Calcula atributos causais; versões relativas dispensam níveis do índice."""
    if feature_set == "dual_smoothing":
        if alpha is None:
            raise ValueError("dual_smoothing exige alpha para a versão suavizada.")
        smooth = prepare_features(raw, alpha=alpha, feature_set="relative")
        original = prepare_features(raw, alpha=None, feature_set="relative")
        # Retornos e medidas calculadas diretamente no OHLCV não são duplicados.
        indicators = ["adx", "rsi", "stoch_k", "stoch_d", "cmf",
                      "macd_relative", "macd_signal_relative", "atr_relative",
                      "distance_ema_21", "distance_ema_50", "distance_psar",
                      "ema_ratio", "bb_position", "bb_width", "obv_change"]
        return smooth.join(original[indicators].add_suffix("_unsmoothed"))
    ind = compute_indicators(apply_smoothing(raw, alpha))
    if feature_set == "legacy":
        return ind[FEATURES].replace([np.inf, -np.inf], np.nan)
    if feature_set not in {"relative", "combined"}:
        raise ValueError("feature_set deve ser legacy, relative ou combined.")
    close = ind["close_s"].replace(0, np.nan)
    relative = ind[["adx", "rsi", "stoch_k", "stoch_d", "cmf"]].copy()
    for name in ["macd", "macd_signal", "atr"]:
        relative[name + "_relative"] = ind[name] / close
    for name in ["ema_21", "ema_50", "psar"]:
        relative["distance_" + name] = close / ind[name].replace(0, np.nan) - 1
    relative["ema_ratio"] = ind["ema_21"] / ind["ema_50"].replace(0, np.nan) - 1
    width = (ind["bb_h"] - ind["bb_l"]).replace(0, np.nan)
    relative["bb_position"] = (close - ind["bb_l"]) / width
    relative["bb_width"] = width / close
    for lag in [1, 2, 3, 5, 10]:
        relative[f"return_{lag}"] = raw["close"].pct_change(lag, fill_method=None)
    returns = raw["close"].pct_change(fill_method=None)
    for window in [5, 20]:
        relative[f"volatility_{window}"] = returns.rolling(window).std()
    relative["volume_relative"] = raw["volume"] / raw["volume"].rolling(20).mean().replace(0, np.nan)
    relative["obv_change"] = ind["obv"].diff(5) / ind["volume_s"].rolling(5).sum().replace(0, np.nan)
    relative["intraday_return"] = raw["close"] / raw["open"].replace(0, np.nan) - 1
    relative["daily_range"] = (raw["high"] - raw["low"]) / raw["close"].replace(0, np.nan)
    if feature_set == "combined":
        relative = relative.join(ind[[name for name in FEATURES if name not in relative]])
    return relative.replace([np.inf, -np.inf], np.nan)


def external_features(index, external_data):
    """Usa apenas fechamentos de datas anteriores à data-base brasileira.

    Defasagem conservadora evita depender dos horários de fechamento estrangeiros.
    Feriados usam a última observação anterior, com validade máxima de sete dias.
    Não preenche para trás nem utiliza dados macroeconômicos revisados.
    """
    if not external_data:
        raise ValueError("Dados externos vazios.")
    if not isinstance(index, pd.DatetimeIndex) or index.tz is not None:
        raise ValueError("Datas locais devem ser DatetimeIndex sem fuso horário.")
    result = pd.DataFrame(index=index)
    for name, source in external_data.items():
        series = pd.to_numeric(source, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if (not isinstance(series.index, pd.DatetimeIndex) or series.index.tz is not None
                or series.index.has_duplicates or not series.index.is_monotonic_increasing):
            raise ValueError("Séries externas devem ter datas únicas, ordenadas e sem fuso.")
        if series.empty or ((series < 0).any() if name == "selic" else (series <= 0).any()):
            raise ValueError(f"Fechamentos externos inválidos: {name}.")
        values = pd.DataFrame(index=series.index)
        if name == "selic":
            values["ext_selic_level"] = series
            values["ext_selic_change_1"] = series.diff()
            values["ext_selic_change_30"] = series.diff(30)
        else:
            values[f"ext_{name}_return_1"] = series.pct_change(fill_method=None)
            values[f"ext_{name}_return_5"] = series.pct_change(5, fill_method=None)
            values[f"ext_{name}_volatility_20"] = series.pct_change(fill_method=None).rolling(20).std()
            if name == "vix":
                values["ext_vix_level"] = series
        # Normaliza para comparar datas, nunca horários incompletos do mesmo dia.
        values.index = values.index.normalize()
        if values.index.has_duplicates:
            raise ValueError("Cada série externa deve conter no máximo uma observação por dia.")
        aligned = pd.merge_asof(pd.DataFrame({"date": index.normalize()}),
                                values.rename_axis("date").reset_index(), on="date",
                                direction="backward", allow_exact_matches=False,
                                tolerance=pd.Timedelta(days=7))
        aligned.index = index
        result = result.join(aligned.drop(columns="date"))
    return result


def make_target(df, horizon):
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("O horizonte deve ser um número inteiro positivo de pregões.")
    future = df["close"].shift(-horizon)
    target = (future > df["close"]).astype(float)
    return target.where(future.notna() & df["close"].notna()).rename("target")
