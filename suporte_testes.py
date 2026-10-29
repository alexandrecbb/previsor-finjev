"""Dublê determinístico de embeddings para testes sem pesos ou rede."""
import numpy as np


class FakeEmbeddings:
    metadata = {"model": "simulado-sem-rede", "dimensions": 384}

    def encode(self, texts):
        result = np.zeros((len(texts), 384), dtype=np.float32)
        result[:, 0] = 1.
        return result
