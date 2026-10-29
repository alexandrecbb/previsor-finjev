"""Execução exclusivamente fictícia, sem conexão com corretoras."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .avaliacao_noticias import sample_episodes
from .decisao_noticias import VERSION
from .memoria import NewsMemory, RETRIEVAL_CONFIG
from .noticias import timestamp


class PaperPortfolio:
    """Cotas fracionárias fictícias: comprar aplica caixa, vender liquida posição."""

    def __init__(self, initial_cash=100000., fee_rate=.001):
        if not math.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("Capital inicial deve ser positivo e finito.")
        if not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise ValueError("Custo deve estar entre zero e um.")
        self.initial_cash = self.cash = float(initial_cash)
        self.units = self.total_fees = 0.
        self.fee_rate = float(fee_rate)

    def value(self, price):
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Preço deve ser positivo e finito.")
        return self.cash + self.units * price

    def context(self, price):
        equity = self.value(price)
        return {"cash": self.cash, "units": self.units, "equity": equity,
                "exposure": self.units * price / equity, "short_selling_allowed": False,
                "leverage_allowed": False, "fractional_units": True,
                "simulation_only": True, "fee_rate": self.fee_rate,
                "instrument": "Cota fictícia do índice de referência ^BVSP; não é ordem de bolsa.",
                "action_policy": {"buy": "Aplicar todo caixa disponível após custos; sem caixa, não operar.",
                                  "sell": "Liquidar a posição existente; sem posição, não operar.",
                                  "hold": "Conservar caixa e cotas, sem negócio."}}

    def execute(self, action, price):
        self.value(price)
        if action not in ("buy", "sell", "hold"):
            raise ValueError("Ação inválida; use buy, sell ou hold.")
        quantity = gross = fee = 0.
        status = "hold"
        if action == "buy" and self.cash > 1e-8:
            gross = self.cash / (1 + self.fee_rate)
            quantity = gross / price
            fee = gross * self.fee_rate
            self.units += quantity
            self.cash = 0.
            status = "filled"
        elif action == "sell" and self.units > 0:
            quantity = self.units
            gross = quantity * price
            fee = gross * self.fee_rate
            self.cash += gross - fee
            self.units = 0.
            status = "filled"
        elif action != "hold":
            status = "no_cash" if action == "buy" else "no_position"
        self.total_fees += fee
        return {"action": action, "status": status, "price": float(price),
                "quantity": quantity, "gross": gross, "fee": fee,
                "cash_after": self.cash, "units_after": self.units}


def simulate_portfolio(episodes, prices, decision_model, *, directory, sample_size=24,
                       warmup_days=90, initial_cash=100000., fee_rate=.001):
    """Decide sem preços futuros; executa na abertura após o corte retrospectivo.

    Índice usado somente como cota fictícia. A carteira é reconstituída na
    retomada; decisões já persistidas não exigem novas chamadas ao Jev.
    """
    if (prices.empty or not isinstance(prices.index, pd.DatetimeIndex) or prices.index.tz is not None
            or not prices.index.is_monotonic_increasing or prices.index.has_duplicates):
        raise ValueError("Preços devem ter datas locais ordenadas e únicas, sem fuso.")
    if not {"open", "close"}.issubset(prices.columns):
        raise ValueError("Simulação exige abertura e fechamento reais.")
    if not np.isfinite(prices[["open", "close"]]).all().all() or (prices[["open", "close"]] <= 0).any().any():
        raise ValueError("Preços de execução inválidos.")
    portfolio = PaperPortfolio(initial_cash, fee_rate)
    sample = sample_episodes(episodes, size=sample_size, warmup_days=warmup_days)
    scheduled = {}
    for episode in sample:
        cutoff = timestamp(episode["cutoff"]).tz_convert("America/Sao_Paulo").tz_localize(None)
        # Sem horário intradiário de abertura: cortes após meia-noite usam o dia seguinte.
        date = cutoff.normalize() + (pd.Timedelta(days=1) if cutoff != cutoff.normalize() else pd.Timedelta(0))
        position = int(prices.index.searchsorted(date))
        if position < len(prices):
            if position in scheduled:
                raise ValueError("Mais de uma decisão na mesma abertura.")
            if position <= episode["base_position"]:
                raise ValueError("Execução deve ocorrer após a data-base conhecida.")
            scheduled[position] = episode
    if not scheduled:
        raise ValueError("Nenhuma decisão com abertura posterior disponível.")
    config = {"initial_cash": initial_cash, "fee_rate": fee_rate, "sample_size": sample_size,
              "warmup_days": warmup_days, "decision_version": VERSION,
              "execution": "next_open", "asset": "^BVSP", "fractional_units": True,
              "strategy": "cash_or_long_v1", "max_text_chars": 4000, "retrieval_config": RETRIEVAL_CONFIG}
    identity = {"config": config, "episodes": episodes,
                "prices_sha256": hashlib.sha256(prices.to_csv().encode()).hexdigest()}
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    memory = NewsMemory(directory / f"carteira_{signature}.sqlite")
    decisions, orders, curve, errors = [], [], [], []
    first = min(scheduled)
    benchmark = PaperPortfolio(initial_cash, fee_rate)
    try:
        # Banco novo e retomável; WAL reduz sincronizações por episódio em cargas grandes.
        memory.db.execute("PRAGMA journal_mode=WAL")
        memory.db.execute("PRAGMA synchronous=NORMAL")
        for row in episodes:
            memory.add({k: v for k, v in row.items() if k not in ("cutoff", "query_context", "base_position")})
        for position in range(first, len(prices)):
            date = prices.index[position].date().isoformat()
            if position in scheduled:
                episode = scheduled[position]
                context = {**episode["query_context"],
                           "data": {**episode["query_context"]["data"],
                                    "position": portfolio.context(float(prices.close.iloc[position-1])),
                                    "simulation_only": True}}
                query_id = "carteira:" + episode["id"]
                stored = memory.db.execute("SELECT result FROM retrievals WHERE query_id=?", (query_id,)).fetchone()
                try:
                    if stored:
                        result = json.loads(stored[0])
                        if result["state"]["current_context"] != context:
                            raise ValueError("Estado da carteira diverge da decisão persistida.")
                    else:
                        result = memory.predict(episode["text"], episode["cutoff"], context=context,
                                                sentiment=episode.get("sentiment"), decision_model=decision_model,
                                                query_id=query_id, retrospective=True, top_k=3,
                                                max_text_chars=config["max_text_chars"],
                                                model=episode["model"], horizon=episode["horizon"],
                                                exclude_event_ids=(episode["event_id"],))
                    order = portfolio.execute(result["action"], float(prices.open.iloc[position]))
                except (ValueError, RuntimeError) as exc:
                    errors.append({"id": episode["id"], "cutoff": episode["cutoff"], "error": str(exc)})
                    break
                decisions.append({"id": episode["id"], "source": episode["source"], "cutoff": episode["cutoff"],
                                  "execution_date": date, "action": result["action"],
                                  "sentiment": episode.get("sentiment", {}).get("label"),
                                  "n_memories": result["n_events"], "decision": result["decision"]})
                orders.append({"id": episode["id"], "date": date, **order})
            if position == first:
                benchmark.execute("buy", float(prices.open.iloc[position]))
            close = float(prices.close.iloc[position])
            curve.append({"date": date, "close": close, "cash": portfolio.cash, "units": portfolio.units,
                          "equity": portfolio.value(close), "buy_hold_equity": benchmark.value(close)})
        values = pd.Series([initial_cash] + [row["equity"] for row in curve])
        final_equity = float(values.iloc[-1])
        benchmark_final = curve[-1]["buy_hold_equity"] if curve else initial_cash
        report = {"simulation_only": True, "retrospective": True, "signature": signature, "config": config,
                  "planned_decisions": len(scheduled), "completed_decisions": len(decisions),
                  "errors": errors, "complete": not errors, "episodes": len(episodes),
                  "first_execution_date": prices.index[first].date().isoformat(),
                  "last_valuation_date": curve[-1]["date"] if curve else None,
                  "final_equity": final_equity, "cash": portfolio.cash, "units": portfolio.units,
                  "return": final_equity / initial_cash - 1,
                  "max_drawdown": float((values / values.cummax() - 1).min()),
                  "fees": portfolio.total_fees,
                  "filled_orders": sum(row["status"] == "filled" for row in orders),
                  "buy_hold_final_equity": benchmark_final, "buy_hold_return": benchmark_final / initial_cash - 1,
                  "buy_hold_fees": benchmark.total_fees, "decisions": decisions, "orders": orders,
                  "limitations": ["Cotas fictícias do índice; não representam execução de BOVA11 ou outro ativo negociável.",
                                  "Textos coletados e classificados hoje; possível contaminação do pré-treinamento Jev.",
                                  "Custos hipotéticos; sem spread, slippage, impostos ou remuneração do caixa.",
                                  "Amostra exploratória de datas, sem reflexões retroativas.",
                                  "Posição final marcada a mercado, sem liquidação compulsória ou custo de saída final."]}
        (directory / "simulacao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        pd.DataFrame(orders).to_csv(directory / "ordens.csv", index=False)
        pd.DataFrame(curve).to_csv(directory / "carteira_diaria.csv", index=False)
        return report
    finally:
        memory.close()
