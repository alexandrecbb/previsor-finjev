"""Embeddings semânticos locais e fixos, sem ajuste sobre o acervo de notícias."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
PROTOCOL = {"model": MODEL, "revision": REVISION, "pooling": "masked_mean_l2_v1",
            "max_length": 128, "dimensions": 384}


@lru_cache(maxsize=2)
def _load_model(local_files_only):
    # Importar o projeto não instala dependências nem baixa pesos.
    from transformers import AutoTokenizer, AutoModel
    options = {"revision": REVISION, "local_files_only": local_files_only, "trust_remote_code": False}
    tokenizer = AutoTokenizer.from_pretrained(MODEL, **options)
    model = AutoModel.from_pretrained(MODEL, use_safetensors=True, **options)
    model.to("cpu")
    model.eval()
    return tokenizer, model


def normalized_vectors(values, count):
    """Rejeita respostas inválidas, inclusive vetores nulos e não finitos."""
    vectors = np.asarray(values, dtype=np.float32)
    if vectors.shape != (count, PROTOCOL["dimensions"]) or not np.isfinite(vectors).all():
        raise ValueError("Embeddings semânticos inválidos.")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or (norms <= 0).any():
        raise ValueError("Embedding semântico nulo.")
    return vectors / norms


class SemanticEmbeddings:
    """Mean pooling com máscara e normalização L2, conforme o modelo publicado.

    O modelo aceita português. São usados os primeiros 128 tokens; o restante
    da notícia não altera seu vetor. O cache não armazena textos nem resultados
    de mercado. Nenhum vocabulário ou transformador é ajustado nas notícias.
    """

    metadata = PROTOCOL

    def __init__(self, *, cache_dir=".cache/embeddings", batch_size=16, local_files_only=False):
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("Tamanho do lote deve ser inteiro positivo.")
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self.local_files_only = local_files_only

    def _infer(self, texts):
        import torch
        tokenizer, model = _load_model(self.local_files_only)
        tokens = tokenizer(texts, padding=True, truncation=True, max_length=PROTOCOL["max_length"],
                           return_tensors="pt")
        with torch.inference_mode():
            hidden = model(**tokens).last_hidden_state
            mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        return pooled.cpu().numpy()

    def encode(self, texts):
        texts = list(texts)
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embeddings exigem textos não vazios.")
        if not texts:
            return np.empty((0, PROTOCOL["dimensions"]), dtype=np.float32)
        records, missing, keys = {}, {}, []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            identity = {**self.metadata, "content_sha256": digest}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            keys.append(key)
            if key in records or key in missing:
                continue
            path = self.cache_dir / (key + ".json")
            if path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("identity") != identity:
                    raise ValueError("Cache de embeddings incompatível.")
                vector = np.asarray([record["vector"]], dtype=np.float32)
                normalized_vectors(vector, 1)
                if not np.allclose(np.linalg.norm(vector, axis=1), 1., atol=1e-5):
                    raise ValueError("Cache de embeddings sem normalização L2.")
                # Reutiliza os mesmos bits; renormalizar a cada leitura pode
                # alterar empates numéricos em consultas idênticas.
                records[key] = vector[0]
            else:
                missing[key] = (text, path, identity)
        items = list(missing.items())
        for start in range(0, len(items), self.batch_size):
            batch = items[start:start + self.batch_size]
            vectors = normalized_vectors(self._infer([value[0] for _, value in batch]), len(batch))
            for (key, (_, path, identity)), vector in zip(batch, vectors):
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"identity": identity, "vector": vector.tolist()},
                                               allow_nan=False), encoding="utf-8")
                temporary.replace(path)
                records[key] = vector
        return np.stack([records[key] for key in keys])
