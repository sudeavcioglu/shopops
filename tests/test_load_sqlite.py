"""Loader'ın R0 dışlama / NULL / indeks davranışını küçük sentetik CSV'lerle test eder.
(Gerçek Olist verisi gerekmez; sentetik, kişisel veri içermez.)"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import load_sqlite  # noqa: E402

HDR_O = "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date\n"


def make_src(tmp_path: Path) -> Path:
    s = tmp_path / "src"
    s.mkdir()
    (s / "olist_orders_dataset.csv").write_text(
        HDR_O
        + "o1,c1,delivered,2018-08-01 10:00:00,2018-08-01 11:00:00,2018-08-02 09:00:00,2018-08-10 12:00:00,2018-08-15 00:00:00\n"
        + "o2,c2,delivered,2018-08-05 10:00:00,2018-08-05 11:00:00,2018-08-06 09:00:00,,2018-08-20 00:00:00\n"
        + "o3,c3,created,2018-09-01 00:00:01,,,,2018-09-20 00:00:00\n"   # R0: dışlanmalı
        + "o4,c4,shipped,2018-09-10 08:00:00,,,,2018-09-30 00:00:00\n")  # R0: dışlanmalı
    (s / "olist_customers_dataset.csv").write_text(
        "customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state\n"
        "c1,u1,01001,sao paulo,SP\nc2,u1,01001,sao paulo,SP\nc3,u2,02002,rio,RJ\nc4,u3,03003,rio,RJ\n")
    (s / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value\n"
        "o1,1,p1,s1,2018-08-03 00:00:00,100.5,10.0\no3,1,p1,s1,2018-09-05 00:00:00,50,5\n")
    return s


def test_r0_exclusion_and_nulls(tmp_path):
    db = tmp_path / "t.db"
    rep = load_sqlite.load(make_src(tmp_path), db)
    con = sqlite3.connect(db)
    assert rep["loaded"]["orders"] == (4, 2)
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2
    assert {r[0] for r in con.execute("SELECT order_id FROM _excluded_orders")} == {"o3", "o4"}
    # R0'a bağlı kalem de dışlanır
    assert con.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 1
    # boş teslim tarihi NULL olmalı (boş string değil) -> R5 ayrımı için kritik
    assert con.execute("SELECT order_delivered_customer_date FROM orders WHERE order_id='o2'").fetchone()[0] is None
    # fiyat sayısal tipte
    assert con.execute("SELECT typeof(price) FROM order_items").fetchone()[0] == "real"
    # customer_id ≠ customer_unique_id: 2 sipariş kimliği, 1 kişi
    assert con.execute("SELECT COUNT(DISTINCT customer_unique_id) FROM customers WHERE customer_id IN ('c1','c2')").fetchone()[0] == 1


def test_return_requests_empty_and_indexed(tmp_path):
    db = tmp_path / "t.db"
    load_sqlite.load(make_src(tmp_path), db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0] == 0
    idx = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_orders_customer", "idx_items_order", "idx_customers_unique"} <= idx
