"""Agent kablolamasını SAHTE (scripted) modelle test eder: LLM gerekmez, deterministik."""
import json

from smolagents import Model
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction

from src.agents.support_agent import Ctx, StepLogger, build_agent, build_tools
from src.tools.session import Session
from tests.test_support_tools import A, O1, OBIG, con  # noqa: F401  (fixture + sabitler)


class Scripted(Model):
    """Sıradaki tool çağrılarını sırayla üretir; script bitince metin cevap verir."""
    def __init__(self, calls):
        super().__init__(model_id="scripted")
        self.calls, self.i = list(calls), 0

    def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kw):
        if self.i < len(self.calls):
            name, args = self.calls[self.i]
            self.i += 1
            tc = ChatMessageToolCall(function=ChatMessageToolCallFunction(name=name, arguments=args), id=f"c{self.i}", type="function")
            return ChatMessage(role="assistant", content="", tool_calls=[tc])
        return ChatMessage(role="assistant", content="(script bitti)")


def run(con, calls, confirm=None, logger=None, session=None):
    ctx = Ctx(con, con, session or Session(A), confirm)
    agent = build_agent(ctx, Scripted(calls), logger)
    return agent.run("test"), ctx


def n_returns(c):
    return c.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]


def test_agent_has_at_least_4_custom_tools(con):
    names = {t.name for t in build_tools(Ctx(con, con, Session(A)))}
    assert len(names) == 6 and {"get_order_status", "create_return_request", "search_policies"} <= names


def test_order_status_flow(con):
    out, _ = run(con, [("list_customer_orders", {}), ("get_order_status", {"order_id": O1}),
                       ("final_answer", {"answer": "Siparişiniz teslim edildi."})])
    assert "teslim" in str(out)


def test_return_flow_with_human_confirm(con):
    seen = []
    out, _ = run(con, [("check_return_eligibility", {"order_id": O1, "reason": "changed_mind"}),
                       ("create_return_request", {"order_id": O1, "reason": "changed_mind", "amount": 100.0}),
                       ("final_answer", {"answer": "Talep açıldı."})],
                 confirm=lambda p: seen.append(p) or True)
    assert n_returns(con) == 1 and seen[0]["refund_amount"] == 100.0


def test_human_declines_no_row(con):
    run(con, [("create_return_request", {"order_id": O1, "reason": "changed_mind", "amount": 100.0}),
              ("final_answer", {"answer": "Tamam."})], confirm=lambda p: False)
    assert n_returns(con) == 0


def test_no_confirm_channel_no_write_and_no_proposal_id_leak(con):
    ctx = Ctx(con, con, Session(A), confirm=None)
    r = [t for t in build_tools(ctx) if t.name == "create_return_request"][0]
    out = r(order_id=O1, reason="changed_mind", amount=100.0)
    assert out["error"] == "APPROVAL_REQUIRED" and "proposal_id" not in out and n_returns(con) == 0


def test_repeated_call_guard(con):
    ctx = Ctx(con, con, Session(A))
    t = [x for x in build_tools(ctx) if x.name == "get_order_status"][0]
    res = [t(order_id=O1) for _ in range(3)]
    assert "status" in res[0] and res[1].get("status") and res[2]["error"] == "REPEATED_CALL"


def test_max_steps_is_enforced(con):
    calls = [("list_customer_orders", {"limit": i + 1}) for i in range(20)]  # hiç final_answer yok
    logger = StepLogger()
    run(con, calls, logger=logger)
    assert len([r for r in logger.records if r["tools"]]) <= 8


def test_step_log_has_no_raw_ids(con, tmp_path):
    logger = StepLogger(tmp_path / "trace.jsonl")
    run(con, [("get_order_status", {"order_id": O1}), ("final_answer", {"answer": "ok"})], logger=logger)
    text = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert O1 not in text and "id:" in text
