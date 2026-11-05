import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from load_sqlite import DDL  # noqa: E402
from src.tools import support_tools as st  # noqa: E402
from src.tools.session import Session  # noqa: E402

A, B = "u" * 32, "v" * 32
O1 = "a" * 32   # A'nın teslim edilmiş, uygun siparişi (fiyat 100, kargo 10)
OBIG = "b" * 32  # A'nın 600 BRL'lik siparişi
OB = "c" * 32   # B'nin siparişi


@pytest.fixture
def con(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db", isolation_level=None)
    c.executescript(DDL)
    c.executescript(f"""
    INSERT INTO customers VALUES ('c1','{A}','1','x','SP'),('c2','{A}','1','x','SP'),('c3','{B}','2','y','RJ');
    INSERT INTO orders VALUES ('{O1}','c1','delivered','2018-08-01 09:00:00',NULL,'2018-08-03 00:00:00','2018-08-25 10:00:00','2018-09-30 00:00:00');
    INSERT INTO orders VALUES ('{OBIG}','c2','delivered','2018-08-02 09:00:00',NULL,'2018-08-03 00:00:00','2018-08-26 10:00:00','2018-09-30 00:00:00');
    INSERT INTO orders VALUES ('{OB}','c3','delivered','2018-08-01 09:00:00',NULL,'2018-08-03 00:00:00','2018-08-25 10:00:00','2018-09-30 00:00:00');
    INSERT INTO order_items VALUES ('{O1}',1,'p1','s1','2018-08-05 00:00:00',100,10);
    INSERT INTO order_items VALUES ('{OBIG}',1,'p1','s1','2018-08-05 00:00:00',600,20);
    INSERT INTO order_items VALUES ('{OB}',1,'p1','s1','2018-08-05 00:00:00',100,10);
    INSERT INTO order_payments VALUES ('{O1}',1,'credit_card',1,110);
    """)
    return c


def n_returns(c):
    return c.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]


# ---- G2 yetki
def test_foreign_orders_all_not_found_identical(con):
    s = Session(A)
    fakes = [OB] + [f"{i:032x}" for i in range(9)]
    res = [st.get_order_status(con, s, o) for o in fakes]
    assert all(r == st.NOT_FOUND for r in res)  # 10/10 aynı yanıt: varlık ifşası yok

def test_own_order_visible(con):
    r = st.get_order_status(con, Session(A), O1)
    assert r["status"] == "delivered" and r["items"][0]["price"] == 100

def test_list_orders_only_own_newest_first(con):
    r = st.list_customer_orders(con, Session(A), limit=5)["orders"]
    assert [o["order_id"] for o in r] == [OBIG, O1]  # B'nin siparişi yok

def test_list_validation(con):
    assert st.list_customer_orders(con, Session(A), limit=99)["error"] == "INVALID_ARGUMENT"
    assert st.list_customer_orders(con, Session(A), status="bogus")["error"] == "INVALID_ARGUMENT"

def test_ops_session_has_no_customer_tools(con):
    assert st.get_order_status(con, Session(A, role="ops"), O1)["error"] == "FORBIDDEN"

# ---- G1 HITL
def test_no_write_without_approval(con):
    s = Session(A)
    r = st.create_return_request(con, s, O1, "changed_mind", 100.0)
    assert r["error"] == "APPROVAL_REQUIRED" and n_returns(con) == 0

def test_llm_cannot_fake_approval(con):
    s = Session(A)
    pid = st.create_return_request(con, s, O1, "changed_mind", 100.0)["proposal_id"]
    for fake in (pid, "approved", "true", "prop_xyz"):  # insan onaylamadı
        assert st.create_return_request(con, s, O1, "changed_mind", 100.0, fake)["error"] == "APPROVAL_REQUIRED"
    assert n_returns(con) == 0

def test_approved_creates_single_row_with_status(con):
    s = Session(A)
    pid = st.create_return_request(con, s, O1, "changed_mind", 100.0)["proposal_id"]
    assert s.gate.approve(pid)
    r = st.create_return_request(con, s, O1, "changed_mind", 100.0, pid)
    assert r["status"] == "PENDING_REVIEW" and n_returns(con) == 1
    # tek kullanımlık + R11
    assert st.create_return_request(con, s, O1, "changed_mind", 100.0, pid)["error"] == "DUPLICATE_REQUEST"
    assert n_returns(con) == 1

def test_r10_senior_status(con):
    s = Session(A)
    pid = st.create_return_request(con, s, OBIG, "changed_mind", 600.0)["proposal_id"]
    s.gate.approve(pid)
    assert st.create_return_request(con, s, OBIG, "changed_mind", 600.0, pid)["status"] == "PENDING_SENIOR"

def test_approval_bound_to_parameters(con):
    s = Session(A)
    pid = st.create_return_request(con, s, O1, "changed_mind", 100.0)["proposal_id"]
    s.gate.approve(pid)
    # onay changed_mind/100 içindi; damaged (110) için kullanılamaz
    r = st.create_return_request(con, s, O1, "damaged", 110.0, pid)
    assert r["error"] == "APPROVAL_REQUIRED" and n_returns(con) == 0

def test_amount_comes_from_rule_engine(con):
    r = st.create_return_request(con, Session(A), O1, "changed_mind", 9999.0)
    assert r["error"] == "AMOUNT_MISMATCH" and r["expected_amount"] == 100.0 and n_returns(con) == 0

def test_foreign_order_cannot_open_request(con):
    r = st.create_return_request(con, Session(A), OB, "changed_mind", 100.0)
    assert r == st.NOT_FOUND and n_returns(con) == 0

def test_not_eligible_gives_no_proposal(con):
    con.execute(f"UPDATE orders SET order_delivered_customer_date='2018-07-01 10:00:00' WHERE order_id='{O1}'")
    r = st.create_return_request(con, Session(A), O1, "changed_mind", 100.0)
    assert r["error"] == "NOT_ELIGIBLE" and "proposal_id" not in r

# ---- G6 / escalate
def test_escalation_redacts_raw_ids():
    st.ESCALATIONS.clear()
    r = st.escalate_to_human(Session(A), f"Müşteri {A} sipariş {O1} için şikayet etti", "high")
    assert r["priority"] == "high"
    t = st.ESCALATIONS[0]
    assert not re.search(r"[0-9a-f]{32}", t["summary"]) and A not in t["customer"]

def test_escalation_validation():
    assert st.escalate_to_human(Session(A), "x", "urgent")["error"] == "INVALID_ARGUMENT"
    assert st.escalate_to_human(Session(A), "  ")["error"] == "INVALID_ARGUMENT"
