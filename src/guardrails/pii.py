"""G6: PII'siz log. Ham 32 karakterlik Olist kimlikleri loglara/ticket'lara yazılmaz.
log dosyalarına, eval raporlarına veya insan temsilcilere devredilen biletlere ham müşteri ve sipariş kimliklerinin düz metin olarak sızmasını engellemektir.
"""
import hashlib
import re

ID_RE = re.compile(r"\b[0-9a-f]{32}\b")


def hash_id(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def redact_ids(text: str) -> str:
    return ID_RE.sub(lambda m: f"id:{hash_id(m.group(0))}", text)
