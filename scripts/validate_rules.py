"""Kural motorunu GERÇEK DB üzerinde Bölüm 9.1 kontrol değerleriyle doğrular.

Kullanım:  python scripts/validate_rules.py --db data/shopops.db
Beklenenler:
  R6 penceresi (0-14 gün) 3.656 sipariş; changed_mind & refund_amount > 500  -> 130
  R7 penceresi (0-30 gün) 8.062 sipariş; damaged & refund_amount > 500       -> 352
  R9 bayraklı 2.256 sipariş: <=14 gün 33 | 15-30 gün 28 (yalnız kargo) | >30 gün 2.195 (talep yok)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SIMULATED_TODAY as T  # noqa: E402
from src.tools.returns import fetch_facts, evaluate  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="data/shopops.db")
con = sqlite3.connect(f"file:{ap.parse_args().db}?mode=ro", uri=True)

rows = con.execute(
    "SELECT o.order_id, c.customer_unique_id FROM orders o JOIN customers c USING(customer_id) "
    "WHERE o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL "
    "AND DATE(o.order_delivered_customer_date) <= ?", (T.isoformat(),)).fetchall()

ok = True
def check(name, got, exp):
    global ok
    good = got == exp
    ok &= good
    print(f"[{'OK  ' if good else 'FAIL'}] {name}: bulunan={got:,} beklenen={exp:,}")

w6 = w7 = big6 = big7 = 0
r9 = {"<=14": 0, "15-30": 0, ">30": 0}
for oid, uid in rows:
    f = fetch_facts(con, oid, uid)
    a = evaluate(f, "changed_mind", T)
    d = a["days_since_delivery"]
    if 0 <= d <= 14:
        w6 += 1
        big6 += a["refund_amount"] > 500
    b = evaluate(f, "damaged", T)
    if 0 <= d <= 30:
        w7 += 1
        big7 += b["refund_amount"] > 500
    if a["freight_refund"]:
        r9["<=14" if d <= 14 else "15-30" if d <= 30 else ">30"] += 1

check("R6 penceresi sipariş", w6, 3656)
check("R7 penceresi sipariş", w7, 8062)
check("changed_mind refund > 500 (R6 penceresi)", big6, 130)
check("damaged refund > 500 (R7 penceresi)", big7, 352)
check("R9 teslim<=14 gün", r9["<=14"], 33)
check("R9 15-30 gün (yalnız kargo)", r9["15-30"], 28)
check("R9 >30 gün (talep yok)", r9[">30"], 2195)
sys.exit(0 if ok else 1)
