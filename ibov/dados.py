"""Coleta e validação dos históricos do Yahoo Finance."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import numpy as np
import pandas as pd
import yfinance as yf

from .config import EXTERNAL_TICKERS


def fetch_data(ticker, start, end):
    df = yf.download(
        ticker, start=start, end=end, progress=False, auto_adjust=False,
        multi_level_index=False,
    )
    if df is None or df.empty:
        raise ValueError(f"O Yahoo Finance não retornou dados para {ticker}.")
    # Algumas versões/respostas retornam colunas (Price, Ticker).
    if isinstance(df.columns, pd.MultiIndex):
        ticker_levels = [
            level for level in range(df.columns.nlevels)
            if ticker in df.columns.get_level_values(level)
        ]
        if len(ticker_levels) != 1:
            raise ValueError("Formato de colunas inesperado na resposta do Yahoo Finance.")
        df = df.xs(ticker, axis=1, level=ticker_levels[0])
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    columns = ["open", "high", "low", "close", "volume"]
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no histórico: {sorted(missing)}")
    df = df[columns].apply(pd.to_numeric, errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    df = df.loc[~df.index.duplicated(keep="last")].sort_index()
    if df.empty:
        raise ValueError("O histórico não contém preços e volumes válidos.")
    return df


def fetch_external_data(start, end):
    """Coleta mercados externos; falhas são explícitas, sem omitir séries."""
    return {name: fetch_data(ticker, start, end)["close"]
            for name, ticker in EXTERNAL_TICKERS.items()}


def fetch_interest_data(start, end):
    """Meta Selic (SGS 432), em % a.a.; fim exclusivo e consultas anuais."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    parts = []
    cursor = start
    while cursor < end:
        stop = min(cursor + pd.DateOffset(years=1), end)
        query = urlencode({"formato": "json", "dataInicial": cursor.strftime("%d/%m/%Y"),
                           "dataFinal": (stop - pd.Timedelta(days=1)).strftime("%d/%m/%Y")})
        for attempt in range(3):
            try:
                with urlopen("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?" + query,
                             timeout=20) as response:
                    frame = pd.DataFrame(json.load(response))
                break
            except (URLError, TimeoutError) as exc:
                if isinstance(exc, HTTPError) and exc.code < 500:
                    raise
                if attempt == 2:
                    raise

        if frame.empty or not {"data", "valor"}.issubset(frame.columns):
            raise ValueError("O Banco Central não retornou a meta Selic esperada.")
        values = pd.to_numeric(frame["valor"], errors="raise")
        dates = pd.to_datetime(frame["data"], format="%d/%m/%Y")
        parts.append(pd.Series(values.to_numpy(), index=dates, name="selic"))
        cursor = stop
    if not parts:
        raise ValueError("Período vazio para a meta Selic.")
    series = pd.concat(parts).sort_index()
    if series.index.has_duplicates or not np.isfinite(series).all() or (series < 0).any():
        raise ValueError("Meta Selic inválida.")
    return series.loc[(series.index >= start) & (series.index < end)]
