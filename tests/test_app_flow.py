"""app.py'yi Streamlit AppTest ile uçtan uca dener (sahte model; LLM ve kota gerekmez). DB yoksa atlanır."""
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
import src.agents.support_agent as sa
from src.tools.returns import check_return_eligibility
from tests.test_support_agent import Scripted

APP = str(Path(__file__).resolve().parents[1] / "app_streamlit.py")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="shopops.db yok")


def _rows():
    return sqlite3.connect(config.DB_PATH).execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]


@pytest.fixture
def demo():
    c = sqlite3.connect(config.DB_PATH)
    c.execute("DELETE FROM return_requests"); c.commit()
    uid, oid = c.execute("""SELECT c.customer_unique_id, o.order_id FROM orders o JOIN customers c USING(customer_id)
        JOIN order_items i USING(order_id) WHERE o.order_status='delivered'
        AND julianday('2018-09-01')-julianday(DATE(o.order_delivered_customer_date)) BETWEEN 1 AND 14
        GROUP BY o.order_id ORDER BY o.order_delivered_customer_date DESC LIMIT 1""").fetchone()
    amt = check_return_eligibility(c, oid, uid, "changed_mind")["refund_amount"]
    yield oid, amt
    c.execute("DELETE FROM return_requests"); c.commit()


def _app(monkeypatch, calls):
    monkeypatch.setattr(sa, "make_model", lambda: Scripted(calls))
    return AppTest.from_file(APP, default_timeout=60).run()


def _click(at, label):
    next(b for b in at.button if label in b.label).click().run()


def test_approve_creates_request_and_no_crash(monkeypatch, demo):
    oid, amt = demo
    at = _app(monkeypatch, [("check_return_eligibility", {"order_id": oid, "reason": "changed_mind"}),
                            ("create_return_request", {"order_id": oid, "reason": "changed_mind", "amount": amt}),
                            ("final_answer", {"answer": "Onay kartını kontrol edin."})])
    at.chat_input[0].set_value("iade etmek istiyorum").run()
    assert not at.exception and at.session_state["pending_proposal"]["proposal_id"] and _rows() == 0
    _click(at, "Talebi Onayla")
    assert not at.exception and _rows() == 1
    assert "oluşturuldu" in at.session_state["messages"][-1]["content"]
    assert at.session_state["pending_proposal"] is None


def test_decline_writes_nothing(monkeypatch, demo):
    oid, amt = demo
    at = _app(monkeypatch, [("create_return_request", {"order_id": oid, "reason": "changed_mind", "amount": amt}),
                            ("final_answer", {"answer": "Kartı kontrol edin."})])
    at.chat_input[0].set_value("iade").run()
    _click(at, "Reddet")
    assert not at.exception and _rows() == 0 and at.session_state["pending_proposal"] is None


def test_quick_button_runs_agent_and_memory_persists(monkeypatch, demo):
    calls = [("list_customer_orders", {}), ("final_answer", {"answer": "Siparişleriniz listelendi."})] * 3
    at = _app(monkeypatch, calls)
    _click(at, "Son siparişlerimi listele")
    assert not at.exception and "listelendi" in at.session_state["messages"][-1]["content"]
    first = at.session_state["support_bundle"][2]
    for _ in range(2):   # aynı çağrı 3 tur: tur başı sayaç sıfırlandığı için REPEATED_CALL olmamalı
        at.chat_input[0].set_value("tekrar listele").run()
    assert at.session_state["support_bundle"][2] is first          # aynı agent: konuşma hafızası korunur
    assert all(s["result"] != "REPEATED_CALL" for s in at.session_state["last_steps"])


def test_quota_error_is_friendly(monkeypatch, demo):
    def boom():
        raise RuntimeError("Error code: 429 - RESOURCE_EXHAUSTED quota")
    monkeypatch.setattr(sa, "make_model", boom)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("merhaba").run()
    assert not at.exception and "kota" in at.session_state["messages"][-1]["content"].lower()
    assert "429" not in at.session_state["messages"][-1]["content"]    # ham hata sızmaz


def test_demo_reset_removes_session_requests(monkeypatch, demo):
    oid, amt = demo
    at = _app(monkeypatch, [("create_return_request", {"order_id": oid, "reason": "changed_mind", "amount": amt}),
                            ("final_answer", {"answer": "ok"})])
    at.chat_input[0].set_value("iade").run()
    _click(at, "Talebi Onayla")
    assert _rows() == 1
    _click(at, "Demo verisini sıfırla")
    assert not at.exception and _rows() == 0
