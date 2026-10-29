"""Sentimento financeiro em português, com inferência local e cache auditável."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .noticias import timestamp

FINBERT_MODEL = "lucas-leme/FinBERT-PT-BR"
FINBERT_REVISION = "c3bf75c85f9b1b0dd257d688822d64390420936c"
LABELS = ("positive", "negative", "neutral")
SENTIMENT_VERSION = "finbert-pt-br-v1"


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_sentiment(record, text=None):
    """Valida sem inferir classes a partir da ordem de dicionários ou do preço."""
    try:
        probs = record["probabilities"]
        if set(probs) != set(LABELS):
            raise ValueError()
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               or not 0 <= v <= 1 for v in probs.values()):
            raise ValueError()
        if not math.isclose(sum(probs.values()), 1, abs_tol=1e-5):
            raise ValueError()
        if record["label"] not in probs or probs[record["label"]] != max(probs.values()):
            raise ValueError()
        timestamp(record["classified_at"])
        for key in ("model", "revision", "version", "content_sha256"):
            if not isinstance(record[key], str) or not record[key].strip():
                raise ValueError()
        if text is not None and record["content_sha256"] != text_hash(text):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("Sentimento FinBERT inválido ou incompatível com o texto.") from None
    return record


class FinBertSentiment:
    """Carrega pesos somente na primeira classificação sem cache.

    A ordem 0=positivo, 1=negativo, 2=neutro segue a documentação do autor,
    não o mapeamento de outro FinBERT. O texto é limitado a 512 tokens.
    """

    def __init__(self, *, revision=FINBERT_REVISION, cache_dir=".cache/finbert", batch_size=8,
                 local_files_only=False, predictor=None):
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("batch_size deve ser inteiro positivo.")
        self.revision, self.cache_dir = revision, Path(cache_dir)
        self.batch_size, self.local_files_only = batch_size, local_files_only
        self.predictor = predictor
        self._tokenizer = self._model = self._torch = None

    def _infer(self, texts):
        if self.predictor is not None:
            return self.predictor(texts)
        if self._model is None:
            try:
                import torch
                from transformers import AutoTokenizer, AutoModelForSequenceClassification
            except ImportError:
                raise RuntimeError("Instale requirements.txt para usar FinBERT-PT-BR.") from None
            self._torch = torch
            options = {"revision": self.revision, "local_files_only": self.local_files_only,
                       "trust_remote_code": False}
            self._tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL, **options)
            # O checkpoint fixado publica pytorch_model.bin; não solicita conversão remota.
            model = AutoModelForSequenceClassification.from_pretrained(
                FINBERT_MODEL, use_safetensors=False, **options)
            mapping = {int(k): v.lower() for k, v in model.config.id2label.items()}
            if mapping != dict(enumerate(LABELS)):
                raise ValueError("Classes do checkpoint FinBERT incompatíveis com o protocolo.")
            model.to("cpu")
            model.eval()
            self._model = model
        tokens = self._tokenizer(texts, return_tensors="pt", padding=True,
                                 truncation=True, max_length=512)
        with self._torch.inference_mode():
            scores = self._model(**tokens).logits.softmax(dim=-1).cpu().tolist()
        return [dict(zip(LABELS, row)) for row in scores]

    def classify_many(self, texts):
        """Cache por texto, revisão e protocolo; falhas não viram neutro."""
        texts = list(texts)
        if any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("Forneça textos não vazios.")
        records, pending = {}, {}
        for text in texts:
            digest = text_hash(text)
            identity = {"text": digest, "model": FINBERT_MODEL, "revision": self.revision,
                        "version": SENTIMENT_VERSION}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            path = self.cache_dir / (key + ".json")
            if path.exists():
                record = validate_sentiment(json.loads(path.read_text(encoding="utf-8")), text)
                if any(record[k] != identity[k] for k in ("model", "revision", "version")):
                    raise ValueError("Cache FinBERT incompatível com o protocolo.")
                records[digest] = record
            else:
                pending[digest] = (text, path)
        items = list(pending.items())
        for start in range(0, len(items), self.batch_size):
            batch = items[start:start + self.batch_size]
            scores = self._infer([value[0] for _, value in batch])
            if len(scores) != len(batch):
                raise ValueError("Quantidade de respostas FinBERT inválida.")
            for (digest, (text, path)), probs in zip(batch, scores):
                record = {"model": FINBERT_MODEL, "revision": self.revision,
                          "version": SENTIMENT_VERSION, "content_sha256": digest,
                          "classified_at": datetime.now(timezone.utc).isoformat(),
                          "max_length": 512, "truncation": True,
                          "label": max(probs, key=probs.get), "probabilities": probs}
                validate_sentiment(record, text)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                temporary.replace(path)
                records[digest] = record
        return [dict(records[text_hash(text)]) for text in texts]

    def __call__(self, text):
        return self.classify_many([text])[0]


def enrich_news(rows, classifier):
    """Preserva os textos e horários originais; classificar hoje não retroage."""
    rows = list(rows)
    records = classifier.classify_many([row["text"] for row in rows])
    enriched = []
    for row, sentiment in zip(rows, records):
        classified = timestamp(sentiment["classified_at"])
        if row.get("classified_at"):
            classified = max(classified, timestamp(row["classified_at"]))
        enriched.append({**row, "sentiment": sentiment, "classified_at": classified.isoformat(),
                         "classification_mode": "finbert_sentiment"})
    return enriched
