"""R0–R13 ve Bölüm 6.1 sınır testleri. Bugün = 2018-09-01 (SIMULATED_TODAY)."""
import sqlite3
from datetime import date

import pytest

from src.tools.returns import Facts, Item, NOT_FOUND_MSG, check_return_eligibility, evaluate

TODAY = date(2018, 9, 1)


def F(status="delivered", deliv="2018-08-25 10:00:00", est="2018-08-30 00:00:00", purchase="2018-08-01 09:00:00",
      items=None, carrier="2018-08-03 09:00:00", voucher=0.0, pay=110.0, dup=False):
    return Facts(status=status, purchase_ts=purchase, delivered_customer_ts=deliv, estimated_ts=est,
                 delivered_carrier_ts=carrier, items=items if items is not None else [Item(100.0, 10.0, "2018-08-05 00:00:00")],
                 voucher_total=voucher, payment_total=pay, has_open_or_closed_request=dup)


def dec(f, reason="changed_mind"):
    return evaluate(f, reason, TODAY)


# ---- R0 / R1
def test_r0_future_purchase_is_not_found():
    r = dec(F(purchase="2018-09-01 00:00:01"))
    assert r["decision"] == "NOT_FOUND" and r["rule"] == "R0"

def test_r1_foreign_or_missing_order_same_message():
    assert evaluate(None, "changed_mind", TODAY) == {"decision": "NOT_FOUND", "rule": "R1", "message": NOT_FOUND_MSG}
    assert dec(F(purchase="2018-09-02 00:00:00"))["message"] == NOT_FOUND_MSG  # R0 de aynı mesaj

# ---- R2–R5
@pytest.mark.parametrize("st", ["created", "approved", "invoiced", "processing"])
def test_r2_pre_ship(st):
    assert dec(F(status=st, deliv=None))["decision"] == "NOT_DELIVERED_CANCELLABLE"

def test_r3_shipped():
    assert dec(F(status="shipped", deliv=None))["decision"] == "IN_TRANSIT"

def test_r3_delivered_in_future():
    assert dec(F(deliv="2018-09-05 12:00:00"))["decision"] == "IN_TRANSIT"

@pytest.mark.parametrize("st", ["canceled", "unavailable"])
def test_r4_closed(st):
    assert dec(F(status=st, deliv=None))["decision"] == "ALREADY_CLOSED"

def test_r5_delivered_without_date():
    assert dec(F(deliv=None))["decision"] == "NEEDS_HUMAN"

# ---- R6 sınırları
@pytest.mark.parametrize("deliv,exp", [("2018-09-01 23:00:00", "ELIGIBLE"),       # 0. gün (saat atılır)
                                       ("2018-08-18 00:00:01", "ELIGIBLE"),       # 14. gün
                                       ("2018-08-17 23:59:59", "NOT_ELIGIBLE_WINDOW")])  # 15. gün
def test_r6_boundaries(deliv, exp):
    assert dec(F(deliv=deliv, est="2018-09-30 00:00:00"), "changed_mind")["decision"] == exp

def test_r6_applies_to_late_reason():
    assert dec(F(deliv="2018-08-17 10:00:00", est="2018-09-30 00:00:00"), "late")["decision"] == "NOT_ELIGIBLE_WINDOW"

# ---- R7 sınırları
@pytest.mark.parametrize("reason", ["damaged", "wrong_item"])
@pytest.mark.parametrize("deliv,exp", [("2018-08-02 10:00:00", "ELIGIBLE"), ("2018-08-01 10:00:00", "NOT_ELIGIBLE_WINDOW")])
def test_r7_boundaries(reason, deliv, exp):
    assert dec(F(deliv=deliv, est="2018-09-30 00:00:00"), reason)["decision"] == exp

# ---- R8 tutar
def test_r8_changed_mind_price_only():
    r = dec(F(est="2018-09-30 00:00:00"))
    assert r["refund_amount"] == 100.0 and r["freight_refund"] is False

def test_r8_damaged_includes_freight():
    assert dec(F(est="2018-09-30 00:00:00"), "damaged")["refund_amount"] == 110.0

def test_r8_multi_item_sum():
    items = [Item(50.5, 5.0), Item(20.25, 2.5)]
    assert dec(F(items=items, est="2018-09-30 00:00:00"))["refund_amount"] == 70.75

# ---- R9
def test_r9_flag_adds_freight_when_eligible():
    # teslim 08-25, tahmini 08-15 -> 10 gün geç
    r = dec(F(deliv="2018-08-25 10:00:00", est="2018-08-15 00:00:00"))
    assert r["freight_refund"] is True and r["refund_amount"] == 110.0

