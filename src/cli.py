"""Müşteri destek CLI demosu (Temel seviye: CLI + HITL 'onayla? [e/h]').
Web arayüzü (Streamlit) açmaya gerek kalmadan, doğrudan terminal üzerinden Müşteri Destek Asistanı 
ile canlı sohbet etmeyi ve test yapmayı sağlar.
"""
from __future__ import annotations

import argparse
import sqlite3
import time

import config
from src.agents.support_agent import Ctx, StepLogger, build_agent
from src.tools.session import Session


def demo_customers(con, n: int = 3):
    return con.execute(
        """SELECT c.customer_unique_id, o.order_id, o.order_delivered_customer_date FROM orders o
           JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.order_status='delivered' AND DATE(o.order_delivered_customer_date) <= DATE(?)
             AND julianday(DATE(?)) - julianday(DATE(o.order_delivered_customer_date)) BETWEEN 1 AND 10
           ORDER BY o.order_delivered_customer_date DESC LIMIT ?""",
        (config.SIMULATED_TODAY.isoformat(), config.SIMULATED_TODAY.isoformat(), n)).fetchall()


def console_confirm(p: dict) -> bool:
    print("\n--- İADE TALEBİ ÖZETİ (insan onayı) ---")
    print(f"Sipariş: {p['order_id']}\nNeden: {p['reason']}\nİade tutarı: {p['refund_amount']} BRL"
          f"{' (yalnız kargo bedeli)' if p['freight_only'] else ''}\nOnay seviyesi: {p['approval_level']}")
    return input("Talebi onaylıyor musunuz? [e/h]: ").strip().lower() in ("e", "evet", "y")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--db", default=str(config.DB_PATH))
    a = ap.parse_args()
    ro = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    if a.demo:
        for uid, oid, d in demo_customers(ro):
            print(f"uid={uid}  order={oid}  teslim={d[:10]}")
        return
    if not a.uid:
        ap.error("--uid ya da --demo gerekli")
    rw = sqlite3.connect(a.db, isolation_level=None)
    ctx = Ctx(ro, rw, Session(a.uid), confirm=console_confirm)
    logger = StepLogger(config.ROOT / "traces" / f"run_{int(time.time())}.jsonl")
    agent = build_agent(ctx, logger=logger, verbosity=0)
    print(f"ShopOps destek ({config.LLM_PROVIDER}/{config.LLM_MODEL}) — bugün {config.SIMULATED_TODAY}. Çıkış: q")
    while True:
        msg = input("\nSiz: ").strip()
        if msg.lower() in ("q", "quit", "exit"):
            break
        if msg:
            print("\nAsistan:", agent.run(msg, reset=False))


if __name__ == "__main__":
    main()
