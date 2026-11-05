"""Politika dokümanları için kaynaklı retrieval.

Chunking: her '## Başlık' bölümü bir chunk (politikalar kısa ve bölüm bazlı yazıldı).
Her sonuç kaynak taşır: doküman adı + bölüm + ilgili R-kuralları.
Müşteri Destek Asistanı (Support Agent), şirketin 6 adet Markdown kural dokümanını aramak için bu kodu kullanır.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"
STOP = {"ve", "veya", "bir", "bu", "da", "de", "ile", "icin", "için", "mi", "mı", "mu", "mü", "ne", "nasıl",
        "olur", "ben", "benim", "var", "yok", "o", "şu", "gibi", "kadar", "ise", "ama", "ki"}


@dataclass
class Chunk:
    doc: str
    section: str
    text: str
    rules: list[str]

    @property
    def source(self) -> str:
        return f"{self.doc} › {self.section}"


def _tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def tokenize(text: str, stem: int = 5) -> list[str]:
    toks = re.findall(r"[a-zçğıöşü0-9]+", _tr_lower(text))
    return [t[:stem] for t in toks if t not in STOP and len(t) > 1]


# Müşteri dili -> politika dili (5 karakterlik kök düzeyinde). Sorguya EKLENİR, yerine geçmez.
SYNONYMS = {"ücret": ["bedel"], "masra": ["bedel"], "bozuk": ["hasar"], "kırık": ["hasar"], "kırıl": ["hasar"],
            "gün": ["süre"], "paran": ["iade"], "para": ["iade"], "vazge": ["vazge"], "iptal": ["iptal"]}


def expand_query(text: str) -> list[str]:
    toks = tokenize(text)
    return toks + [x for t in toks for x in SYNONYMS.get(t, [])]


def load_chunks(policy_dir: Path = POLICY_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(policy_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^Kurallar:\s*(.+)$", text, re.M)
        rules = [r.strip() for r in m.group(1).split(",")] if m else []
        title = re.search(r"^#\s+(.+)$", text, re.M)
        for block in re.split(r"^## ", text, flags=re.M)[1:]:
            head, _, body = block.partition("\n")
            body = body.strip()
            chunks.append(Chunk(path.name, head.strip(), f"{title.group(1) if title else ''} — {head.strip()}\n{body}", rules))
    return chunks


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avg = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, q: list[str]) -> list[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


class PolicyIndex:
    def __init__(self, backend: str = "bm25", policy_dir: Path = POLICY_DIR):
        self.chunks = load_chunks(policy_dir)
        self.backend = backend
        if backend == "bm25":
            self.bm25 = BM25([tokenize(c.text) for c in self.chunks])
        elif backend == "e5":
            from sentence_transformers import SentenceTransformer  # isteğe bağlı bağımlılık
            self.model = SentenceTransformer("intfloat/multilingual-e5-small")
            self.emb = self.model.encode([f"passage: {c.text}" for c in self.chunks], normalize_embeddings=True)
        else:
            raise ValueError("backend 'bm25' veya 'e5' olmalı")

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        if self.backend == "bm25":
            sc = self.bm25.scores(expand_query(query))
        else:
            sc = (self.emb @ self.model.encode([f"query: {query}"], normalize_embeddings=True)[0]).tolist()
        order = sorted(range(len(sc)), key=lambda i: -sc[i])[:k]
        return [(self.chunks[i], sc[i]) for i in order]


_INDEX: PolicyIndex | None = None


def search_policies(query: str, k: int = 3, min_score: float = 0.5) -> dict:
    """Tool gövdesi. G8: eşleşme yoksa uydurma yok -> temsilciye aktar."""
    global _INDEX
    if not isinstance(query, str) or not query.strip():
        return {"error": "EMPTY_QUERY", "message": "query boş olamaz."}
    if not 1 <= k <= 5:
        return {"error": "INVALID_K", "message": "k 1 ile 5 arasında olmalı."}
    _INDEX = _INDEX or PolicyIndex()
    hits = [(c, s) for c, s in _INDEX.search(query, k) if s >= min_score]
    if not hits:
        return {"results": [], "message": "Politikada bu konuda bilgi yok; müşteri temsilcisine aktarın."}
    return {"results": [{"doc": c.doc, "section": c.section, "rules": c.rules, "score": round(s, 3), "text": c.text}
                        for c, s in hits]}
