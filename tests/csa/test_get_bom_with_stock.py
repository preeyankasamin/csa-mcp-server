"""
Tests for get_bom_with_stock CSA custom tool.
Tests the core logic directly without going through MCP protocol.
"""

import os
import pytest
import xmlrpc.client
from dotenv import load_dotenv

load_dotenv()


class MockConnection:
    """
    Simulates OdooConnection for testing.
    Wraps raw XML-RPC so we can call _handle_get_bom_with_stock
    without starting the full MCP server.
    """

    def __init__(self):
        url = os.getenv("ODOO_URL")
        db = os.getenv("ODOO_DB")
        self.db = db
        self.uid = 33831
        self.api_key = os.getenv("ODOO_API_KEY")
        self._models = xmlrpc.client.ServerProxy(
            f"{url}/xmlrpc/2/object"
        )

    def execute_kw(self, model, method, args, kwargs=None):
        """
        Mirrors the signature of OdooConnection.execute_kw.
        model   — Odoo model name e.g. 'mrp.bom'
        method  — method name e.g. 'search_read'
        args    — positional args list e.g. [[['name','=','x']]]
        kwargs  — keyword args dict e.g. {'fields': [...], 'limit': 5}
        """
        if kwargs is None:
            kwargs = {}
        return self._models.execute_kw(
            self.db, self.uid, self.api_key,
            model, method, args, kwargs
        )


class MockApp:
    """
    Simulates FastMCP app for testing.
    We don't need real MCP registration in tests —
    we call _handle_get_bom_with_stock directly.
    """

    def tool(self, *args, **kwargs):
        """Returns a no-op decorator so @self.app.tool() doesn't crash."""
        def decorator(fn):
            return fn
        return decorator


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def csa_handler():
    """
    Creates a real CSAToolHandler with a live Odoo connection.
    Used by all tests that need to call the tool logic directly.
    """
    from mcp_server_odoo.csa_tools import CSAToolHandler
    app = MockApp()
    connection = MockConnection()
    return CSAToolHandler(app, connection)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bom_found_for_known_product(csa_handler):
    """
    CSA-CRM11 is confirmed to have a BOM in Odoo (verified in Day 1 audit).
    This test confirms the tool finds it and returns correct structure.
    """
    result = await csa_handler._handle_get_bom_with_stock("CSA-CRM11")

    assert result["found"] is True, "BOM should be found for CSA-CRM11"
    assert result["bom_id"] > 0, "BOM id should be a positive integer"
    assert "finished_product" in result, "Result must contain finished_product"
    assert "components" in result, "Result must contain components list"
    assert result["total_components"] > 0, "CSA-CRM11 BOM should have components"


@pytest.mark.asyncio
async def test_bom_not_found_for_unknown_product(csa_handler):
    """
    A made-up product name should return found=False cleanly,
    not crash or raise an exception.
    """
    result = await csa_handler._handle_get_bom_with_stock("XXXX-DOES-NOT-EXIST-9999")

    assert result["found"] is False, "Unknown product should return found=False"
    assert "message" in result, "Should return a helpful message"
    assert result["components"] == [], "Components should be empty list"


@pytest.mark.asyncio
async def test_each_component_has_required_fields(csa_handler):
    """
    Every component in the result must have all required fields.
    If any field is missing, the automation pipeline will crash downstream.
    """
    result = await csa_handler._handle_get_bom_with_stock("CSA-CRM11")

    assert result["found"] is True

    for component in result["components"]:
        assert "product_id" in component, "Missing product_id"
        assert "product_name" in component, "Missing product_name"
        assert "qty_needed" in component, "Missing qty_needed"
        assert "qty_available" in component, "Missing qty_available"
        assert "uom" in component, "Missing uom"
        assert "shortage" in component, "Missing shortage flag"
        assert "shortage_qty" in component, "Missing shortage_qty"


@pytest.mark.asyncio
async def test_shortage_flag_is_correct(csa_handler):
    """
    shortage=True must only appear when qty_available < qty_needed.
    shortage=False must only appear when qty_available >= qty_needed.
    """
    result = await csa_handler._handle_get_bom_with_stock("CSA-CRM11")

    assert result["found"] is True

    for component in result["components"]:
        if component["shortage"]:
            assert component["qty_available"] < component["qty_needed"], \
                f"shortage=True but qty_available >= qty_needed for {component['product_name']}"
        else:
            assert component["qty_available"] >= component["qty_needed"], \
                f"shortage=False but qty_available < qty_needed for {component['product_name']}"


@pytest.mark.asyncio
async def test_has_shortages_flag_matches_components(csa_handler):
    """
    The top-level has_shortages flag must match whether any component
    has shortage=True. These two must always be in sync.
    """
    result = await csa_handler._handle_get_bom_with_stock("CSA-CRM11")

    assert result["found"] is True

    any_shortage = any(c["shortage"] for c in result["components"])
    assert result["has_shortages"] == any_shortage, \
        "has_shortages flag does not match component shortage flags"


@pytest.mark.asyncio
async def test_shortage_count_is_correct(csa_handler):
    """
    shortage_count must equal the exact number of components with shortage=True.
    """
    result = await csa_handler._handle_get_bom_with_stock("CSA-CRM11")

    assert result["found"] is True

    expected_count = sum(1 for c in result["components"] if c["shortage"])
    assert result["shortage_count"] == expected_count, \
        f"shortage_count={result['shortage_count']} but actual={expected_count}"
        
        
@pytest.mark.asyncio
async def test_search_by_internal_reference(csa_handler):
    """
    User types internal reference code 'SMH-150D' not the full name.
    Tool must find BOM via default_code field, not just product name.
    This was a real bug found during Day 5 testing.
    """
    result = await csa_handler._handle_get_bom_with_stock("SMH-150D")

    assert result["found"] is True, "SMH-150D should be found by internal reference"
    assert result["total_components"] == 83, \
        f"SMH-150D should have 83 components, got {result['total_components']}"


@pytest.mark.asyncio
async def test_large_bom_has_correct_shortage_count(csa_handler):
    """
    SMH-150D has 83 components — tests tool handles large BOMs correctly.
    shortage_count must exactly match components with shortage=True.
    """
    result = await csa_handler._handle_get_bom_with_stock("SMH-150D")

    assert result["found"] is True
    actual_shortage_count = sum(1 for c in result["components"] if c["shortage"])
    assert result["shortage_count"] == actual_shortage_count, \
        f"shortage_count mismatch on large BOM"


@pytest.mark.asyncio
async def test_b1300_has_known_shortage(csa_handler):
    """
    B-1300 is confirmed to have DISPFAS-B1300 (Dispatch Fasteners) as shortage.
    This test pins that known real-world data point.
    If this fails, either Odoo data changed or tool logic broke.
    """
    result = await csa_handler._handle_get_bom_with_stock("B-1300")

    assert result["found"] is True
    shortage_products = [
        c["product_name"] for c in result["components"] if c["shortage"]
    ]
    assert any("DISPFAS" in name for name in shortage_products), \
        f"Expected DISPFAS-B1300 shortage, got shortages: {shortage_products}"


@pytest.mark.asyncio
async def test_qty_available_never_negative(csa_handler):
    """
    qty_available must never be negative in the result.
    Our tool sums only positive stock quantities — negative subcontracting
    stock must be excluded. Confirmed real issue from stock.quant audit.
    """
    result = await csa_handler._handle_get_bom_with_stock("SMH-150D")

    assert result["found"] is True
    for c in result["components"]:
        assert c["qty_available"] >= 0, \
            f"qty_available is negative for {c['product_name']}: {c['qty_available']}"