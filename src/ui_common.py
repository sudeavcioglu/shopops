"""Teknik API ve kota hatalarını kullanıcı dostu Türkçe mesajlara dönüştüren, ajan adımlarını ise kişisel verileri (PII) 
maskeleyerek arayüzde şeffafça görselleştiren UI yardımcı modülüdür."""
from __future__ import annotations

import json

from src.guardrails.pii import redact_ids


def friendly_error(e: Exception) -> str:
    t = str(e).lower()
    if any(k in t for k in ("429", "quota", "resource_exhausted", "rate limit", "rate_limit")):
        return "⏳ Demo model kotası şu an dolu. Lütfen bir dakika sonra tekrar deneyin."
    if any(k in t for k in ("gemini_api_key", "groq_api_key", "api key", "api_key", "401", "403", "unauthorized")):
        return "🔑 Model anahtarı bulunamadı ya da geçersiz görünüyor. Lütfen demo sahibine bildirin."
    if any(k in t for k in ("404", "no longer available", "not found", "notfounderror")):
        return "🤖 Yapılandırılan model bulunamadı ya da artık kullanılamıyor. Lütfen demo sahibine bildirin."
    if any(k in t for k in ("timeout", "timed out", "connection", "unavailable", "503", "502")):
        return "🌐 Model servisine şu an ulaşılamıyor. Birkaç saniye sonra tekrar deneyin."
    return "Beklenmeyen bir hata oluştu. Lütfen mesajınızı yeniden gönderin."


def short_result(res) -> str:
    if not isinstance(res, dict):
        return str(res)[:80]
    for k in ("decision", "error", "status"):
        if k in res:
            extra = f" · {res['refund_amount']} BRL" if "refund_amount" in res else ""
            return f"{res[k]}{extra}"
    if "orders" in res:
        return f"{len(res['orders'])} sipariş"
    if "results" in res:
        return f"{len(res['results'])} politika parçası"
    if "data" in res:
        return f"{res.get('row_count', len(res['data']))} satır"
    return ", ".join(list(res.keys())[:4])


def summarize_trace(trace: list) -> list[dict]:
    out = []
    for name, args, res in trace:
        a = redact_ids(json.dumps(args, ensure_ascii=False, default=str))
        out.append({"tool": name, "args": a[:220], "result": short_result(res)})
    return out


def steps_markdown(steps: list[dict]) -> str:
    if not steps:
        return "_Bu yanıt için tool çağrılmadı._"
    lines = []
    for i, s in enumerate(steps, 1):
        lines.append(f"**{i}. `{s['tool']}`** → {s['result']}\n\n```json\n{s['args']}\n```")
    return "\n\n".join(lines)
