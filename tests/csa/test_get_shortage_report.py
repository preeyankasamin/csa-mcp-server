"""
Tests for get_shortage_report tool.
Uses FakeHandler pattern (same as test_explode_bom_multilevel.py)
to call the method directly without going through FastMCP.
"""

import os
import sys
import xmlrpc.client
import pytest
from dotenv import load_dotenv

load_dotenv('../.env')

# ── FakeHandler ────────────────────────────────────────────────────────────────
# Same pattern as Day 1 tests.
# CSAToolHandler needs self.connection.execute_kw to work.
# We create a minimal fake object that has only execute_kw.

class FakeConnection:
    """
    Mimics OdooConnection but uses raw xmlrpc.client directly.
    This lets us call CSAToolHandler methods without needing
    connect() or authenticate() from OdooConnection.
    """
    def __init__(self):
        url = os.getenv("ODOO_URL")
        db = os.getenv("ODOO_DB")
        api_key = os.getenv("ODOO_API_KEY")
        uid = 33831

        self._db = db
        self._uid = uid
        self._api_key = api_key
        self._models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def execute_kw(self, model, method, args, kwargs=None):
        if kwargs is None:
            kwargs = {}
        return self._models.execute_kw(
            self._db, self._uid, self._api_key,
            model, method, args, kwargs
        )


class FakeHandler:
    """
    Minimal stand-in for CSAToolHandler.
    Has self.connection (FakeConnection) and the three methods we need.
    """
    def __init__(self):
        from mcp_server_odoo.csa_tools import CSAToolHandler
        self.connection = FakeConnection()
        self._cache = {}
        self._cache_get = lambda key: CSAToolHandler._cache_get(self, key)
        self._cache_set = lambda key, val: CSAToolHandler._cache_set(self, key, val)
        self._get_bom_for_product_id = lambda pid: CSAToolHandler._get_bom_for_product_id(self, pid)
        self._explode = lambda *a, **kw: CSAToolHandler._explode(self, *a, **kw)
        self.explode_bom_multilevel = lambda *a, **kw: CSAToolHandler.explode_bom_multilevel(self, *a, **kw)
        self._check_stock_for_product = lambda pid: CSAToolHandler._check_stock_for_product(self, pid)
        self.get_shortage_report = lambda *a, **kw: CSAToolHandler.get_shortage_report(self, *a, **kw)


@pytest.fixture(scope="module")
def handler():
    """Single FakeHandler instance shared across all tests in this file."""
    return FakeHandler()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_shortage_report_found(handler):
    """B-1300 exists and has a BOM — found must be True."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert result["found"] is True


def test_shortage_report_has_finished_product(handler):
    """Result must include the finished product name."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert "finished_product" in result
    assert len(result["finished_product"]) > 0


def test_shortage_report_qty_requested(handler):
    """qty_requested must match what we passed in."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert result["qty_requested"] == 1.0


def test_shortage_report_total_raw_materials(handler):
    """B-1300 explodes to many raw materials — must be a realistic number."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert result["total_raw_materials"] >= 100

def test_shortage_report_shortage_count_is_int(handler):
    """shortage_count must be an integer >= 0."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert isinstance(result["shortage_count"], int)
    assert result["shortage_count"] >= 0


def test_shortage_report_has_shortages_flag(handler):
    """has_shortages must be True if shortage_count > 0, False otherwise."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert result["has_shortages"] == (result["shortage_count"] > 0)


def test_shortage_report_shortages_is_list(handler):
    """shortages key must be a list."""
    result = handler.get_shortage_report("B-1300", qty=1)
    assert isinstance(result["shortages"], list)


def test_shortage_report_shortage_item_keys(handler):
    """Every shortage item must have the required keys."""
    result = handler.get_shortage_report("B-1300", qty=1)
    for item in result["shortages"]:
        assert "product_id" in item
        assert "product_name" in item
        assert "qty_needed" in item
        assert "qty_available" in item
        assert "shortage_qty" in item
        assert "uom" in item


def test_shortage_report_shortage_qty_positive(handler):
    """shortage_qty must always be > 0 for every item in the list."""
    result = handler.get_shortage_report("B-1300", qty=1)
    for item in result["shortages"]:
        assert item["shortage_qty"] > 0


def test_shortage_report_not_found(handler):
    """A product that does not exist must return found=False."""
    result = handler.get_shortage_report("PRODUCT_THAT_DOES_NOT_EXIST_XYZ", qty=1)
    assert result["found"] is False


def test_shortage_report_not_found_has_message(handler):
    """found=False result must include a message."""
    result = handler.get_shortage_report("PRODUCT_THAT_DOES_NOT_EXIST_XYZ", qty=1)
    assert "message" in result


def test_shortage_report_qty_2_more_shortages(handler):
    """Building qty=2 should produce >= shortages compared to qty=1."""
    result_1 = handler.get_shortage_report("B-1300", qty=1)
    result_2 = handler.get_shortage_report("B-1300", qty=2)
    assert result_2["shortage_count"] >= result_1["shortage_count"]