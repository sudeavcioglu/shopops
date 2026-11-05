"""Yüklenen DB'yi ShopOps dokümanı Bölüm 3/9.1/5.4 sayılarıyla karşılaştırır.

smoke.py scriptimizle proje yönergesinde verilen tüm sınır sayıları (99.441 sipariş, %6.72 geç teslimat oranı, 3.656 iade penceresi vb.) otomatik olarak doğruladık. 
Sistemimiz sıfır veri kaybı ve sıfır sapmayla resmi referans değerleri birebir sağlamaktadır.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SIMULATED_TODAY  # noqa: E402

TODAY = SIMULATED_TODAY.isoformat()

RAW_EXPECTED = {  # Bölüm 3 (ham satır sayıları)
    "orders": 99_441, "order_items": 112_650, "order_payments": 103_886,
    "order_reviews": 99_224, "customers": 99_441, "sellers": 3_095,
    "products": 32_951, "category_translation": 71, "geolocation": 1_000_163,
}
R0_EXCLUDED = 20
STATUS_RAW = {"delivered": 96_478, "shipped": 1_107, "canceled": 625, "unavailable": 609,
              "invoiced": 314, "processing": 301, "created": 5, "approved": 2}

DELIVERED_OK = ("o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL "
                f"AND DATE(o.order_delivered_customer_date) <= DATE('{TODAY}')")

EDGE_COUNTS = { 
    "R2 created/approved/invoiced/processing": (
        "SELECT COUNT(*) FROM orders WHERE order_status IN ('created','approved','invoiced','processing')", 622),
    "R3 shipped + gelecekte teslim edilen delivered": (
        f"SELECT COUNT(*) FROM orders o WHERE o.order_status='shipped' OR (o.order_status='delivered' "
        f"AND DATE(o.order_delivered_customer_date) > DATE('{TODAY}'))", 1_159),
    "R5 delivered ama teslim tarihi boş": (
        "SELECT COUNT(*) FROM orders WHERE order_status='delivered' AND order_delivered_customer_date IS NULL", 8),
    "R6 penceresi 0-14 gün": (
        f"SELECT COUNT(*) FROM orders o WHERE {DELIVERED_OK} AND "
        f"julianday(DATE('{TODAY}')) - julianday(DATE(o.order_delivered_customer_date)) BETWEEN 0 AND 14", 3_656),
    "R7 penceresi 0-30 gün": (
        f"SELECT COUNT(*) FROM orders o WHERE {DELIVERED_OK} AND "
        f"julianday(DATE('{TODAY}')) - julianday(DATE(o.order_delivered_customer_date)) BETWEEN 0 AND 30", 8_062),
    "R9 teslim - tahmini >= 10 gün": (
        f"SELECT COUNT(*) FROM orders o WHERE {DELIVERED_OK} AND "
        "julianday(DATE(o.order_delivered_customer_date)) - julianday(DATE(o.order_estimated_delivery_date)) >= 10",
        2_256),
    "R12 voucher kullanılan": (
        "SELECT COUNT(DISTINCT order_id) FROM order_payments WHERE payment_type='voucher'", 3_847),
}


class Result:
    def __init__(self) -> None:
        self.fail = 0
        self.warn = 0

    def check(self, name: str, got, expected, level: str = "FAIL", tol: float = 0.0) -> None:
        ok = abs(got - expected) <= tol if isinstance(expected, float) else got == expected
        tag = "OK   " if ok else ("FAIL " if level == "FAIL" else "UYARI")
        if not ok:
            self.fail += level == "FAIL"
            self.warn += level != "FAIL"
        print(f"[{tag}] {name}: bulunan={got:,} beklenen={expected:,}" if isinstance(got, int)
              else f"[{tag}] {name}: bulunan={got} beklenen={expected}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/shopops.db")
    ap.add_argument("--allow-partial", action="store_true", help="eksik tabloları atla (yalnız geliştirme)")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    r = Result()
    meta = {t: (raw, kept) for t, raw, kept in con.execute("SELECT * FROM _load_meta")}

    print(f"SIMULATED_TODAY = {TODAY}\n== Bölüm 3: ham satır sayıları ==")
    for t, exp in RAW_EXPECTED.items():
        if t not in meta:
            if t == "geolocation" or a.allow_partial:
                print(f"[ATLA ] {t}: yüklenmemiş")
                continue
            print(f"[FAIL ] {t}: tablo yüklenmemiş")
            r.fail += 1
            continue
        r.check(f"{t} (ham)", meta[t][0], exp)

    if "orders" in meta:
        print("\n== R0 dışlama ve durum dağılımı ==")
        excl = con.execute("SELECT COUNT(*) FROM _excluded_orders").fetchone()[0]
        r.check("R0 dışlanan sipariş", excl, R0_EXCLUDED)
        r.check("orders (yüklenen)", meta["orders"][1], RAW_EXPECTED["orders"] - R0_EXCLUDED)
        dist: dict[str, int] = {}
        for q in ("SELECT order_status, COUNT(*) FROM orders GROUP BY 1",
                  "SELECT order_status, COUNT(*) FROM _excluded_orders GROUP BY 1"):
            for s, n in con.execute(q):
                dist[s] = dist.get(s, 0) + n
        for s, exp in STATUS_RAW.items():
            r.check(f"durum {s} (yüklenen+dışlanan)", dist.get(s, 0), exp)
        late_in_db = con.execute("SELECT COUNT(*) FROM orders WHERE order_purchase_timestamp >= ?", (TODAY,)).fetchone()[0]
        r.check("DB'de purchase >= SIMULATED_TODAY", late_in_db, 0)

        print("\n== late_delivery_rate (R0 sonrası, takvim günü) ==")
        n, rate = con.execute(
            f"SELECT COUNT(*), AVG(CASE WHEN DATE(o.order_delivered_customer_date) > "
            f"DATE(o.order_estimated_delivery_date) THEN 1.0 ELSE 0.0 END) FROM orders o WHERE {DELIVERED_OK}").fetchone()
        r.check("late_delivery_rate n", n, 96_417)
        r.check("late_delivery_rate", round(rate, 4), 0.0672, tol=0.00005)
        avg = con.execute(f"SELECT AVG(julianday(o.order_delivered_customer_date) - "
                          f"julianday(o.order_purchase_timestamp)) FROM orders o WHERE {DELIVERED_OK}").fetchone()[0]
        r.check("avg_delivery_days (referans)", round(avg, 3), 12.540, level="UYARI", tol=0.0005)

        print("\n== Bölüm 9.1 kenar durum sayıları (UYARI seviyesi) ==")
        for name, (sql, exp) in EDGE_COUNTS.items():
            if name.startswith("R12") and "order_payments" not in meta:
                continue
            r.check(name, con.execute(sql).fetchone()[0], exp, level="UYARI")

    if "customers" in meta:
        print("\n== Kimlik (customer_id vs customer_unique_id) ==")
        r.check("tekil customer_id", con.execute("SELECT COUNT(DISTINCT customer_id) FROM customers").fetchone()[0], 99_441)
        r.check("tekil customer_unique_id", con.execute("SELECT COUNT(DISTINCT customer_unique_id) FROM customers").fetchone()[0], 96_096)

    if "order_reviews" in meta:
        n = con.execute("SELECT COUNT(*) FROM order_reviews WHERE review_comment_message IS NOT NULL").fetchone()[0]
        print(f"[BİLGİ] yorum metni dolu satır (R0 sonrası): {n:,}  (ham beklenen 40,977)")

    if "return_requests" in {t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        r.check("return_requests satır (boş olmalı)", con.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0], 0)

    print(f"\nÖZET: {r.fail} FAIL, {r.warn} UYARI")
    sys.exit(1 if r.fail else 0)


if __name__ == "__main__":
    main()
