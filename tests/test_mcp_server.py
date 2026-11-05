"""ShopOps MCP Server (shopops-orders) testleri."""
import pytest
from src.mcp_server import server


def test_mcp_server_name_and_tools():
    assert server.mcp.name == "shopops-orders"
    # FastMCP üzerinde kayıtlı araçları kontrol et
    # FastMCP list_tools() veya _tool_manager.list_tools()
    tool_names = [t.name for t in server.mcp._tool_manager.list_tools()]
    expected = {"get_order_status", "list_customer_orders", "check_return_eligibility", "create_return_request"}
    assert expected.issubset(set(tool_names))


def test_mcp_tool_functions_work_directly():
    # Session müşterisi a71cac9f356cfeb9db35061020806212
    # list_customer_orders çağrısı
    res = server.list_customer_orders(limit=2)
    assert "orders" in res

    # Yabancı sipariş için NOT_FOUND
    unauth_res = server.get_order_status("e3447938231fb6ba2fee0231b51eca59")
    assert unauth_res.get("error") == "NOT_FOUND"

    # Onaysız yazma denemesi -> APPROVAL_REQUIRED
    write_res = server.create_return_request("6d25592267349b322799e2beb687871e", "changed_mind", 100.0)
    assert write_res.get("error") in ("APPROVAL_REQUIRED", "AMOUNT_MISMATCH", "NOT_FOUND")

