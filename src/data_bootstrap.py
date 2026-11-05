"""İlk açılışta veritabanını kurar (Streamlit Cloud / HF gibi ortamlarda repoda DB yok).

Olist verisi CC BY-NC-SA 4.0 lisanslıdır; ham veri ve türetilmiş DB repoya konmaz, açılışta indirilir.
geolocation yüklenmez (Temel'de gerekmez; kurulum süresini ve boyutu küçültür).
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _kaggle_download() -> str:
    import kagglehub
    return kagglehub.dataset_download("olistbr/brazilian-ecommerce")


def ensure_db(db_path: Path, downloader: Callable[[], str] = _kaggle_download) -> Path:
    """DB varsa ve dolu görünüyorsa dokunmaz; yoksa indirip kurar. Yarım kalan dosyaya karşı geçici adla yazar."""
    db_path = Path(db_path)
    if db_path.exists():
        try:
            # closing: hata olsa bile bağlantı kapanır (Windows açık dosyayı silemez)
            with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
                ok = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] > 0
            if ok:
                return db_path
        except sqlite3.Error:
            pass
        db_path.unlink(missing_ok=True)
    import load_sqlite
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)   # önceki yarım kurulumdan kalan dosya
    load_sqlite.load(Path(downloader()), tmp, with_geolocation=False)
    tmp.replace(db_path)
    return db_path
