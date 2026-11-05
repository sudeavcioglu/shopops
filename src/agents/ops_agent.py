"""Ops Data Agent (smolagents ToolCallingAgent).

Operasyon ekibinin (Selin) metrik ve analiz sorularını yanıtlar.
Özellikler:
  * Semantic Layer (metrics.yaml): list_metrics + run_metric
  * Salt-okunur güvenli serbest SQL: run_sql (G3 doğrulamalı)
  * Self-correction: SQL hatası durumunda en fazla MAX_SQL_CORRECTIONS kez düzeltme
  * G9 Guardrail: Cevaplarda daima gözlemsel sınır ve caveat açıklaması (nedensellik yok, GMV kâr değildir)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from smolagents import Tool, ToolCallingAgent

import config
from src.agents.support_agent import StepLogger, make_model
from src.tools import ops_tools
from src.tools.session import Session

OPS_INSTRUCTIONS = """Sen "Örnekpazar" pazaryerinin Operasyon Veri Analisti Ajanısın (Ops Data Agent).
Operasyon yöneticilerine (Selin vb.) teslimat, satıcı, kargo ve satış performansıyla ilgili veriye dayalı yanıtlar verirsin.

KURALLAR:
1. Metrik Soruları:
   - Soru standart bir metrikle ilgiliyse (geç teslim oranı, ortalama teslim süresi, GMV, sepet ortalaması, iptal oranı, değerlendirme puanı vb.), ÖNCE list_metrics ile metrik adına ve geçerli boyutlara bak, ardından run_metric ile çalıştır.
   - run_metric şablondan üretildiği için hatasız ve standart tanımlıdır.

2. Özel veya Çok Boyutlu Sorular:
   - Tanımlı metriklerin yetmediği durumlarda run_sql aracını kullanarak geçerli SQLite SELECT sorguları yaz.
   - Sorgularda her zaman DATE(:simulated_today) parametresini kullan.
   - Eğer SQL hatası (SQL_EXECUTION_ERROR) alırsan, dönen hata mesajını analiz et ve sorguyu en fazla 2 kez düzelterek tekrar dene (self-correction).

3. Güvenlik ve Sınırlar:
   - Sistemde veri yazma, güncelleme veya silme yetkin YOKTUR. Yalnızca salt-okunur SELECT sorguları çalıştırabilirsin.
   - Başka bir müşteri kimliği sorgusu veya kişisel veri çekme taleplerini kibarca reddet.

4. Yorumlama ve Caveat (Zorunlu Kurallar - G9):
   - Raporladığın her metrikte tool'dan dönen "caveat" uyarısını müşteriye aktar.
   - GMV (Gross Merchandise Value) bir ciro hacmidir; net kâr, katkı payı ya da şirket geliri DEĞİLDİR.
   - Tüm metrikler geçmiş gözlemsel veridir; korelasyon asla nedensellik (causality) kanıtlamaz."""


@dataclass
class OpsCtx:
    con_ro: Any
    session: Session


class ListMetrics(Tool):
    name = "list_metrics"
    description = "Sistemde tanımlı tüm standart metrikleri, açıklamalarını ve filtrelenebilir boyutlarını listeler."
    inputs = {}
    output_type = "object"

    def __init__(self, ctx: OpsCtx):
        super().__init__()
        self.ctx = ctx

    def forward(self):
        return ops_tools.list_metrics(self.ctx.session)


class RunMetric(Tool):
    name = "run_metric"
    description = ("Tanımlı bir metriği (late_delivery_rate, avg_delivery_days, gmv, avg_order_value, "
                   "order_count, avg_review_score, cancellation_rate, seller_delay_rate) istenen boyutlara "
                   "göre hesaplar ve caveat bilgisiyle döndürür.")
    inputs = {
        "metric_name": {"type": "string", "description": "Hesaplanacak metrik adı."},
        "dimensions": {"type": "array", "description": "Gruplama boyutları (ör: ['customer_state'], ['purchase_month'])", "nullable": True},
        "filters": {"type": "object", "description": "Filtre sözlüğü (ör: {'customer_state': 'SP'})", "nullable": True},
        "limit": {"type": "integer", "description": "Sonuç satır sınırı (varsayılan 50)", "nullable": True}
    }
    output_type = "object"

    def __init__(self, ctx: OpsCtx):
        super().__init__()
        self.ctx = ctx

    def forward(self, metric_name: str, dimensions: list[str] | None = None,
                filters: dict | None = None, limit: int | None = None):
        return ops_tools.run_metric(
            self.ctx.con_ro, self.ctx.session, metric_name,
            dimensions=dimensions, filters=filters, limit=limit or 50
        )


class RunSQL(Tool):
    name = "run_sql"
    description = ("Veritabanı üzerinde serbest SELECT sorgusu çalıştırır. Yalnızca salt-okunur sorgulara izin verilir. "
                   "Hata durumunda SQLite hata mesajı döner.")
    inputs = {
        "sql": {"type": "string", "description": "Çalıştırılacak SQLite SELECT sorgusu."}
    }
    output_type = "object"

    def __init__(self, ctx: OpsCtx):
        super().__init__()
        self.ctx = ctx

    def forward(self, sql: str):
        return ops_tools.run_sql(self.ctx.con_ro, self.ctx.session, sql)


def build_ops_tools(ctx: OpsCtx) -> list[Tool]:
    return [ListMetrics(ctx), RunMetric(ctx), RunSQL(ctx)]


def build_ops_agent(ctx: OpsCtx, model=None, logger: StepLogger | None = None,
                    verbosity: int = 0) -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=build_ops_tools(ctx),
        model=model or make_model(),
        instructions=OPS_INSTRUCTIONS,
        max_steps=config.MAX_STEPS,
        verbosity_level=verbosity,
        step_callbacks=[logger] if logger else None
    )

