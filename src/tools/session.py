"""Oturum ve HITL kapısı (G1, G2). Kimlik ve onay durumu SUNUCU tarafında durur, LLM'den gelmez.

Neden LLM onayı taklit edemez?
  * Onay bir 'token string'i değil, ApprovalGate içindeki bir DURUM'dur; yalnızca insan
    arayüzünün çağırdığı gate.approve() bu durumu değiştirir. Agent'ın tool listesinde approve yoktur.
  * proposal_id tahmin edilemez (secrets) ve LLM onu ancak APPROVAL_REQUIRED yanıtında görür;
    onaylanmamış bir id'yi tekrar göndermek hiçbir şey değiştirmez.
  * Onay; oturum + order_id + reason + tutara bağlıdır ve tek kullanımlıktır.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field


@dataclass
class _Proposal:
    uid: str
    order_id: str
    reason: str
    amount: float
    approved: bool = False
    used: bool = False


class ApprovalGate:
    def __init__(self) -> None:
        self._p: dict[str, _Proposal] = {}

    def propose(self, uid: str, order_id: str, reason: str, amount: float) -> str:
        for pid, p in self._p.items():  # aynı parametreli bekleyen öneri varsa onu kullan
            if (p.uid, p.order_id, p.reason, p.amount) == (uid, order_id, reason, amount) and not p.used:
                return pid
        pid = "prop_" + secrets.token_urlsafe(12)
        self._p[pid] = _Proposal(uid, order_id, reason, amount)
        return pid

    def approve(self, proposal_id: str) -> bool:
        """YALNIZ insan arayüzü (CLI/Streamlit butonu) çağırır; agent tool'u değildir."""
        p = self._p.get(proposal_id)
        if p is None or p.used:
            return False
        p.approved = True
        return True

    def consume(self, proposal_id: str | None, uid: str, order_id: str, reason: str, amount: float) -> bool:
        p = self._p.get(proposal_id or "")
        if not p or not p.approved or p.used:
            return False
        if (p.uid, p.order_id, p.reason, p.amount) != (uid, order_id, reason, amount):
            return False
        p.used = True
        return True


@dataclass
class Session:
    customer_unique_id: str
    role: str = "customer"  # "customer" | "ops"  (oturum bilgisinden gelir, mesajdan değil)
    gate: ApprovalGate = field(default_factory=ApprovalGate)
