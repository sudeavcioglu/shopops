"""ShopOps — Pazaryeri Müşteri Destek & Operasyon Web Arayüzü (Streamlit).

Özellikler:
  * Müşteri Destek (Ayşe/Mert) ve Operasyon (Selin) oturumları; yetki oturum nesnesinden gelir
  * Canlı HITL onay ekranı: iade özet kartı + Onayla / Reddet (yazma YALNIZ bu butondan geçer)
  * Ara adımlar paneli: agent'ın hangi tool'u hangi argümanla çağırdığı ve ne döndüğü
  * Operasyon paneli: tanımlı metrikler, üretilen SQL, grafik ve zorunlu caveat
  * Simülasyon zamanı: SIMULATED_TODAY = 2018-09-01
  * İlk açılışta veritabanı yoksa Olist verisi indirilip kurulur (repoda DB yok)

Demo notu: rol ve müşteri seçici, gerçek bir kimlik doğrulamanın yerini tutar.
Canlı sistemde rol ve kimlik giriş (auth) katmanından gelir, kullanıcı seçemez.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Streamlit Cloud sırlarını, config import edilmeden önce ortam değişkenine aktar
try:
    for _k in ("GEMINI_API_KEY", "GROQ_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # secrets.toml yoksa sorun değil (.env kullanılır)
    pass

import config  # noqa: E402
from src.agents.ops_agent import OpsCtx, build_ops_agent  # noqa: E402
from src.agents.support_agent import Ctx, StepLogger, build_agent, make_model  # noqa: E402
from src.guardrails.pii import redact_ids  # noqa: E402
from src.tools import ops_tools, support_tools as st_tools  # noqa: E402
from src.tools.session import Session  # noqa: E402

st.set_page_config(
    page_title="ShopOps — E-Ticaret Destek & Operasyon Ajanı",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Herkese açık demoda keyfi müşteri kimliği girişi kapalıdır (yerelde SHOPOPS_ALLOW_CUSTOM_ID=1)
ALLOW_CUSTOM_ID = os.getenv("SHOPOPS_ALLOW_CUSTOM_ID", "0") == "1"


# --- Veritabanı ---------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def prepare_db() -> str:
    from src.data_bootstrap import ensure_db
    return str(ensure_db(config.DB_PATH))


if not Path(config.DB_PATH).exists():
    try:
        with st.status("İlk açılış: Olist verisi indirilip veritabanı kuruluyor (1-2 dk sürebilir)…", expanded=True):
            prepare_db()
    except Exception:
        st.error("Veritabanı kurulamadı. Lütfen birkaç dakika sonra sayfayı yenileyin.")
        st.stop()


@st.cache_resource
def get_db_connections():
    con_ro = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    con_rw = sqlite3.connect(config.DB_PATH, isolation_level=None, check_same_thread=False)
    return con_ro, con_rw


@st.cache_resource
def get_write_lock() -> threading.Lock:
    """Tek yazma bağlantısı tüm ziyaretçiler arasında paylaşılır; yazmalar sıraya girer."""
    return threading.Lock()


@st.cache_data
def get_demo_customers():
    con_ro, _ = get_db_connections()
    cur = con_ro.execute("""
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
    """)
    return cur.fetchall()


con_ro, con_rw = get_db_connections()


# --- Yardımcılar ---------------------------------------------------------------
def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pending_proposal = None
    st.session_state.last_steps = []
    st.session_state.support_bundle = None
    st.session_state.ops_bundle = None
    st.session_state.system_note = None


def friendly_error(e: Exception) -> str:
    t = str(e).lower()
    if any(k in t for k in ("429", "quota", "resource_exhausted", "rate limit", "rate_limit")):
        return "⏳ Demo model kotası şu an dolu. Lütfen bir dakika sonra tekrar deneyin."
    if any(k in t for k in ("gemini_api_key", "groq_api_key", "api key", "api_key", "401", "403", "unauthorized")):
        return "🔑 Model anahtarı bulunamadı ya da geçersiz görünüyor. Lütfen demo sahibine bildirin."
    if any(k in t for k in ("timeout", "timed out", "connection", "unavailable", "503", "502")):
        return "🌐 Model servisine şu an ulaşılamıyor. Birkaç saniye sonra tekrar deneyin."
    return "Beklenmeyen bir hata oluştu. Lütfen mesajınızı yeniden gönderin."


def _short(res) -> str:
    if not isinstance(res, dict):
        return str(res)[:80]
    for k in ("decision", "error", "status"):
        if k in res:
            extra = f" · {res['refund_amount']} BRL" if "refund_amount" in res else ""
            return f"{res[k]}{extra}"
    if "orders" in res:
        return f"{len(res['orders'])} sipariş"
    if "results" in res:
        return f"{len(res['results'])} politika parçası"
    if "data" in res:
        return f"{res.get('row_count', len(res['data']))} satır"
    return ", ".join(list(res.keys())[:4])


def summarize_trace(trace: list) -> list[dict]:
    out = []
    for name, args, res in trace:
        a = redact_ids(json.dumps(args, ensure_ascii=False, default=str))
        out.append({"tool": name, "args": a[:220], "result": _short(res)})
    return out


def render_steps(steps: list[dict]) -> None:
    with st.expander(f"🔎 Ara adımlar ({len(steps)} tool çağrısı)", expanded=False):
        if not steps:
            st.caption("Bu yanıt için tool çağrılmadı.")
        for i, s in enumerate(steps, 1):
            st.markdown(f"**{i}. `{s['tool']}`** → {s['result']}")
            st.code(s["args"], language="json")


def get_support_agent():
    sess = st.session_state.current_session
    key = (sess.role, sess.customer_unique_id)
    b = st.session_state.support_bundle
    if b is None or b[0] != key:
        # Agent'a SALT-OKUNUR bağlantı verilir: onaylanana kadar yazması fiziksel olarak da mümkün değil.
        ctx = Ctx(con_ro, con_ro, sess, confirm=None, defer_approval=True)
        b = (key, ctx, build_agent(ctx, model=make_model(), logger=StepLogger(), verbosity=0))
        st.session_state.support_bundle = b
    return b[1], b[2]


def get_ops_agent():
    sess = st.session_state.current_session
    b = st.session_state.ops_bundle
    if b is None or b[0] != sess.role:
        logger = StepLogger()
        ctx = OpsCtx(con_ro, sess)
        b = (sess.role, build_ops_agent(ctx, model=make_model(), logger=logger, verbosity=0), logger)
        st.session_state.ops_bundle = b
    return b[1], b[2]


# --- Session State -------------------------------------------------------------
for _k, _v in {"messages": [], "pending_proposal": None, "created_requests": [], "last_steps": [],
               "support_bundle": None, "ops_bundle": None, "system_note": None}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v
if "current_session" not in st.session_state:
    demos = get_demo_customers()
    default_uid = demos[0][0] if demos else "a71cac9f356cfeb9db35061020806212"
    st.session_state.current_session = Session(default_uid, role="customer")

# --- SIDEBAR -------------------------------------------------------------------
with st.sidebar:
    st.title("🛍️ ShopOps")
    st.caption("Pazaryeri Müşteri Destek & Operasyon Sistemi")
    st.markdown("---")

    role_choice = st.radio(
        "👤 **Oturum Rolü Seçin:**",
        ["Müşteri Destek (Ayşe & Mert)", "Operasyon Analitiği (Selin)"],
        index=0 if st.session_state.current_session.role == "customer" else 1,
    )
    st.caption("Demo: rol seçimi kimlik doğrulamanın yerini tutar; canlıda rol giriş katmanından gelir.")
    new_role = "customer" if "Müşteri" in role_choice else "ops"
    if new_role != st.session_state.current_session.role:
        st.session_state.current_session.role = new_role
        reset_chat()
        st.rerun()

    if st.session_state.current_session.role == "customer":
        st.subheader("Oturum Kimliği")
        demos = get_demo_customers()
        demo_dict = {f"Demo müşteri {n} (Sipariş: {d[1][:6]}…, {d[4]} BRL)": d[0] for n, d in enumerate(demos, 1)}
        if ALLOW_CUSTOM_ID:
            demo_dict["Özel / Manuel ID"] = "custom"
        sel = st.selectbox("Demo Müşteri Seçin:", list(demo_dict.keys()))
        if demo_dict[sel] != "custom":
            if st.session_state.current_session.customer_unique_id != demo_dict[sel]:
                st.session_state.current_session.customer_unique_id = demo_dict[sel]
                reset_chat()
                st.rerun()
        else:
            custom_id = st.text_input("customer_unique_id:", value=st.session_state.current_session.customer_unique_id)
            if custom_id != st.session_state.current_session.customer_unique_id:
                st.session_state.current_session.customer_unique_id = custom_id
                reset_chat()
                st.rerun()

    st.markdown("---")
    st.info(f"📅 **Bugün:** `{config.SIMULATED_TODAY}`\n\n"
            f"🤖 **Model:** `{config.LLM_PROVIDER} / {config.LLM_MODEL}`\n\n"
            f"🔒 **Güvenlik:** Salt-okunur agent + insan onayı")

    if st.button("🗑️ Sohbeti Temizle", use_container_width=True):
        reset_chat()
        st.rerun()

    if st.session_state.created_requests and st.button(
            "♻️ Demo verisini sıfırla", use_container_width=True,
            help="Bu oturumda açılan iade taleplerini siler; demo siparişi tekrar denenebilir."):
        ids = list(st.session_state.created_requests)
        with get_write_lock():
            con_rw.execute(f"DELETE FROM return_requests WHERE request_id IN ({','.join('?' * len(ids))})", ids)
        st.session_state.created_requests = []
        reset_chat()
        st.rerun()

# --- MÜŞTERİ DESTEK EKRANI -----------------------------------------------------
if st.session_state.current_session.role == "customer":
    st.header("💬 Örnekpazar Müşteri Destek Asistanı")
    st.caption("Siparişlerinizin durumunu öğrenebilir, iade talebi açabilir ya da pazaryeri politikalarını sorabilirsiniz.")

    quick = {"📦 Son siparişlerimi listele": "Son siparişlerimi listeler misiniz?",
             "❓ İade politikası nedir?": "Ürünleri kaç gün içinde iade edebilirim?",
             "🚚 Kargo gecikmesi iadesi": "Siparişim çok geç geldi, kargo paramı geri alabilir miyim?"}
    for col, (label, text) in zip(st.columns(3), quick.items()):
        if col.button(label, use_container_width=True):
            st.session_state.queued_input = text
            st.rerun()

    st.markdown("---")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.session_state.messages:
        render_steps(st.session_state.last_steps)

    # HITL ONAY KARTI
    if st.session_state.pending_proposal:
        prop = st.session_state.pending_proposal
        st.warning("⚠️ **İNSAN ONAYI GEREKİYOR (Human-in-the-Loop)**")
        with st.container(border=True):
            st.markdown("### 📋 İade Talebi Özeti")
            c1, c2 = st.columns(2)
            c1.markdown(f"**Sipariş No:** `{prop['order_id'][:8]}…`")
            c1.markdown(f"**İade Nedeni:** `{prop['reason']}`")
            c2.markdown(f"**İade Tutarı:** `{prop['refund_amount']} BRL`" + (" *(Yalnız Kargo Bedeli)*" if prop.get("freight_only") else ""))
            c2.markdown(f"**Onay Seviyesi:** `{prop['approval_level']}`")

            st.write("Bu talebin oluşturulmasını onaylıyor musunuz?")
            btn_col1, btn_col2 = st.columns([1, 4])

            if btn_col1.button("✅ Talebi Onayla", type="primary", use_container_width=True):
                sess = st.session_state.current_session
                sess.gate.approve(prop["proposal_id"])   # onay YALNIZ bu insan düğmesinden geçer
                with get_write_lock():
                    res = st_tools.create_return_request(con_rw, sess, prop["order_id"], prop["reason"],
                                                         prop["refund_amount"], prop["proposal_id"])
                if "return_request_id" in res:
                    st.session_state.created_requests.append(res["return_request_id"])
                    text = (f"✅ İade talebiniz oluşturuldu. Talep No: **#{res['return_request_id']}**, "
                            f"Durum: **{res['status']}**, İade Tutarı: **{res['refund_amount']} BRL**.")
                    st.session_state.system_note = f"[SİSTEM: Müşteri onayladı; iade talebi #{res['return_request_id']} açıldı.]"
                else:
                    text = f"❌ Talep açılamadı: {res.get('message', 'bilinmeyen neden')}"
                    st.session_state.system_note = "[SİSTEM: Talep açılamadı.]"
                st.session_state.messages.append({"role": "assistant", "content": text})
                st.session_state.pending_proposal = None
                st.rerun()

            if btn_col2.button("❌ Reddet / İptal Et", use_container_width=True):
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "İade talebini onaylamadınız; talep açılmadı. Başka bir konuda yardımcı olabilir miyim?"})
                st.session_state.system_note = "[SİSTEM: Müşteri iade talebini onaylamadı; talep açılmadı.]"
                st.session_state.pending_proposal = None
                st.rerun()

    user_input = st.chat_input("Mesajınızı yazın...") or st.session_state.pop("queued_input", None)
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Asistan yanıt hazırlıyor..."):
                try:
                    ctx, agent = get_support_agent()
                    ctx.calls.clear()      # tekrar koruması tur başına sayılır
                    ctx.trace.clear()
                    ctx.pending = None
                    note, st.session_state.system_note = st.session_state.system_note, None
                    answer = str(agent.run((note + "\n" if note else "") + user_input, reset=False))
                    if ctx.pending:
                        st.session_state.pending_proposal = ctx.pending
                    st.session_state.last_steps = summarize_trace(ctx.trace)
                except Exception as e:  # noqa: BLE001
                    answer = friendly_error(e)
                    st.session_state.last_steps = []
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
        st.rerun()

# --- OPERASYON ANALİTİĞİ EKRANI ------------------------------------------------
else:
    st.header("📊 Operasyon Veri Analitiği (Ops Data Agent)")
    st.caption("Tanımlı semantic layer metriklerini inceleyebilir, boyut bazlı analiz yapabilir ya da serbest sorgulama yapabilirsiniz.")

    tab1, tab2 = st.tabs(["📈 Hızlı Metrik Paneli (Semantic Layer)", "💬 Doğal Dil & SQL Analiz Sohbeti"])

    with tab1:
        st.subheader("Tanımlı Metrik Hesaplama")
        m_defs = ops_tools.load_metrics_def()

        c1, c2, c3 = st.columns([2, 2, 1])
        selected_metric = c1.selectbox(
            "Metrik Seçin:", list(m_defs.keys()),
            format_func=lambda k: f"{m_defs[k].get('title', k)} ({k})")

        m_info = m_defs[selected_metric]
        st.caption(f"ℹ️ **Açıklama:** {m_info.get('description', '')}")

        avail_dims = list(m_info.get("dimensions", {}).keys())
        selected_dims = c2.multiselect("Gruplama Boyutları (Opsiyonel):", avail_dims)
        limit_val = c3.number_input("Satır Sınırı:", min_value=5, max_value=500, value=20)

        if st.button("🚀 Metriği Hesapla", type="primary"):
            with st.spinner("Sorgu yürütülüyor..."):
                res = ops_tools.run_metric(con_ro, st.session_state.current_session, selected_metric,
                                           dimensions=selected_dims, limit=limit_val)
                if "error" in res:
                    st.error(f"Hata: {res['message']}")
                else:
                    data = res.get("data", [])
                    st.success(f"Hesaplama tamamlandı: {len(data)} satır bulundu.")
                    st.warning(f"⚠️ **Caveat / Gözlemsel Sınır:** {res.get('caveat', '')}")

                    if data:
                        df = pd.DataFrame(data)
                        col_left, col_right = st.columns([3, 2])
                        with col_left:
                            st.markdown("#### 📋 Veri Tablosu")
                            st.dataframe(df, use_container_width=True)
                        with col_right:
                            st.markdown("#### 📊 Grafik")
                            if selected_dims and len(df) > 0:
                                try:
                                    st.bar_chart(df.set_index(selected_dims[0])[selected_metric])
                                except Exception:  # noqa: BLE001
                                    st.line_chart(df[selected_metric])
                            else:
                                st.metric(label=m_info.get("title", selected_metric), value=df.iloc[0][selected_metric])
                        with st.expander("🔍 Üretilen SQL Sorgusu"):
                            st.code(res.get("sql", ""), language="sql")

    with tab2:
        st.subheader("Operasyon Analisti ile Sohbet")
        st.caption("Örnek: 'São Paulo eyaletinde geç teslim oranı nedir?' ya da 'En çok sipariş alan 5 kategori hangisi?'")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        if st.session_state.messages:
            render_steps(st.session_state.last_steps)

        ops_input = st.chat_input("Operasyon sorunuzu yazın...")
        if ops_input:
            st.session_state.messages.append({"role": "user", "content": ops_input})
            with st.chat_message("user"):
                st.markdown(ops_input)
            with st.chat_message("assistant"):
                with st.spinner("Ops Data Agent analiz ediyor..."):
                    try:
                        agent, logger = get_ops_agent()
                        start = len(logger.records)
                        ans = str(agent.run(ops_input, reset=False))
                        st.session_state.last_steps = [
                            {"tool": t["name"], "args": json.dumps(t["args"], ensure_ascii=False, default=str)[:220], "result": "—"}
                            for r in logger.records[start:] for t in r.get("tools", []) if t["name"] != "final_answer"]
                    except Exception as e:  # noqa: BLE001
                        ans = friendly_error(e)
                        st.session_state.last_steps = []
                    st.markdown(ans)
                    st.session_state.messages.append({"role": "assistant", "content": ans})
            st.rerun()

st.markdown("---")
st.caption("Veri: Olist Brazilian E-Commerce Public Dataset (Kaggle), CC BY-NC-SA 4.0. Senaryo kurgusaldır; "
           "tarihler 2018'dendir ve sistemde 'bugün' sabittir.")
