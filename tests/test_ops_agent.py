"""Ops Agent kablolama testleri (sahte/scripted model ile)."""
import sqlite3
import pytest

from smolagents import Model
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction

import config
from src.agents.ops_agent import OpsCtx, build_ops_agent, build_ops_tools
from src.agents.support_agent import StepLogger
from src.tools.session import Session


class ScriptedOpsModel(Model):
    def __init__(self, calls):
        super().__init__(model_id="scripted_ops")
        self.calls, self.i = list(calls), 0

    def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kw):
        if self.i < len(self.calls):
            name, args = self.calls[self.i]
            self.i += 1
            tc = ChatMessageToolCall(function=ChatMessageToolCallFunction(name=name, arguments=args), id=f"c{self.i}", type="function")
            return ChatMessage(role="assistant", content="", tool_calls=[tc])
        return ChatMessage(role="assistant", content="Rapor hazır.")


@pytest.fixture
def ops_ctx():
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    yield OpsCtx(con, Session("selin_ops", role="ops"))
    con.close()


def test_ops_agent_tools_count(ops_ctx):
    tools = build_ops_tools(ops_ctx)
    names = {t.name for t in tools}
    assert names == {"list_metrics", "run_metric", "run_sql"}


def test_ops_agent_metric_flow(ops_ctx):
    calls = [
        ("list_metrics", {}),
        ("run_metric", {"metric_name": "late_delivery_rate", "dimensions": ["customer_state"]}),
        ("final_answer", {"answer": "En yüksek geç teslim oranı hesaplandı."})
    ]
    logger = StepLogger()
    agent = build_ops_agent(ops_ctx, model=ScriptedOpsModel(calls), logger=logger)
    out = agent.run("SP eyaletinde geç teslim oranı nedir?")
    assert "hesaplandı" in str(out)
    tool_names = [t["name"] for r in logger.records for t in r.get("tools", [])]
    assert "run_metric" in tool_names


def test_ops_agent_sql_flow(ops_ctx):
    calls = [
        ("run_sql", {"sql": "SELECT COUNT(*) FROM orders"}),
        ("final_answer", {"answer": "Toplam sipariş sayısı bulundu."})
    ]
    logger = StepLogger()
    agent = build_ops_agent(ops_ctx, model=ScriptedOpsModel(calls), logger=logger)
    out = agent.run("Kaç sipariş var?")
    assert "bulundu" in str(out)

