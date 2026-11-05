"""Support Agent tool'ları. 
Müşteri Destek Ajanı'nın sipariş sorgulama (get_order_status), listeleme, canlı desteğe aktarma ve veritabanındaki 
tek yazma noktası olan iade talebini insan onayıyla açma işlevlerini yürüten çekirdek araç modülüdür.
"""
from __future__ import annotations

import sqlite3

from config import SIMULATED_TODAY
from src.guardrails.pii import hash_id, redact_ids
from src.tools.returns import NOT_FOUND_MSG, REASONS, check_return_eligibility
from src.tools.session import Session

STATUSES = ("created", "approved", "invoiced", "processing", "shipped", "delivered", "canceled", "unavailable")
NOT_FOUND = {"error": "NOT_FOUND", "message": NOT_FOUND_MSG}
TODAY = SIMULATED_TODAY.isoformat()
ESCALATIONS: list[dict] = [] 


def _customer_only(session: Session) -> dict | None:
    if session.role != "customer":
        return {"error": "FORBIDDEN", "message": "Bu işlem yalnız müşteri oturumunda kullanılabilir."}
    return None


def get_order_status(con: sqlite3.Connection, session: Session, order_id: str) -> dict:
    """Oturumdaki müşterinin siparişinin durumunu, tarihlerini ve kalemlerini döndürür.
    order_id: sipariş numarası (32 karakter). Sipariş yoksa ya da size ait değilse NOT_FOUND."""
    if (err := _customer_only(session)):
        return err
    if not isinstance(order_id, str) or not order_id.strip():
        return {"error": "INVALID_ARGUMENT", "message": "order_id boş olamaz."}
    row = con.execute(
        """SELECT o.order_id, o.order_status, o.order_purchase_timestamp, o.order_estimated_delivery_date,
                  o.order_delivered_customer_date
           FROM orders o JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.order_id = ? AND c.customer_unique_id = ? AND DATE(o.order_purchase_timestamp) < DATE(?)""",
        (order_id.strip(), session.customer_unique_id, TODAY)).fetchone()
    if row is None:
        return dict(NOT_FOUND)
    items = [{"product_id": p, "category": cat, "price": pr, "freight_value": fr} for p, cat, pr, fr in con.execute(
        """SELECT i.product_id, t.product_category_name_english, i.price, i.freight_value
           FROM order_items i LEFT JOIN products p ON p.product_id = i.product_id
           LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
           WHERE i.order_id = ? ORDER BY i.order_item_id""", (row[0],))]
    d = lambda ts: ts[:10] if ts else None  # noqa: E731
    return {"order_id": row[0], "status": row[1], "purchase_date": d(row[2]),
            "estimated_delivery_date": d(row[3]), "delivered_date": d(row[4]), "items": items}


def list_customer_orders(con: sqlite3.Connection, session: Session, limit: int = 5,
                         status: str | None = None) -> dict:
    """Oturumdaki müşterinin siparişlerini yeni -> eski listeler. limit 1–20; status isteğe bağlı filtre."""
    if (err := _customer_only(session)):
        return err
    if not isinstance(limit, int) or not 1 <= limit <= 20:
        return {"error": "INVALID_ARGUMENT", "message": "limit 1 ile 20 arasında tam sayı olmalı."}
    if status is not None and status not in STATUSES:
        return {"error": "INVALID_ARGUMENT", "message": f"status şunlardan biri olmalı: {', '.join(STATUSES)}"}
    q = ("SELECT o.order_id, o.order_status, o.order_purchase_timestamp FROM orders o "
         "JOIN customers c ON c.customer_id = o.customer_id "
         "WHERE c.customer_unique_id = ? AND DATE(o.order_purchase_timestamp) < DATE(?)")
    args: list = [session.customer_unique_id, TODAY]
    if status:
        q += " AND o.order_status = ?"
        args.append(status)
    q += " ORDER BY o.order_purchase_timestamp DESC LIMIT ?"
    rows = con.execute(q, (*args, limit)).fetchall()
    return {"orders": [{"order_id": a, "status": b, "purchase_date": c[:10]} for a, b, c in rows]}


