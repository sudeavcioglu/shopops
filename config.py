"""ShopOps merkezi ayarlar. Tüm iş kuralı sabitleri ve 'bugün' tek yerde durur.

Tüm projenin iş kurallarını (iade süreleri, tutar eşikleri), güvenlik sınırlarını (maksimum adım, döngü engeli), 
model ayarlarını ve deterministik tarihini (SIMULATED_TODAY = 2018-09-01) tek merkezde toplayan konfigürasyon modülüdür

"""
import os
from datetime import date
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  
    pass

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SHOPOPS_DB") or ROOT / "data" / "shopops.db")   

# --- Simülasyon zamanı -------------------------------------------------------
SIMULATED_TODAY = date(2018, 9, 1)

# --- İş kuralları (Bölüm 6.1) -------------------------------------------------
RETURN_WINDOW_CHANGED_MIND_LATE_DAYS = 14   # R6
RETURN_WINDOW_DAMAGED_WRONG_DAYS = 30       # R7
FREIGHT_REFUND_LATE_DAYS = 10               # R9: teslim - tahmini >= 10 gün
FREIGHT_REFUND_CLAIM_WINDOW_DAYS = 30       # R9
SENIOR_APPROVAL_THRESHOLD_BRL = 500.0       # R10: > 500 -> PENDING_SENIOR

# --- Agent sınırları (G4, G10) ------------------------------------------------
MAX_STEPS = 8
MAX_IDENTICAL_CALLS = 2
MAX_SQL_CORRECTIONS = 2
SQL_ROW_LIMIT = 1000

# --- LLM ----------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
_DEFAULT_MODELS = {"gemini": "gemini-3.5-flash-lite", "groq": "llama-3.3-70b-versatile", "ollama": "qwen3:8b"}
LLM_MODEL = os.getenv("LLM_MODEL") or _DEFAULT_MODELS.get(LLM_PROVIDER, "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE") or 0)
