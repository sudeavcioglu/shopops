"""ShopOps Router & Çoklu Ajan Orkestratörü (Multi-Agent Orchestrator).

Genel Rehber §3 #3 ve ShopOps §5.1 / §5.2 gereksinimleri:
- Router, oturum tipini KULLANICI MESAJINDAN DEĞİL, kimlik doğrulama oturum nesnesinden (Session.role) alır.
- 'Ben operasyon yöneticisiyim' diyen bir müşteri asla Ops Agent'ına gidemez (G2 yetki prensibi).
- Müşteri oturumu (role='customer')  -> Support Agent (smolagents ToolCallingAgent)
- Operasyon oturumu (role='ops')      -> Ops Data Agent (smolagents ToolCallingAgent)
"""
from __future__ import annotations

import sqlite3
from typing import Callable

import config
from src.agents.ops_agent import OpsCtx, build_ops_agent
from src.agents.support_agent import Ctx, StepLogger, build_agent
from src.tools.session import Session


class ShopOpsOrchestrator:
    def __init__(self, db_path: str = str(config.DB_PATH),
                 confirm_callback: Callable[[dict], bool] | None = None,
                 logger: StepLogger | None = None,
                 model=None):
        self.db_path = db_path
        self.confirm_callback = confirm_callback
        self.logger = logger
        self.model = model
        
        # Bağlantılar
        self.con_ro = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.con_rw = sqlite3.connect(self.db_path, isolation_level=None)

    def route_and_run(self, session: Session, message: str, reset: bool = True) -> str:
        """Kullanıcı mesajını oturumun yetkili rolüne göre doğru uzmana yönlendirir."""
        if not isinstance(message, str) or not message.strip():
            return "Lütfen geçerli bir mesaj girin."

        role = getattr(session, "role", "customer")

        if role == "customer":
            # Müşteri destek ajanı
            ctx = Ctx(self.con_ro, self.con_rw, session, confirm=self.confirm_callback)
            agent = build_agent(ctx, model=self.model, logger=self.logger, verbosity=0)
            return agent.run(message.strip(), reset=reset)

        elif role == "ops":
            # Operasyon veri analiz ajanı
            ctx = OpsCtx(self.con_ro, session)
            agent = build_ops_agent(ctx, model=self.model, logger=self.logger, verbosity=0)
            return agent.run(message.strip(), reset=reset)

        else:
            return f"Bilinmeyen oturum rolü: {role}. Erişim reddedildi."

    def close(self):
        try:
            self.con_ro.close()
            self.con_rw.close()
        except Exception:
            pass

