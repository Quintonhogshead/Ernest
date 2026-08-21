"""Embeddings + vector math for the library.

Embeddings run on an ``openai:`` model (Anthropic doesn't ship an embeddings
endpoint). Vectors are packed to float32 BLOBs for SQLite; search does a linear
cosine scan, which beats a vector DB at personal scale (tens of thousands of
chunks).
"""

from __future__ import annotations

import math
import struct

from . import ConfigError
from .config import Config
from .llm import parse_spec

_BATCH = 96


def embed(cfg: Config, texts: list[str]) -> list[list[float]]:
    provider, model = parse_spec(cfg.embed_model)
    if provider != "openai":
        raise ConfigError("embeddings require an openai: model in ERNEST_EMBED_MODEL")
    if not cfg.openai_api_key:
        raise ConfigError("OPENAI_API_KEY is required for embeddings")
    if not texts:
        return []
    import openai

    client = openai.OpenAI(api_key=cfg.openai_api_key)
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        resp = client.embeddings.create(model=model, input=batch)
        out.extend(d.embedding for d in resp.data)
    return out


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