def create_return_request(con: sqlite3.Connection, session: Session, order_id: str, reason: str,
                          amount: float, proposal_id: str | None = None) -> dict:
    """İade talebi açar. İNSAN ONAYI olmadan çalışmaz (APPROVAL_REQUIRED).
    Tutar kural motorundan doğrulanır; LLM'in verdiği tutara güvenilmez."""
    if (err := _customer_only(session)):
        return err
    if reason not in REASONS:
        return {"error": "INVALID_ARGUMENT", "message": f"reason şunlardan biri olmalı: {', '.join(REASONS)}"}
    elig = check_return_eligibility(con, order_id, session.customer_unique_id, reason)
    if elig["decision"] == "NOT_FOUND":
        return dict(NOT_FOUND)
    if elig["decision"] == "DUPLICATE_REQUEST":
        return {"error": "DUPLICATE_REQUEST", "message": elig["message"]}
    if not (elig["decision"] == "ELIGIBLE" or elig.get("freight_only")) or elig.get("refund_amount", 0) <= 0:
        return {"error": "NOT_ELIGIBLE", "decision": elig["decision"], "message": elig.get("message", "")}
    if round(float(amount), 2) != elig["refund_amount"]:
        return {"error": "AMOUNT_MISMATCH", "expected_amount": elig["refund_amount"],
                "message": "Tutar kural motorunun hesabıyla uyuşmuyor."}
    amt = elig["refund_amount"]
    if not session.gate.consume(proposal_id, session.customer_unique_id, order_id, reason, amt):
        pid = session.gate.propose(session.customer_unique_id, order_id, reason, amt)
        return {"error": "APPROVAL_REQUIRED", "proposal_id": pid,
                "proposal": {"order_id": order_id, "reason": reason, "refund_amount": amt,
                             "freight_only": elig.get("freight_only", False),
                             "approval_level": elig["approval_status"]},
                "message": "Talep insan onayı bekliyor; müşteriye özeti gösterip onay alın."}
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM return_requests WHERE order_id = ?", (order_id,)).fetchone():
            con.execute("ROLLBACK")
            return {"error": "DUPLICATE_REQUEST", "message": "Bu sipariş için zaten bir iade talebi var."}
        cur = con.execute(
            "INSERT INTO return_requests (order_id, customer_unique_id, reason, refund_amount, freight_only, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (order_id, session.customer_unique_id, reason, amt, int(elig.get("freight_only", False)),
             elig["approval_status"], TODAY))
        con.execute("COMMIT")
    except sqlite3.Error as e:
        if con.in_transaction:
            con.execute("ROLLBACK")
        return {"error": "DB_ERROR", "message": str(e)}
    return {"return_request_id": cur.lastrowid, "status": elig["approval_status"], "refund_amount": amt,
            "voucher_refund": elig.get("voucher_refund"), "original_method_refund": elig.get("original_method_refund")}


def escalate_to_human(session: Session, summary: str, priority: str = "normal") -> dict:
    """Konuyu insana devreder (kayıt değiştirmez). summary kişisel veri içermemeli; kimlikler otomatik maskelenir."""
    if priority not in ("low", "normal", "high"):
        return {"error": "INVALID_ARGUMENT", "message": "priority low | normal | high olmalı."}
    if not isinstance(summary, str) or not summary.strip():
        return {"error": "INVALID_ARGUMENT", "message": "summary boş olamaz."}
    ticket = {"ticket": f"T-{len(ESCALATIONS) + 1:05d}", "priority": priority,
              "summary": redact_ids(summary.strip())[:500], "customer": hash_id(session.customer_unique_id)}
    ESCALATIONS.append(ticket)
    return {"ticket": ticket["ticket"], "priority": priority}
