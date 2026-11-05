"""LLM bağlantı testi (30 sn sınırlı, yeniden deneme yok). Kullanım:  python scripts/check_llm.py
Çıktı: OK + süre ya da hatanın türü (429 = kota, 401/403 = anahtar, 404/400 = model adı, timeout = ağ)."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402  (.env'i yükler)
from openai import OpenAI  # noqa: E402

BASES = {"gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
         "groq": "https://api.groq.com/openai/v1", "ollama": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/v1"}
KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "ollama": None}

p = config.LLM_PROVIDER
key = os.environ.get(KEYS[p], "ollama") if KEYS[p] else "ollama"
print(f"sağlayıcı={p} model={config.LLM_MODEL} anahtar={'VAR' if key else 'YOK'}")
if not key:
    sys.exit(f"{KEYS[p]} boş: .env dosyasına anahtarı yaz.")
t = time.time()
try:
    r = OpenAI(api_key=key, base_url=BASES[p], timeout=30, max_retries=0).chat.completions.create(
        model=config.LLM_MODEL, messages=[{"role": "user", "content": "Sadece 'tamam' yaz."}], max_tokens=20)
    print(f"OK: {r.choices[0].message.content!r}  ({time.time() - t:.1f} sn)")
except Exception as e:  # noqa: BLE001
    print(f"HATA: {type(e).__name__}: {str(e)[:300]}  ({time.time() - t:.1f} sn)")
