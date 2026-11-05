"""ShopOps — Pazaryeri Müşteri Destek & Operasyon Arayüzü.

  * Müşteri Destek: sohbet, ara adımlar paneli, canlı HITL onay kartı (yazma YALNIZ onay butonundan geçer)
  * Operasyon Analitiği: tanımlı metrik paneli (SQL + caveat) ve doğal dil analiz sohbeti
  * Simülasyon zamanı: SIMULATED_TODAY = 2018-09-01
  * Veritabanı repoda yoktur; yoksa açılışta Olist verisi indirilip kurulur
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import gradio as gr
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config  
from src.agents.ops_agent import OpsCtx, build_ops_agent
from src.agents.support_agent import Ctx, StepLogger, build_agent, make_model 
from src.tools import ops_tools, support_tools as st_tools  
from src.tools.session import Session  
from src.ui_common import friendly_error, steps_markdown, summarize_trace  


try:
    import spaces

    @spaces.GPU
    def _zerogpu_placeholder() -> None:
        return None
except ImportError:
    pass

# --- Veritabanı ---------------------------------------------------------------
DB_ERROR: str | None = None
try:
    from src.data_bootstrap import ensure_db
    ensure_db(config.DB_PATH)
except Exception:
    import traceback
    traceback.print_exc()
    DB_ERROR = "⚠️ Veritabanı kurulamadı. Lütfen birkaç dakika sonra sayfayı yenileyin."

WRITE_LOCK = threading.Lock()   # tek yazma bağlantısı tüm ziyaretçiler arasında paylaşılır


@lru_cache(maxsize=1)
def get_db_connections():
    con_ro = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    con_rw = sqlite3.connect(config.DB_PATH, isolation_level=None, check_same_thread=False)
    return con_ro, con_rw


@lru_cache(maxsize=1)
def get_demo_customers():
    con_ro, _ = get_db_connections()
    return con_ro.execute("""
        SELECT c.customer_unique_id, o.order_id, o.order_status,
               DATE(o.order_delivered_customer_date) as deliv_date,
               ROUND(SUM(i.price), 2) as total_price
        FROM orders o
        JOIN customers c USING(customer_id)
        JOIN order_items i USING(order_id)
        WHERE o.order_status = 'delivered'
          AND o.order_delivered_customer_date IS NOT NULL
          AND DATE(o.order_delivered_customer_date) <= DATE('2018-09-01')
          AND julianday('2018-09-01') - julianday(DATE(o.order_delivered_customer_date)) BETWEEN 1 AND 14
        GROUP BY o.order_id
        ORDER BY o.order_delivered_customer_date DESC
        LIMIT 5
    """).fetchall()


def _demo_labels() -> dict[str, str]:
    return {f"Demo müşteri {n} (Sipariş: {d[1][:6]}…, {d[4]} BRL)": d[0] for n, d in enumerate(get_demo_customers(), 1)}


# --- Oturum durumu (her ziyaretçi için ayrı) -------------------------------------
@dataclass
class UIState:
    cust: Session
    ops: Session
    cust_msgs: list = field(default_factory=list)
    ops_msgs: list = field(default_factory=list)
    cust_steps: list = field(default_factory=list)
    ops_steps: list = field(default_factory=list)
    pending: dict | None = None
    note: str | None = None
    created: list = field(default_factory=list)
    cust_bundle: tuple | None = None
    ops_bundle: tuple | None = None


def new_state() -> UIState:
    demos = get_demo_customers()
    uid = demos[0][0] if demos else "no-demo-customer"
    return UIState(cust=Session(uid, role="customer"), ops=Session("ops-demo", role="ops"))


def _ensure(s: UIState | None) -> UIState:
    return s if isinstance(s, UIState) else new_state()


def _support_agent(s: UIState):
    key = s.cust.customer_unique_id
    if s.cust_bundle is None or s.cust_bundle[0] != key:
        con_ro, _ = get_db_connections()
       
        ctx = Ctx(con_ro, con_ro, s.cust, confirm=None, defer_approval=True)
        s.cust_bundle = (key, ctx, build_agent(ctx, model=make_model(), logger=StepLogger(), verbosity=0))
    return s.cust_bundle[1], s.cust_bundle[2]


def _ops_agent(s: UIState):
    if s.ops_bundle is None:
        con_ro, _ = get_db_connections()
        logger = StepLogger()
        s.ops_bundle = (build_ops_agent(OpsCtx(con_ro, s.ops), model=make_model(), logger=logger, verbosity=0), logger)
    return s.ops_bundle


# --- Müşteri işleyicileri ---------------------------------------------------------
def _hitl_text(p: dict | None) -> str:
    if not p:
        return ""
    kind = " *(yalnız kargo bedeli)*" if p.get("freight_only") else ""
    return (f"### 📋 İade Talebi Özeti\n\n**Sipariş:** `{p['order_id'][:8]}…`  \n**Neden:** `{p['reason']}`  \n"
            f"**İade tutarı:** `{p['refund_amount']} BRL`{kind}  \n**Onay seviyesi:** `{p['approval_level']}`\n\n"
            "Bu talebin oluşturulmasını onaylıyor musunuz?")


def _cust_view(s: UIState):
    return (list(s.cust_msgs), "", steps_markdown(s.cust_steps), gr.update(visible=bool(s.pending)), _hitl_text(s.pending), s)


def customer_send(text: str, s: UIState | None):
    s = _ensure(s)
    text = (text or "").strip()
    if not text:
        return _cust_view(s)
    s.cust_msgs.append({"role": "user", "content": text})
    try:
        ctx, agent = _support_agent(s)
        ctx.calls.clear()      # tekrar koruması tur başına sayılır
        ctx.trace.clear()
        ctx.pending = None
        note, s.note = s.note, None
        answer = str(agent.run((note + "\n" if note else "") + text, reset=False))
        if ctx.pending:
            s.pending = ctx.pending
        s.cust_steps = summarize_trace(ctx.trace)
    except Exception as e: 
        answer = friendly_error(e)
        s.cust_steps = []
    s.cust_msgs.append({"role": "assistant", "content": answer})
    return _cust_view(s)


def customer_approve(s: UIState | None):
    s = _ensure(s)
    p = s.pending
    if p:
        s.cust.gate.approve(p["proposal_id"])   # onay YALNIZ bu insan düğmesinden geçer
        _, con_rw = get_db_connections()
        with WRITE_LOCK:
            res = st_tools.create_return_request(con_rw, s.cust, p["order_id"], p["reason"],
                                                 p["refund_amount"], p["proposal_id"])
        if "return_request_id" in res:
            s.created.append(res["return_request_id"])
            text = (f"✅ İade talebiniz oluşturuldu. Talep No: **#{res['return_request_id']}**, "
                    f"Durum: **{res['status']}**, İade Tutarı: **{res['refund_amount']} BRL**.")
            s.note = f"[SİSTEM: Müşteri onayladı; iade talebi #{res['return_request_id']} açıldı.]"
        else:
            text = f"❌ Talep açılamadı: {res.get('message', 'bilinmeyen neden')}"
            s.note = "[SİSTEM: Talep açılamadı.]"
        s.cust_msgs.append({"role": "assistant", "content": text})
        s.pending = None
    return _cust_view(s)


def customer_reject(s: UIState | None):
    s = _ensure(s)
    if s.pending:
        s.cust_msgs.append({"role": "assistant", "content":
                            "İade talebini onaylamadınız; talep açılmadı. Başka bir konuda yardımcı olabilir miyim?"})
        s.note = "[SİSTEM: Müşteri iade talebini onaylamadı; talep açılmadı.]"
        s.pending = None
    return _cust_view(s)


def customer_reset(s: UIState | None):
    s = _ensure(s)
    s.cust_msgs, s.cust_steps, s.pending, s.note, s.cust_bundle = [], [], None, None, None
    return _cust_view(s)


def customer_pick(label: str, s: UIState | None):
    s = _ensure(s)
    uid = _demo_labels().get(label)
    if uid:
        s.cust.customer_unique_id = uid
    return customer_reset(s)


def demo_reset(s: UIState | None):
    """Bu oturumda açılan iade taleplerini siler; demo siparişi tekrar denenebilir."""
    s = _ensure(s)
    if s.created:
        _, con_rw = get_db_connections()
        with WRITE_LOCK:
            con_rw.execute(f"DELETE FROM return_requests WHERE request_id IN ({','.join('?' * len(s.created))})", s.created)
        s.created = []
    return customer_reset(s)


def make_quick(text: str):
    def _f(s):
        return customer_send(text, s)
    return _f


# --- Operasyon işleyicileri -------------------------------------------------------
def ops_send(text: str, s: UIState | None):
    s = _ensure(s)
    text = (text or "").strip()
    if text:
        s.ops_msgs.append({"role": "user", "content": text})
        try:
            agent, logger = _ops_agent(s)
            start = len(logger.records)
            ans = str(agent.run(text, reset=False))
            s.ops_steps = [{"tool": t["name"], "args": str(t["args"])[:220], "result": "—"}
                           for r in logger.records[start:] for t in r.get("tools", []) if t["name"] != "final_answer"]
        except Exception as e:  # noqa: BLE001
            ans = friendly_error(e)
            s.ops_steps = []
        s.ops_msgs.append({"role": "assistant", "content": ans})
    return list(s.ops_msgs), "", steps_markdown(s.ops_steps), s


def metric_choices():
    return [(f"{v.get('title', k)} ({k})", k) for k, v in ops_tools.load_metrics_def().items()]


def metric_changed(metric: str):
    m = ops_tools.load_metrics_def().get(metric, {})
    return gr.update(choices=list(m.get("dimensions", {}).keys()), value=[]), f"ℹ️ {m.get('description', '')}"


def metric_run(metric: str, dims: list | None, limit: float, s: UIState | None):
    s = _ensure(s)
    con_ro, _ = get_db_connections()
    res = ops_tools.run_metric(con_ro, s.ops, metric, dimensions=list(dims or []), limit=int(limit or 20))
    if "error" in res:
        return f"❌ {res.get('message', 'Hata')}", pd.DataFrame(), "", s
    status = f"✅ {len(res['data'])} satır.\n\n⚠️ **Caveat / gözlemsel sınır:** {res.get('caveat', '')}"
    return status, pd.DataFrame(res["data"]), res.get("sql", ""), s


# --- Arayüz -----------------------------------------------------------------------
HEADER = ("# 🛍️ ShopOps — Pazaryeri Destek & Operasyon Ajanı\n"
          f"📅 Sistemde bugün: **{config.SIMULATED_TODAY}** · 🤖 `{config.LLM_PROVIDER}/{config.LLM_MODEL}` · "
          "🔒 Salt-okunur agent + insan onayı")
FOOTER = ("Veri: Olist Brazilian E-Commerce Public Dataset (Kaggle), CC BY-NC-SA 4.0. Senaryo kurgusaldır; "
          "tarihler 2018'dendir. Demo: sekmeler kimlik doğrulamanın yerini tutar.")


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="ShopOps — Destek & Operasyon Ajanı") as demo:
        state = gr.State(None)
        gr.Markdown(HEADER)
        if DB_ERROR:
            gr.Markdown(DB_ERROR)
            return demo

        with gr.Tabs():
            # ---------------- Müşteri ----------------
            with gr.Tab("💬 Müşteri Destek"):
                labels = list(_demo_labels().keys())
                picker = gr.Dropdown(labels, value=labels[0] if labels else None, label="Demo müşteri")
                chat = gr.Chatbot(height=380, label="Örnekpazar Destek Asistanı")
                with gr.Row():
                    box = gr.Textbox(placeholder="Mesajınızı yazın…", show_label=False, scale=8)
                    send = gr.Button("Gönder", variant="primary", scale=1)
                with gr.Row():
                    quick = [gr.Button(t) for t in ("📦 Son siparişlerimi listele", "❓ İade politikası nedir?",
                                                     "🚚 Kargo gecikmesi iadesi")]
                with gr.Accordion("🔎 Ara adımlar (son yanıt)", open=False):
                    steps = gr.Markdown("_Henüz tool çağrısı yok._")
                with gr.Group(visible=False) as hitl:
                    gr.Markdown("⚠️ **İNSAN ONAYI GEREKİYOR (Human-in-the-Loop)**")
                    hitl_md = gr.Markdown()
                    with gr.Row():
                        approve = gr.Button("✅ Talebi Onayla", variant="primary")
                        reject = gr.Button("❌ Reddet / İptal Et")
                with gr.Row():
                    clear = gr.Button("🗑️ Sohbeti temizle")
                    reset = gr.Button("♻️ Demo verisini sıfırla")

                out = [chat, box, steps, hitl, hitl_md, state]
                box.submit(customer_send, [box, state], out, api_name="customer_send")
                send.click(customer_send, [box, state], out, api_name=False)
                for btn, text in zip(quick, ("Son siparişlerimi listeler misiniz?",
                                             "Ürünleri kaç gün içinde iade edebilirim?",
                                             "Siparişim çok geç geldi, kargo paramı geri alabilir miyim?")):
                    btn.click(make_quick(text), [state], out, api_name=False)
                approve.click(customer_approve, [state], out, api_name="customer_approve")
                reject.click(customer_reject, [state], out, api_name="customer_reject")
                clear.click(customer_reset, [state], out, api_name=False)
                reset.click(demo_reset, [state], out, api_name=False)
                picker.change(customer_pick, [picker, state], out, api_name=False)

            # ---------------- Operasyon ----------------
            with gr.Tab("📊 Operasyon Analitiği"):
                with gr.Tabs():
                    with gr.Tab("📈 Hızlı metrik paneli"):
                        choices = metric_choices()
                        with gr.Row():
                            metric = gr.Dropdown(choices, value=choices[0][1], label="Metrik")
                            dims = gr.CheckboxGroup(label="Gruplama boyutları (opsiyonel)")
                            limit = gr.Number(value=20, label="Satır sınırı", minimum=5, maximum=500, precision=0)
                        desc = gr.Markdown()
                        calc = gr.Button("🚀 Metriği hesapla", variant="primary")
                        status = gr.Markdown()
                        table = gr.Dataframe(label="Sonuç", wrap=True)
                        sql = gr.Code(label="Üretilen SQL", language="sql")
                        metric.change(metric_changed, [metric], [dims, desc], api_name=False)
                        demo.load(metric_changed, [metric], [dims, desc], api_name=False)
                        calc.click(metric_run, [metric, dims, limit, state], [status, table, sql, state], api_name="metric_run")
                    with gr.Tab("💬 Doğal dil & SQL analiz sohbeti"):
                        ochat = gr.Chatbot(height=380, label="Operasyon Veri Analisti")
                        with gr.Row():
                            obox = gr.Textbox(placeholder="Örn: São Paulo eyaletinde geç teslim oranı nedir?",
                                              show_label=False, scale=8)
                            osend = gr.Button("Gönder", variant="primary", scale=1)
                        with gr.Accordion("🔎 Ara adımlar (son yanıt)", open=False):
                            osteps = gr.Markdown("_Henüz tool çağrısı yok._")
                        oout = [ochat, obox, osteps, state]
                        obox.submit(ops_send, [obox, state], oout, api_name="ops_send")
                        osend.click(ops_send, [obox, state], oout, api_name=False)

        gr.Markdown(FOOTER)
        demo.load(new_state, None, [state], api_name=False)
    return demo


demo = build_ui()
demo.queue(default_concurrency_limit=4)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft())