def test_r9_nine_days_late_no_flag():
    assert dec(F(deliv="2018-08-25 10:00:00", est="2018-08-16 00:00:00"))["freight_refund"] is False

def test_r9_outside_window_freight_only_claim():
    # teslim 08-10 (22. gün), 12 gün geç -> pencere dışı ama kargo talebi açılabilir
    r = dec(F(deliv="2018-08-10 10:00:00", est="2018-07-29 00:00:00"))
    assert r["decision"] == "NOT_ELIGIBLE_WINDOW" and r["freight_only"] and r["refund_amount"] == 10.0

def test_r9_freight_claim_day_30_ok_day_31_none():
    d30 = dec(F(deliv="2018-08-02 10:00:00", est="2018-07-20 00:00:00"))
    d31 = dec(F(deliv="2018-08-01 10:00:00", est="2018-07-20 00:00:00"))
    assert d30["refund_amount"] == 10.0 and d31["refund_amount"] == 0.0 and "approval_status" not in d31

# ---- R10
def test_r10_threshold_is_strictly_greater():
    eq = dec(F(items=[Item(500.0, 0.0)], est="2018-09-30 00:00:00"))
    gt = dec(F(items=[Item(500.01, 0.0)], est="2018-09-30 00:00:00"))
    assert eq["approval_status"] == "PENDING_REVIEW" and gt["approval_status"] == "PENDING_SENIOR"

def test_r10_uses_refund_amount_incl_freight():
    # price 495 + freight 10 = 505 > 500 (damaged -> kargo dahil)
    r = dec(F(items=[Item(495.0, 10.0)], est="2018-09-30 00:00:00"), "damaged")
    assert r["approval_status"] == "PENDING_SENIOR"

# ---- R11
def test_r11_duplicate():
    assert dec(F(dup=True))["decision"] == "DUPLICATE_REQUEST"

def test_r11_after_status_checks():
    assert dec(F(status="shipped", deliv=None, dup=True))["decision"] == "IN_TRANSIT"

# ---- R12
def test_r12_voucher_split():
    r = dec(F(est="2018-09-30 00:00:00", voucher=55.0, pay=110.0))
    assert r["voucher_refund"] == 50.0 and r["original_method_refund"] == 50.0

# ---- R13
def test_r13_seller_delay_flag():
    assert dec(F(carrier="2018-08-10 09:00:00"))["seller_caused_delay"] is True   # limit 08-05
    assert dec(F(carrier="2018-08-05 23:00:00"))["seller_caused_delay"] is False  # aynı gün: gecikme değil

def test_invalid_reason():
    assert dec(F(), "because")["error"] == "INVALID_REASON"

# ---- DB katmanı: yetki tool katmanında
def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
    CREATE TABLE customers(customer_id TEXT, customer_unique_id TEXT);
    CREATE TABLE orders(order_id TEXT, customer_id TEXT, order_status TEXT, order_purchase_timestamp TEXT,
      order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT, order_delivered_carrier_date TEXT);
    CREATE TABLE order_items(order_id TEXT, price REAL, freight_value REAL, shipping_limit_date TEXT);
    CREATE TABLE order_payments(order_id TEXT, payment_type TEXT, payment_value REAL);
    CREATE TABLE return_requests(order_id TEXT, status TEXT);
    INSERT INTO customers VALUES ('c1','uA'),('c2','uB');
    INSERT INTO orders VALUES ('o1','c1','delivered','2018-08-01 09:00:00','2018-08-25 10:00:00','2018-09-30 00:00:00','2018-08-03 00:00:00');
    INSERT INTO order_items VALUES ('o1',100,10,'2018-08-05 00:00:00');
    INSERT INTO order_payments VALUES ('o1','credit_card',110);
    """)
    return con

def test_db_owner_gets_decision_foreign_gets_not_found():
    con = _db()
    assert check_return_eligibility(con, "o1", "uA", "changed_mind", TODAY)["decision"] == "ELIGIBLE"
    foreign = check_return_eligibility(con, "o1", "uB", "changed_mind", TODAY)
    missing = check_return_eligibility(con, "nope", "uA", "changed_mind", TODAY)
    assert foreign == missing and foreign["decision"] == "NOT_FOUND"  # varlık ifşası yok

def test_db_duplicate_detected():
    con = _db()
    con.execute("INSERT INTO return_requests VALUES ('o1','REJECTED')")
    assert check_return_eligibility(con, "o1", "uA", "changed_mind", TODAY)["decision"] == "DUPLICATE_REQUEST"
