"""İade kural motoru (R0–R13). LLM'siz.

İki katman:
  * evaluate(facts, reason, today)  -> saf fonksiyon, DB'siz test edilir
  * check_return_eligibility(con, order_id, session_unique_id, reason) -> DB'den olguları çeker

Tarihler TAKVİM GÜNÜ olarak karşılaştırılır (saat atılır); teslim günü 0. gündür.
"Bugün" daima config.SIMULATED_TODAY'dir (datetime.now() kullanılmaz).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from config import (FREIGHT_REFUND_CLAIM_WINDOW_DAYS, FREIGHT_REFUND_LATE_DAYS,
                    RETURN_WINDOW_CHANGED_MIND_LATE_DAYS, RETURN_WINDOW_DAMAGED_WRONG_DAYS,
                    SENIOR_APPROVAL_THRESHOLD_BRL, SIMULATED_TODAY)

REASONS = ("changed_mind", "damaged", "wrong_item", "late")
PRE_SHIP = {"created", "approved", "invoiced", "processing"}
CLOSED = {"canceled", "unavailable"}
NOT_FOUND_MSG = "Bu numarayla size ait sipariş bulunamadı."  # R1: yok / yabancı / R0 için AYNI mesaj


def _d(ts: str | None) -> date | None:
    """'YYYY-MM-DD HH:MM:SS' -> date (saat atılır)."""
    return date.fromisoformat(ts[:10]) if ts else None


@dataclass
class Item:
    price: float
    freight_value: float
    shipping_limit_date: str | None = None


@dataclass
class Facts:
    """Bir siparişin kural motoru için gereken olguları."""
    status: str
    purchase_ts: str
    delivered_customer_ts: str | None = None
    estimated_ts: str | None = None
    delivered_carrier_ts: str | None = None
    items: list[Item] = field(default_factory=list)
    voucher_total: float = 0.0
    payment_total: float = 0.0
    has_open_or_closed_request: bool = False  # R11: PENDING_*/APPROVED/REJECTED


def _not_found() -> dict:
    return {"decision": "NOT_FOUND", "rule": "R1", "message": NOT_FOUND_MSG}


def evaluate(facts: Facts | None, reason: str, today: date = SIMULATED_TODAY) -> dict:
    """facts None ise (sipariş yok ya da oturumun değil) -> NOT_FOUND (R1)."""
    if reason not in REASONS:
        return {"decision": "ERROR", "rule": None, "error": "INVALID_REASON",
                "message": f"reason şunlardan biri olmalı: {', '.join(REASONS)}"}
    if facts is None:
        return _not_found()
    # R0: simülasyonda olmayan sipariş
    if _d(facts.purchase_ts) >= today:
        return {**_not_found(), "rule": "R0"}

    st = facts.status
    delivered = _d(facts.delivered_customer_ts)

    # --- Durum kontrolleri (R2–R5) ---
    if st in PRE_SHIP:
        return {"decision": "NOT_DELIVERED_CANCELLABLE", "rule": "R2", "refund_amount": 0.0,
                "message": "Sipariş henüz kargoya verilmedi; iade yapılamaz ama iptal edilebilir."}
    if st == "shipped":
        return {"decision": "IN_TRANSIT", "rule": "R3", "refund_amount": 0.0,
                "message": "Sipariş yolda; iade ve iptal yapılamaz. Teslimden sonra iade hakkı doğar."}
    if st in CLOSED:
        return {"decision": "ALREADY_CLOSED", "rule": "R4", "refund_amount": 0.0,
                "message": "Sipariş iptal/temin edilemedi durumunda; iade talebi açılmaz."}
    if st == "delivered":
        if delivered is None:
            return {"decision": "NEEDS_HUMAN", "rule": "R5", "refund_amount": 0.0,
                    "message": "Teslim kaydı eksik; bir temsilciye devredilmeli."}
        if delivered > today:
            return {"decision": "IN_TRANSIT", "rule": "R3", "refund_amount": 0.0,
                    "message": "Sipariş henüz teslim edilmemiş sayılır."}
    else:  # bilinmeyen durum: güvenli tarafta kal
        return {"decision": "NEEDS_HUMAN", "rule": "R5", "refund_amount": 0.0,
                "message": f"Bilinmeyen sipariş durumu: {st}"}

    # --- R11: tekrar koruması ---
    if facts.has_open_or_closed_request:
        return {"decision": "DUPLICATE_REQUEST", "rule": "R11", "refund_amount": 0.0,
                "message": "Bu sipariş için zaten bir iade talebi var."}

    days = (today - delivered).days
    estimated = _d(facts.estimated_ts)
    late_days = (delivered - estimated).days if estimated else 0
    freight_flag = late_days >= FREIGHT_REFUND_LATE_DAYS  # R9

    # --- Pencere (R6 / R7) ---
    damaged_like = reason in ("damaged", "wrong_item")
    window = RETURN_WINDOW_DAMAGED_WRONG_DAYS if damaged_like else RETURN_WINDOW_CHANGED_MIND_LATE_DAYS
    rule = "R7" if damaged_like else "R6"
    eligible = 0 <= days <= window
    decision = "ELIGIBLE" if eligible else "NOT_ELIGIBLE_WINDOW"

    # --- R8 tutar ---
    price_sum = round(sum(i.price for i in facts.items), 2)
    freight_sum = round(sum(i.freight_value for i in facts.items), 2)
    freight_only = False
    amount = 0.0
    if eligible:
        amount = price_sum + (freight_sum if (damaged_like or freight_flag) else 0.0)
    elif freight_flag and 0 <= days <= FREIGHT_REFUND_CLAIM_WINDOW_DAYS:
        amount, freight_only = freight_sum, True  # R9: yalnız kargo bedeli talebi
    amount = round(amount, 2)

    out = {"decision": decision, "rule": rule, "days_since_delivery": days,
           "window_days": window, "refund_amount": amount, "freight_refund": freight_flag,
           "freight_only": freight_only}

    # --- R10 onay seviyesi (yalnız talep açılabiliyorsa) ---
    if amount > 0:
        out["approval_status"] = "PENDING_SENIOR" if amount > SENIOR_APPROVAL_THRESHOLD_BRL else "PENDING_REVIEW"
        # R12 voucher / orijinal ödeme dağılımı (bilgi)
        share = facts.voucher_total / facts.payment_total if facts.payment_total > 0 else 0.0
        out["voucher_refund"] = round(amount * share, 2)
        out["original_method_refund"] = round(amount - out["voucher_refund"], 2)

    # --- R13 satıcı kaynaklı gecikme (bilgi bayrağı) ---
    carrier = _d(facts.delivered_carrier_ts)
    out["seller_caused_delay"] = bool(carrier and any(
        i.shipping_limit_date and carrier > _d(i.shipping_limit_date) for i in facts.items))

    out["message"] = _message(out)
    return out


def _message(o: dict) -> str:
    if o["decision"] == "ELIGIBLE":
        return "İade için uygunsunuz."
    if o.get("freight_only"):
        return "İade süresi dolmuş; ancak geç teslim nedeniyle yalnız kargo bedeli için talep açabilirsiniz."
    return "İade süresi dolmuş."


# ---------------------------------------------------------------- DB katmanı
def fetch_facts(con: sqlite3.Connection, order_id: str, session_unique_id: str) -> Facts | None:
    """Sipariş oturumdaki customer_unique_id'ye ait değilse None (R1: 'yokmuş gibi')."""
    row = con.execute(
        """SELECT o.order_status, o.order_purchase_timestamp, o.order_delivered_customer_date,
                  o.order_estimated_delivery_date, o.order_delivered_carrier_date
           FROM orders o JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.order_id = ? AND c.customer_unique_id = ?""", (order_id, session_unique_id)).fetchone()
    if row is None:
        return None
    items = [Item(p or 0.0, f or 0.0, s) for p, f, s in con.execute(
        "SELECT price, freight_value, shipping_limit_date FROM order_items WHERE order_id = ?", (order_id,))]
    pay_total, voucher = con.execute(
        "SELECT COALESCE(SUM(payment_value),0), COALESCE(SUM(CASE WHEN payment_type='voucher' THEN payment_value END),0) "
        "FROM order_payments WHERE order_id = ?", (order_id,)).fetchone()
    dup = con.execute("SELECT 1 FROM return_requests WHERE order_id = ? AND status IN "
                      "('PENDING_REVIEW','PENDING_SENIOR','APPROVED','REJECTED') LIMIT 1", (order_id,)).fetchone()
    return Facts(*row, items=items, voucher_total=voucher, payment_total=pay_total,
                 has_open_or_closed_request=dup is not None)


def check_return_eligibility(con: sqlite3.Connection, order_id: str, session_unique_id: str,
                             reason: str, today: date = SIMULATED_TODAY) -> dict:
    """Tool gövdesi. Kimlik LLM'den değil oturumdan (session_unique_id) gelir."""
    return evaluate(fetch_facts(con, order_id, session_unique_id), reason, today)
