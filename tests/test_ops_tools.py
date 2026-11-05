"""Ops Data Agent ve Semantic Layer testleri."""
import sqlite3
import pytest

import config
from src.tools import ops_tools
from src.tools.session import Session


@pytest.fixture
def db_con():
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    yield con
    con.close()


def test_validate_sql_blocks_drop_and_write():
    bad_queries = [
        "DROP TABLE orders",
        "drop table customers;",
        "'; DROP TABLE orders; --",
        "DELETE FROM orders WHERE 1=1",
        "UPDATE customers SET customer_city = 'Hacked'",
        "INSERT INTO return_requests VALUES (1,'o1','u1','late',10,0,'APPROVED','2018-09-01')",
        "ALTER TABLE orders ADD COLUMN evil TEXT",
        "ATTACH DATABASE 'evil.db' AS evil",
        "PRAGMA schema_version",
        "SELECT * FROM orders; DROP TABLE orders;",
    ]
    for q in bad_queries:
        valid, msg = ops_tools.validate_sql(q)
        assert not valid, f"Engellenmeliydi: {q}"
        assert msg is not None


def test_validate_sql_allows_safe_select():
    good_queries = [
        "SELECT order_id, order_status FROM orders LIMIT 10",
        "WITH delivered AS (SELECT order_id FROM orders WHERE order_status='delivered') SELECT COUNT(*) FROM delivered",
        "SELECT c.customer_state, COUNT(*) FROM customers c GROUP BY 1 ORDER BY 2 DESC",
    ]
    for q in good_queries:
        valid, msg = ops_tools.validate_sql(q)
        assert valid, f"İzin verilmeliydi: {q} - Hata: {msg}"
        assert msg is None


def test_list_metrics_returns_at_least_8_metrics_with_caveats():
    s = Session("ops_user", role="ops")
    res = ops_tools.list_metrics(s)
    metrics = res["metrics"]
    assert len(metrics) >= 8
    names = {m["metric_name"] for m in metrics}
    assert {"late_delivery_rate", "gmv", "avg_delivery_days", "order_count", "avg_review_score"} <= names
    for m in metrics:
        assert len(m["caveat"]) > 5, f"{m['metric_name']} için caveat eksik!"


def test_customer_role_cannot_access_ops_tools(db_con):
    s = Session("cust123", role="customer")
    assert ops_tools.list_metrics(s)["error"] == "FORBIDDEN"
    assert ops_tools.run_metric(db_con, s, "late_delivery_rate")["error"] == "FORBIDDEN"
    assert ops_tools.run_sql(db_con, s, "SELECT 1")["error"] == "FORBIDDEN"


def test_run_metric_late_delivery_rate(db_con):
    s = Session("ops_user", role="ops")
    res = ops_tools.run_metric(db_con, s, "late_delivery_rate", dimensions=["customer_state"], limit=3)
    assert "data" in res
    assert res["row_count"] > 0
    assert "caveat" in res
    assert "nedensellik" in res["caveat"].lower()
    first_row = res["data"][0]
    assert "customer_state" in first_row
    assert "late_delivery_rate" in first_row


def test_run_metric_invalid_dimension_error(db_con):
    s = Session("ops_user", role="ops")
    res = ops_tools.run_metric(db_con, s, "late_delivery_rate", dimensions=["invalid_dim"])
    assert res.get("error") == "INVALID_METRIC_REQUEST"


def test_run_sql_execution_and_error_reporting(db_con):
    s = Session("ops_user", role="ops")
    # Başarılı sorgu
    res = ops_tools.run_sql(db_con, s, "SELECT COUNT(*) as n FROM orders")
    assert res["data"][0]["n"] > 0

    # Hatalı sorgu (self-correction için hata mesajı döndürülmeli)
    err_res = ops_tools.run_sql(db_con, s, "SELECT nonexistent_col FROM orders")
    assert err_res.get("error") == "SQL_EXECUTION_ERROR"
    assert "no such column" in err_res["message"]

