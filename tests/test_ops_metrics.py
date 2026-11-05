"""ops_tools regresyon testleri. DB'ye bağlı olanlar DB yoksa atlanır (CI'da 126 MB DB yok)."""
import sqlite3

import pytest

import config
from src.tools import ops_tools as ot
from src.tools.session import Session

OPS = Session("ops1", role="ops")


def test_filter_only_dimension_still_joins_table():
    sql, _ = ot.build_metric_sql("late_delivery_rate", None, {"customer_state": "SP", "purchase_month": "2018-07"})
    assert "JOIN customers c" in sql  # eski hata: filtre c.* kullanıyor ama join yoktu


def test_unknown_filter_is_error_not_ignored():
    with pytest.raises(ValueError):
        ot.build_metric_sql("order_count", None, {"state": "SP"})


@pytest.mark.parametrize("bad", ["SP' OR '1'='1", "SP'; DROP TABLE orders;--", "a" * 100])
def test_filter_value_injection_rejected(bad):
    with pytest.raises(ValueError):
        ot.build_metric_sql("order_count", None, {"customer_state": bad})


def test_order_grain_ratios_use_distinct_numerator():
    m = ot.load_metrics_def()
    for name in ("late_delivery_rate", "cancellation_rate"):
        assert "COUNT(DISTINCT CASE" in m[name]["numerator"], name


def test_non_ops_session_forbidden():
    assert ot.run_sql(None, Session("c", role="customer"), "SELECT 1")["error"] == "FORBIDDEN"


needs_db = pytest.mark.skipif(not config.DB_PATH.exists(), reason="shopops.db yok")


@pytest.fixture
def con():
    return sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)


@needs_db
def test_doc_example_sp_july_2018(con):
    r = ot.run_metric(con, OPS, "late_delivery_rate", None, {"customer_state": "SP", "purchase_month": "2018-07"})
    assert r["data"][0]["late_delivery_rate"] == 0.0358


@needs_db
def test_avg_delivery_days_matches_documented_reference(con):
    assert ot.run_metric(con, OPS, "avg_delivery_days")["data"][0]["avg_delivery_days"] == 12.54


@needs_db
def test_category_rates_equal_distinct_order_rates(con):
    r = ot.run_metric(con, OPS, "late_delivery_rate", ["product_category_en"], None, 200)
    row = {x["product_category_en"]: x["late_delivery_rate"] for x in r["data"]}
    assert row["christmas_supplies"] == 0.08  # eski hata: 0.12 (kalem satırları sayılıyordu)
