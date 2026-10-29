"""Memória persistente de notícias, com recuperação temporal inspirada no FinMem."""
import hashlib
import json
import math
import sqlite3

import numpy as np
import pandas as pd

from .noticias import timestamp
from .sentimento import validate_sentiment
from .embeddings import SemanticEmbeddings, PROTOCOL

# Escalas de decaimento do exemplo TSLA do FinMem, medidas aqui em dias.
LAYERS = {"short": (3, .92), "mid": (90, .967), "long": (365, .988)}
LIFECYCLE_CONFIG = {"version": "layered_daily_v1", "promotion": {"short": 60., "mid": 80.},
                    "demotion": {"mid": 60., "long": 80.},
                    "min_recency": .05, "min_importance": 5.}
RETRIEVAL_CONFIG = {"version": "semantic_cosine_recency_importance_v2_layered", "embedding": PROTOCOL,
                    "score": "cosine + recency + importance", "layers": LAYERS,
                    "lifecycle": LIFECYCLE_CONFIG}


class NewsMemory:
    """Armazena episódios e consultas; embeddings locais com pesos baixados sob demanda."""

    def __init__(self, path, *, encoder=None):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL, content_hash TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY, query_id TEXT NOT NULL, created_at TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_feedback (
                id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, created_at TEXT NOT NULL,
                delta REAL NOT NULL, query_id TEXT NOT NULL,
                UNIQUE(memory_id, query_id));
            CREATE TABLE IF NOT EXISTS retrievals (
                query_id TEXT PRIMARY KEY, cutoff TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decision_outcomes (
                query_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observed_results (
                query_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                reflection_id TEXT);
        ''')
        self.encoder = encoder if encoder is not None else SemanticEmbeddings()

    def close(self):
        self.db.close()

    def add(self, episode):
        """Inclui versão com horários explícitos; alterações exigem novo id.

        event_id agrupa republicações do mesmo acontecimento. outcome só pode
        ser usado após outcome_at; horizon e asset evitam misturar resultados.
        """
        row = dict(episode)
        required = {"id", "event_id", "text", "published_at", "available_at",
                    "classified_at", "model", "prompt_version", "asset", "horizon"}
        if not required.issubset(row):
            raise ValueError("Episódio incompleto: " + ", ".join(sorted(required - row.keys())))
        for key in required - {"horizon"}:
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"Campo inválido: {key}")
        for key in ["published_at", "available_at", "classified_at"]:
            row[key] = timestamp(row[key]).isoformat()
        if timestamp(row["available_at"]) < timestamp(row["published_at"]):
            raise ValueError("Disponibilidade antecede publicação.")
        if isinstance(row["horizon"], bool) or not isinstance(row["horizon"], int) or row["horizon"] < 1:
            raise ValueError("Horizonte deve ser inteiro positivo.")
        row.setdefault("layer", "short")
        row.setdefault("importance", 50.)
        if row["layer"] not in LAYERS or not math.isfinite(row["importance"]) or not 0 <= row["importance"] <= 100:
            raise ValueError("Camada ou importância inválida.")
        if row.get("outcome") is not None:
            if row["outcome"] not in (0, 1) or not row.get("outcome_at"):
                raise ValueError("Resultado exige classe 0/1 e outcome_at.")
            row["outcome_at"] = timestamp(row["outcome_at"]).isoformat()
            if timestamp(row["outcome_at"]) <= timestamp(row["available_at"]):
                raise ValueError("Resultado deve ocorrer após disponibilidade.")
        if "context" in row:
            if not isinstance(row["context"], dict):
                raise ValueError("Contexto histórico deve ser objeto JSON conhecido na disponibilidade.")
        if row.get("sentiment") is not None:
            validate_sentiment(row["sentiment"], row["text"])
            if timestamp(row["classified_at"]) < timestamp(row["sentiment"]["classified_at"]):
                raise ValueError("Classificação do episódio antecede o sentimento FinBERT.")
        digest = hashlib.sha256(" ".join(row["text"].lower().split()).encode()).hexdigest()
        payload = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
        old = self.db.execute("SELECT payload FROM episodes WHERE id=?", (row["id"],)).fetchone()
        if old and old[0] != payload:
            raise ValueError("Id existente é imutável; forneça novo id para nova versão.")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO episodes VALUES (?, ?, ?, ?)",
                            (row["id"], row["event_id"], digest, payload))

    def feedback(self, memory_id, *, feedback_id, query_id, delta, created_at):
        """Registra crédito explícito após resultado conhecido, uma vez por decisão.

        delta está na escala de importância 0–100. Consultar não reforça memória.
        O episódio original permanece imutável e feedback futuro não é retroativo.
        """
        if (not isinstance(feedback_id, str) or not feedback_id.strip()
                or isinstance(delta, bool) or not isinstance(delta, (int, float))
                or not math.isfinite(delta) or not -100 <= delta <= 100):
            raise ValueError("Identificador ou ajuste de importância inválido.")
        created_at = timestamp(created_at)
        record = self.db.execute("SELECT cutoff, result FROM retrievals WHERE query_id=?",
                                 (query_id,)).fetchone()
        if record is None:
            raise ValueError("Previsão original inexistente.")
        original = json.loads(record["result"])
        if memory_id not in {r["id"] for r in original["memories"]}:
            raise ValueError("Memória não participou da decisão.")
        reviews = self.db.execute("SELECT payload FROM reflections WHERE query_id=?", (query_id,))
        if not any(timestamp(json.loads(r[0])["created_at"]) <= created_at for r in reviews):
            raise ValueError("Feedback exige reflexão já disponível com resultado observado.")
        with self.db:
            self.db.execute("INSERT INTO memory_feedback VALUES (?, ?, ?, ?, ?)",
                            (feedback_id, memory_id, created_at.isoformat(), delta, query_id))

    def record_outcome(self, query_id, *, net_return, outcome_at, created_at):
        """Distribui o sinal do resultado líquido às memórias da decisão.

        O chamador informa o retorno efetivo da operação, incluindo custos e
        posição, sem inferir lucro de uma simples classe de alta/baixa. Cada
        memória recebe cinco pontos por acerto líquido e perde cinco por perda.
        É uma adaptação por evento do reforço do FinMem, sem crédito causal.
        """
        if (isinstance(net_return, bool) or not isinstance(net_return, (int, float))
                or not math.isfinite(net_return)):
            raise ValueError("Retorno líquido deve ser numérico e finito.")
        record = self.db.execute("SELECT cutoff, result FROM retrievals WHERE query_id=?", (query_id,)).fetchone()
        if record is None:
            raise ValueError("Previsão original inexistente.")
        outcome_at, created_at = timestamp(outcome_at), timestamp(created_at)
        if not timestamp(record["cutoff"]) < outcome_at <= created_at:
            raise ValueError("Resultado deve ser posterior à decisão e conhecido na criação.")
        original = json.loads(record["result"])
        signal = int(net_return > 0) - int(net_return < 0)
        row = {"query_id": query_id, "net_return": net_return, "signal": signal,
               "outcome_at": outcome_at.isoformat(), "created_at": created_at.isoformat(),
               "action": original["action"], "asset": original["state"]["asset"],
               "horizon": original["state"]["horizon"],
               "memory_ids": [r["id"] for r in original["memories"]],
               "policy": "realized_net_return_sign_step_5_v1", "delta": signal * 5.}
        payload = json.dumps(row, sort_keys=True, allow_nan=False)
        old = self.db.execute("SELECT payload FROM decision_outcomes WHERE query_id=?", (query_id,)).fetchone()
        if old:
            if old[0] != payload:
                raise ValueError("Resultado já registrado é imutável.")
            return row
        # A restrição por memória/decisão impede crédito duplo com feedback manual.
        with self.db:
            self.db.execute("INSERT INTO decision_outcomes VALUES (?, ?)", (query_id, payload))
            for memory_id in row["memory_ids"]:
                feedback_id = hashlib.sha256(json.dumps(["outcome", query_id, memory_id]).encode()).hexdigest()
                self.db.execute("INSERT INTO memory_feedback VALUES (?, ?, ?, ?, ?)",
                                (feedback_id, memory_id, created_at.isoformat(), row["delta"], query_id))
        return row

    def memory_state(self, memory_id, cutoff):
        """Reconstitui camadas em passos de 24h desde a disponibilidade.

        A evolução independe da ordem e frequência de consultas. Exclusão lógica
        preserva episódios e decisões para auditoria e consultas históricas.
        """
        stored = self.db.execute("SELECT payload FROM episodes WHERE id=?", (memory_id,)).fetchone()
        if stored is None:
            raise ValueError("Memória inexistente.")
        row = json.loads(stored[0])
        cutoff, start = timestamp(cutoff), timestamp(row["available_at"])
        if cutoff <= start:
            raise ValueError("Memória ainda indisponível no corte.")
        layer, importance, age = row["layer"], float(row["importance"]), 0.
        current = start
        deleted = False
        transitions = []
        feedback = sorted((timestamp(r["created_at"]), r["id"], r["delta"])
                          for r in self.db.execute("SELECT * FROM memory_feedback WHERE memory_id=?", (memory_id,))
                          if timestamp(r["created_at"]) < cutoff)
        def transition(at):
            nonlocal layer, age
            previous = layer
            if importance >= LIFECYCLE_CONFIG["promotion"].get(layer, math.inf):
                layer = {"short": "mid", "mid": "long"}[layer]
            elif importance < LIFECYCLE_CONFIG["demotion"].get(layer, -math.inf):
                layer = {"mid": "short", "long": "mid"}[layer]
            if layer != previous:
                transitions.append({"at": at.isoformat(), "from": previous, "to": layer})
                if LAYERS[layer][0] > LAYERS[previous][0]:
                    age = 0.
        # Inicialização determinística; importância alta já pode justificar promoção.
        transition(start)
        tick = start + pd.Timedelta(days=1)
        events = [(at, 1, key, delta) for at, key, delta in feedback]
        while tick < cutoff:
            events.append((tick, 0, "", 0.))
            tick += pd.Timedelta(days=1)
        for at, kind, _, delta in sorted(events) + [(cutoff, 2, "", 0.)]:
            days = (at - current).total_seconds() / 86400
            scale, factor = LAYERS[layer]
            importance *= factor ** days
            age += days
            current = at
            recency = math.exp(-age / scale)
            if importance < LIFECYCLE_CONFIG["min_importance"] or recency < LIFECYCLE_CONFIG["min_recency"]:
                deleted = True
                break
            if kind == 1:
                importance = min(100., max(0., importance + delta))
                if importance < LIFECYCLE_CONFIG["min_importance"]:
                    deleted = True
                    break
            if kind != 2:
                transition(at)
        return {"layer": layer, "importance": importance, "recency": math.exp(-age / LAYERS[layer][0]),
                "deleted": deleted, "transitions": transitions}

    def retrieve(self, text, cutoff, *, asset="^BVSP", horizon=3, model="jev-1.14.0",
                prompt_version="ibov-news-v1", top_k=10, min_similarity=.15,
                retrospective=False, exclude_event_ids=()):
        """Recupera episódios disponíveis, sem transformar resultados em votos.

        Consultas não reforçam memórias automaticamente: repetir uma consulta
        não fabrica evidência. Os resultados e seus componentes são auditáveis.
        """
        cutoff = timestamp(cutoff)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Consulta vazia.")
        if top_k < 1 or horizon < 1 or not 0 <= min_similarity <= 1:
            raise ValueError("Parâmetros de recuperação inválidos.")
        candidates = []
        for stored in self.db.execute("SELECT payload, content_hash FROM episodes ORDER BY id"):
            row = json.loads(stored[0])
            if row["event_id"] in exclude_event_ids:
                continue
            if (row["asset"], row["horizon"], row["model"], row["prompt_version"]) != (asset, horizon, model, prompt_version):
                continue
            ready = max(timestamp(row["published_at"]), timestamp(row["available_at"]))
            if not retrospective:
                ready = max(ready, timestamp(row["classified_at"]))
            if ready >= cutoff:
                continue
            state = self.memory_state(row["id"], cutoff)
            if state["deleted"]:
                continue
            row["memory_state"] = state
            row["content_hash"] = stored[1]
            candidates.append(row)
        selected = []
        if candidates:
            # Filtra disponibilidade antes de gerar vetores. Os pesos são fixos:
            # incluir notícias futuras não altera vetores nem ranking do passado.
            vectors = self.encoder.encode([text] + [r["text"] for r in candidates])
            similarities = np.clip(vectors[1:] @ vectors[0], -1., 1.)
            for row, similarity in zip(candidates, similarities):
                if similarity < min_similarity or similarity <= 0:
                    continue
                state = row["memory_state"]
                recency = state["recency"]
                importance = state["importance"] / 100
                selected.append({"id": row["id"], "event_id": row["event_id"],
                                 "content_hash": row["content_hash"], "layer": state["layer"],
                                 "transitions": state["transitions"],
                                 "text": row["text"], "published_at": row["published_at"],
                                 "context": row.get("context", {}),
                                 "sentiment": row.get("sentiment") if retrospective or not row.get("sentiment")
                                 or timestamp(row["sentiment"]["classified_at"]) < cutoff else None,
                                 "outcome": row.get("outcome") if row.get("outcome_at") and timestamp(row["outcome_at"]) < cutoff else None,
                                 "similarity": float(similarity),
                                 "recency": recency, "importance": importance,
                                 "score": float(similarity + recency + importance)})
        selected.sort(key=lambda r: (-r["score"], r["id"]))
        unique, events, hashes = [], set(), set()
        for row in selected:
            if row["event_id"] in events or row["content_hash"] in hashes:
                continue
            events.add(row["event_id"])
            hashes.add(row["content_hash"])
            unique.append(row)
            if len(unique) == top_k:
                break
        config = {**RETRIEVAL_CONFIG, "embedding": self.encoder.metadata,
                  "min_similarity": min_similarity, "top_k": top_k}
        return {"n_events": len(unique), "retrospective": retrospective, "memories": unique,
                "retrieval_config": config}

    def predict(self, text, cutoff, *, context, decision_model, query_id=None, sentiment=None,
                max_text_chars=None, **options):
        """Decisão contextual do modelo; o ranking apenas seleciona experiências.

        context exige available_at e data. O chamador deve fornecer somente
        indicadores e notícias efetivamente disponíveis naquele horário.
        """
        cutoff = timestamp(cutoff)
        if max_text_chars is not None and (isinstance(max_text_chars, bool)
                                          or not isinstance(max_text_chars, int) or max_text_chars < 1):
            raise ValueError("Limite de texto deve ser inteiro positivo ou None.")
        if not isinstance(context, dict) or "data" not in context or "available_at" not in context:
            raise ValueError("Contexto exige data e available_at com fuso.")
        if timestamp(context["available_at"]) > cutoff:
            raise ValueError("Contexto ainda não disponível no corte.")
        if sentiment is not None:
            validate_sentiment(sentiment, text)
            if not options.get("retrospective", False) and timestamp(sentiment["classified_at"]) > cutoff:
                raise ValueError("Sentimento atual ainda não disponível no corte.")
        if query_id is not None and self.db.execute(
                "SELECT 1 FROM retrievals WHERE query_id=?", (query_id,)).fetchone():
            raise ValueError("query_id já utilizado.")
        retrieved = self.retrieve(text, cutoff, **options)
        ids = {row["id"] for row in retrieved["memories"]}
        reflections = []
        for stored in self.db.execute("SELECT payload FROM reflections ORDER BY created_at, id"):
            row = json.loads(stored[0])
            if timestamp(row["created_at"]) < cutoff and ids.intersection(row["memory_ids"]):
                reflections.append(row)
        state = {"cutoff": cutoff.isoformat(), "asset": options.get("asset", "^BVSP"),
                 "horizon": options.get("horizon", 3), "current_news": text,
                 "current_sentiment": sentiment,
                 "current_context": context, **retrieved, "reflections": reflections[-10:]}
        if max_text_chars is not None:
            # O sentimento pertence ao texto completo validado acima; o trecho
            # enviado ao Jev é identificado sem alterar o episódio ou seu hash.
            state["current_news"] = text[:max_text_chars]
            state["current_news_original_length"] = len(text)
            state["max_text_chars"] = max_text_chars
            state["memories"] = [{**row, "text": row["text"][:max_text_chars],
                                  "original_text_length": len(row["text"])}
                                 for row in retrieved["memories"]]
        json.dumps(state, allow_nan=False)
        decision = decision_model(state)
        if not isinstance(decision, dict):
            raise ValueError("Modelo deve retornar action buy/sell/hold.")
        action = decision.get("action")
        # Compatibilidade de leitura com modelos simulados e contratos anteriores.
        if action is None:
            action = {"up": "buy", "down": "sell", "abstain": "hold"}.get(decision.get("direction"))
        if action not in ("buy", "sell", "hold"):
            raise ValueError("Modelo deve retornar action buy/sell/hold.")
        # Uma decisão pode divergir de todos os resultados históricos recuperados.
        result = {**retrieved, "action": action,
                  "action_pt": {"buy": "comprar", "sell": "vender", "hold": "manter"}[action],
                  "prediction": {"buy": 1, "sell": 0, "hold": None}[action],
                  "decision": decision, "state": state}
        if query_id is not None:
            with self.db:
                self.db.execute("INSERT INTO retrievals VALUES (?, ?, ?)",
                                (query_id, cutoff.isoformat(), json.dumps(result, allow_nan=False)))
        return result

    def register_result(self, query_id, *, outcome, outcome_at, observed_at, net_return=None):
        """Enfileira resultado observado sem fabricar retorno ou crédito por memória."""
        record = self.db.execute("SELECT cutoff FROM retrievals WHERE query_id=?", (query_id,)).fetchone()
        if record is None:
            raise ValueError("Previsão original inexistente.")
        outcome_at, observed_at = timestamp(outcome_at), timestamp(observed_at)
        if (isinstance(outcome, bool) or outcome not in (0, 1)
                or not timestamp(record[0]) < outcome_at <= observed_at):
            raise ValueError("Resultado ou cronologia de observação inválidos.")
        if net_return is not None and (isinstance(net_return, bool) or not isinstance(net_return, (int, float))
                                       or not math.isfinite(net_return)):
            raise ValueError("Retorno líquido deve ser numérico e finito.")
        row = {"query_id": query_id, "outcome": outcome, "outcome_at": outcome_at.isoformat(),
               "observed_at": observed_at.isoformat(), "net_return": net_return}
        payload = json.dumps(row, sort_keys=True, allow_nan=False)
        old = self.db.execute("SELECT payload FROM observed_results WHERE query_id=?", (query_id,)).fetchone()
        if old and old[0] != payload:
            raise ValueError("Resultado observado já registrado é imutável.")
        if not old and self.db.execute("SELECT 1 FROM memory_feedback WHERE query_id=?", (query_id,)).fetchone():
            raise ValueError("Decisão já recebeu feedback; não é permitido crédito duplo.")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO observed_results VALUES (?, ?, NULL)", (query_id, payload))
        return row

    def process_pending_reflections(self, reflection_model, *, as_of, limit=1, query_ids=None):
        """Revisa resultados maduros e aplica feedback específico, de forma retomável.

        Uma falha deixa o resultado pendente, sem reforço parcial ou abstenção
        inventada. Reflexões produzidas hoje nunca recebem uma data passada.
        """
        as_of = timestamp(as_of)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("Limite de reflexões deve ser inteiro não negativo.")
        pending = [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload FROM observed_results WHERE reflection_id IS NULL")]
        pending.sort(key=lambda row: (row["observed_at"], row["query_id"]))
        eligible = [row for row in pending if timestamp(row["observed_at"]) <= as_of
                    and timestamp(row["outcome_at"]) <= as_of
                    and (query_ids is None or row["query_id"] in query_ids)]
        results = []
        for row in eligible[:limit]:
            reflection_id = "auto:" + hashlib.sha256(row["query_id"].encode()).hexdigest()
            def complete_review(state):
                review = reflection_model(state)
                expected = {r["id"] for r in state["original"]["memories"]}
                if (not isinstance(review, dict) or not isinstance(review.get("memory_feedback"), dict)
                        or set(review["memory_feedback"]) != expected
                        or review.get("lesson") not in ("consistent", "reconsider", "insufficient")):
                    raise ValueError("Reflexão automática exige feedback explícito para cada memória usada.")
                return review
            result = self.reflect(row["query_id"], reflection_id=reflection_id,
                                  outcome=row["outcome"], outcome_at=row["outcome_at"], created_at=as_of,
                                  net_return=row["net_return"], reflection_model=complete_review)
            with self.db:
                self.db.execute("UPDATE observed_results SET reflection_id=? WHERE query_id=?",
                                (reflection_id, row["query_id"]))
            results.append(result)
        return results

    def reflect(self, query_id, *, reflection_id, outcome, outcome_at, created_at, reflection_model,
                net_return=None):
        """Avalia decisão passada somente após observar seu resultado futuro.

        Reflexões recebem seu horário real de criação e não são retroativas.
        O modelo devolve uma lição estruturada, persistida com a decisão original.
        """
        record = self.db.execute("SELECT cutoff, result FROM retrievals WHERE query_id=?", (query_id,)).fetchone()
        if record is None:
            raise ValueError("Previsão original inexistente.")
        outcome_at, created_at = timestamp(outcome_at), timestamp(created_at)
        if outcome not in (0, 1) or not timestamp(record["cutoff"]) < outcome_at <= created_at:
            raise ValueError("Resultado ou cronologia da reflexão inválidos.")
        if net_return is not None and (isinstance(net_return, bool) or not isinstance(net_return, (int, float))
                                       or not math.isfinite(net_return)):
            raise ValueError("Retorno líquido deve ser numérico e finito.")
        old = self.db.execute("SELECT payload FROM reflections WHERE id=?", (reflection_id,)).fetchone()
        if old:
            row = json.loads(old[0])
            if (row["query_id"] != query_id or row["outcome"] != outcome
                    or timestamp(row["outcome_at"]) != outcome_at or row.get("net_return") != net_return):
                raise ValueError("Reflexão existente é imutável.")
            return row
        if self.db.execute("SELECT 1 FROM memory_feedback WHERE query_id=?", (query_id,)).fetchone():
            raise ValueError("Decisão já recebeu feedback; não é permitido crédito duplo.")
        original = json.loads(record["result"])
        review = reflection_model({"original": original, "observed_outcome": outcome,
                                   "observed_net_return": net_return,
                                   "outcome_at": outcome_at.isoformat()})
        if not isinstance(review, dict) or not review:
            raise ValueError("Reflexão deve retornar objeto não vazio.")
        if review.get("generated_at"):
            created_at = max(created_at, timestamp(review["generated_at"]))
        row = {"id": reflection_id, "query_id": query_id, "created_at": created_at.isoformat(),
               "memory_ids": [r["id"] for r in original["memories"]],
               "outcome": outcome, "outcome_at": outcome_at.isoformat(), "review": review,
               "original_context": original["state"]["current_context"],
               "original_news": original["state"]["current_news"],
               "original_decision": original["decision"]}
        row["net_return"] = net_return
        # Crédito por memória deve ser explícito; acerto da decisão sozinho não
        # demonstra que todas as experiências recuperadas foram úteis.
        adjustments = review.get("memory_feedback", {})
        if not isinstance(adjustments, dict) or any(
                key not in row["memory_ids"] or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not -100 <= value <= 100 for key, value in adjustments.items()):
            raise ValueError("Feedback da reflexão deve mapear memórias usadas para ajustes finitos entre -100 e 100.")
        with self.db:
            self.db.execute("INSERT INTO reflections VALUES (?, ?, ?, ?)",
                            (reflection_id, query_id, created_at.isoformat(), json.dumps(row, allow_nan=False)))
            for memory_id, delta in adjustments.items():
                self.db.execute("INSERT INTO memory_feedback VALUES (?, ?, ?, ?, ?)",
                                (f"{reflection_id}:{memory_id}", memory_id,
                                 created_at.isoformat(), delta, query_id))
        return row



def directional_outcomes(close, *, horizon=3):
    """Alvos em pregões e horário em que o fechamento futuro ficou disponível.

    O índice deve fornecer horários reais de disponibilidade com fuso. Não
    infere horários de fechamento nem preenche pregões ausentes.
    """
    if not isinstance(close, pd.Series) or not isinstance(close.index, pd.DatetimeIndex):
        raise ValueError("Forneça série de fechamentos com índice temporal.")
    if close.index.tz is None or close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise ValueError("Índice deve ser único, ordenado e conter fuso.")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("Horizonte deve ser inteiro positivo.")
    values = pd.to_numeric(close, errors="raise")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Fechamentos devem ser positivos e finitos.")
    future = values.shift(-horizon)
    target = (future > values).astype(float).where(future.notna())
    known = pd.Series(close.index, index=close.index).shift(-horizon)
    return pd.DataFrame({"outcome": target, "outcome_at": known})
