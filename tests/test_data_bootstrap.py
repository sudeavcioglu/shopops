import sqlite3
from contextlib import closing
from src.data_bootstrap import ensure_db
from tests.test_load_sqlite import make_src


def _n_orders(db):
    with closing(sqlite3.connect(db)) as c:   # bağlantıyı kapat: Windows'ta dosya kilitli kalmasın
        return c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


def test_builds_db_when_missing_and_is_idempotent(tmp_path):
    src = make_src(tmp_path)
    calls = []
    dl = lambda: calls.append(1) or str(src)           # noqa: E731
    db = tmp_path / "x" / "shopops.db"
    assert ensure_db(db, dl) == db and db.exists() and len(calls) == 1
    assert _n_orders(db) == 2   # R0 sonrası
    ensure_db(db, dl)
    assert len(calls) == 1                              # var olan DB'ye dokunmaz


def test_broken_db_is_rebuilt(tmp_path):
    src = make_src(tmp_path)
    db = tmp_path / "shopops.db"
    db.write_bytes(b"not a database")
    ensure_db(db, lambda: str(src))
    assert _n_orders(db) == 2
