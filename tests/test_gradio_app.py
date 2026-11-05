"""Gradio app.py testleri: işleyiciler (sahte model) + gerçek sunucu/istemci smoke. DB yoksa atlanır."""
import sqlite3

import gradio as gr
import pytest

import config
from tests.test_ops_agent import ScriptedOpsModel
from tests.test_support_agent import Scripted

pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="shopops.db yok")


@pytest.fixture
def app():
    import app as app_module
    return app_module


@pytest.fixture
def demo(app):
    c = sqlite3.connect(config.DB_PATH)
    c.execute("DELETE FROM return_requests"); c.commit()
    uid, oid = app.get_demo_customers()[0][0], app.get_demo_customers()[0][1]
    from src.tools.returns import check_return_eligibility
    amt = check_return_eligibility(c, oid, uid, "changed_mind")["refund_amount"]
    yield oid, amt
    c.execute("DELETE FROM return_requests"); c.commit()


def n_rows():
    return sqlite3.connect(config.DB_PATH).execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]


def test_ui_builds_and_db_ready(app):
    assert isinstance(app.demo, gr.Blocks) and app.DB_ERROR is None


def test_approve_flow(app, demo, monkeypatch):
    oid, amt = demo
    monkeypatch.setattr(app, "make_model", lambda: Scripted([
        ("check_return_eligibility", {"order_id": oid, "reason": "changed_mind"}),
        ("create_return_request", {"order_id": oid, "reason": "changed_mind", "amount": amt}),
        ("final_answer", {"answer": "Onay kartını kontrol edin."})]))
    s = app.new_state()
    chat, _, steps, hitl, hitl_md, s = app.customer_send("iade etmek istiyorum", s)
    assert s.pending and s.pending["proposal_id"] and n_rows() == 0          # onaysız yazma yok
    assert hitl["visible"] is True and "İade Talebi Özeti" in hitl_md
    assert "create_return_request" in steps                                    # ara adımlar görünür
    chat, _, _, hitl, _, s = app.customer_approve(s)
    assert n_rows() == 1 and s.pending is None and hitl["visible"] is False
    assert "oluşturuldu" in chat[-1]["content"]


def test_reject_writes_nothing(app, demo, monkeypatch):
    oid, amt = demo
    monkeypatch.setattr(app, "make_model", lambda: Scripted([
        ("create_return_request", {"order_id": oid, "reason": "changed_mind", "amount": amt}),
        ("final_answer", {"answer": "Kartı kontrol edin."})]))
    s = app.new_state()
    *_, s = app.customer_send("iade", s)
    *_, s = app.customer_reject(s)
    assert n_rows() == 0 and s.pending is None


def test_quick_button_memory_and_repeat_guard(app, demo, monkeypatch):
    monkeypatch.setattr(app, "make_model", lambda: Scripted(
        [("list_customer_orders", {}), ("final_answer", {"answer": "Siparişleriniz listelendi."})] * 3))
    s = app.new_state()
    chat, *_, s = app.make_quick("Son siparişlerimi listeler misiniz?")(s)
    assert "listelendi" in chat[-1]["content"]
    first = s.cust_bundle[2]
    for _ in range(2):
        *_, s = app.customer_send("tekrar listele", s)
    assert s.cust_bundle[2] is first and all(x["result"] != "REPEATED_CALL" for x in s.cust_steps)
    assert len(s.cust_msgs) == 6                                               # konuşma geçmişi birikir


def test_quota_error_is_friendly(app, monkeypatch):
    def boom():
        raise RuntimeError("Error code: 429 - RESOURCE_EXHAUSTED")
    monkeypatch.setattr(app, "make_model", boom)
    chat, *_ = app.customer_send("merhaba", app.new_state())
    assert "kota" in chat[-1]["content"].lower() and "429" not in chat[-1]["content"]


def test_demo_reset(app, demo, monkeypatch):
    oid, amt = demo
    monkeypatch.setattr(app, "make_model", lambda: Scripted([
        ("create_return_request", {"order_id": oid, "reason": "changed_mind", "amount": amt}),
        ("final_answer", {"answer": "ok"})]))
    s = app.new_state()
    *_, s = app.customer_send("iade", s)
    *_, s = app.customer_approve(s)
    assert n_rows() == 1
    *_, s = app.demo_reset(s)
    assert n_rows() == 0 and s.created == []


def test_ops_metric_panel_and_chat(app, monkeypatch):
    status, df, sql, s = app.metric_run("late_delivery_rate", ["customer_state"], 5, None)
    assert "Caveat" in status and len(df) > 0 and "SELECT" in sql
    monkeypatch.setattr(app, "make_model", lambda: ScriptedOpsModel([
        ("run_metric", {"metric_name": "order_count"}), ("final_answer", {"answer": "Sipariş sayısı hesaplandı."})]))
    chat, _, steps, s = app.ops_send("Kaç sipariş var?", s)
    assert "hesaplandı" in chat[-1]["content"] and "run_metric" in steps


def test_real_server_roundtrip_with_client(app, demo, monkeypatch):
    from gradio_client import Client
    oid, amt = demo
    monkeypatch.setattr(app, "make_model", lambda: Scripted(
        [("list_customer_orders", {}), ("final_answer", {"answer": "Listelendi."})] * 2))
    app.demo.launch(prevent_thread_lock=True, quiet=True, theme=gr.themes.Soft())
    try:
        c = Client(app.demo.local_url, verbose=False)
        r1 = c.predict("Son siparişlerimi listeler misiniz?", api_name="/customer_send")
        r2 = c.predict("bir daha", api_name="/customer_send")
        assert len(r1[0]) == 2 and len(r2[0]) == 4        # oturum durumu çağrılar arasında korunuyor
    finally:
        app.demo.close()
