"""ShopOps Sipariş ve İade MCP Sunucusu (shopops-orders).

Genel Rehber §3 #4 ve ShopOps §5.3 gereksinimleri:
- Kendi yazdığımız özel FastMCP sunucusu (stdio transport).
- Sunulan araçlar: get_order_status, list_customer_orders, check_return_eligibility, create_return_request
- Yetki ve HITL onay kontrolleri SUNUCU tarafında oturum nesnesinde (Session) tutulur.
- LLM'den asla customer_id parametresi alınmaz; oturumdan (customer_unique_id) çekilir.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import config
from src.tools import returns
from src.tools import support_tools as st
from src.tools.session import Session

# FastMCP sunucusu başlat
mcp = FastMCP("shopops-orders")

# Sunucu tarafı oturum nesnesi (Varsayılan müşteri kimliği ortam değişkeninden ya da demo müşteriden)
_SESSION_UID = os.getenv("SHOPOPS_SESSION_UID", "a71cac9f356cfeb9db35061020806212")
SESSION = Session(_SESSION_UID, role="customer")


def get_db_con_ro():
    return sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)


def get_db_con_rw():
    return sqlite3.connect(config.DB_PATH, isolation_level=None)


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Oturumdaki müşterinin siparişinin durumunu, tarihlerini ve kalemlerini döndürür.
    Sipariş yoksa ya da müşteriye ait değilse NOT_FOUND hatası döner.
    """
    con = get_db_con_ro()
    try:
        return st.get_order_status(con, SESSION, order_id)
    finally:
        con.close()


@mcp.tool()
def list_customer_orders(limit: int = 5, status: str | None = None) -> dict:
    """Oturumdaki müşterinin siparişlerini yeniden eskiye listeler (limit: 1-20)."""
    con = get_db_con_ro()
    try:
        return st.list_customer_orders(con, SESSION, limit, status)
    finally:
        con.close()


@mcp.tool()
def check_return_eligibility(order_id: str, reason: str) -> dict:
    """Bir siparişin iade uygunluğunu deterministik kural motoruyla (R0-R13) kontrol eder.
    Dönen sonuçta karar kodu, iade tutarı (BRL) ve onay seviyesi bulunur.
    reason seçenekleri: changed_mind, damaged, wrong_item, late
    """
    con = get_db_con_ro()
    try:
        return returns.check_return_eligibility(con, order_id, SESSION.customer_unique_id, reason)
    finally:
        con.close()


@mcp.tool()
def create_return_request(order_id: str, reason: str, amount: float,
                          proposal_id: str | None = None) -> dict:
    """İade talebi açar. İNSAN ONAYI (HITL) zorunludur; onaysız çağrılarda APPROVAL_REQUIRED döner.
    Tutar kural motorunun refund_amount değeriyle birebir eşleşmelidir.
    """
    con = get_db_con_rw()
    try:
        return st.create_return_request(con, SESSION, order_id, reason, amount, proposal_id)
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")

