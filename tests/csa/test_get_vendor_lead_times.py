"""
Tests for get_vendor_lead_times tool.
Uses FakeHandler pattern (same as test_get_shortage_report.py).
"""

import os
import xmlrpc.client
import pytest
from dotenv import load_dotenv

load_dotenv('../.env')


# ── FakeConnection ────────────────────────────────────────────────────────────

class FakeConnection:
    """
    Mimics OdooConnection using raw xmlrpc.client directly.
    Lets us call CSAToolHandler methods without connect() or authenticate().
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
    Wires all methods we need from CSAToolHandler using self as the instance.
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
        self._get_vendor_info_for_product = lambda *a, **kw: CSAToolHandler._get_vendor_info_for_product(self, *a, **kw)
        self.get_vendor_lead_times = lambda *a, **kw: CSAToolHandler.get_vendor_lead_times(self, *a, **kw)


@pytest.fixture(scope="module")
def handler():
    """Single FakeHandler instance shared across all tests in this file."""
    return FakeHandler()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_vendor_lead_times_found(handler):
    """B-1300 has a BOM -- found must be True."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    assert result["found"] is True


def test_vendor_lead_times_has_finished_product(handler):
    """Result must include finished_product name."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    assert "finished_product" in result
    assert len(result["finished_product"]) > 0


def test_vendor_lead_times_total_components(handler):
    """B-1300 has many raw materials -- must be realistic number."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    assert result["total_components"] >= 100


def test_vendor_lead_times_components_is_list(handler):
    """components must be a list."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    assert isinstance(result["components"], list)


def test_vendor_lead_times_component_required_keys(handler):
    """Every component must have required keys."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    for item in result["components"]:
        assert "product_id" in item
        assert "product_name" in item
        assert "qty_needed" in item
        assert "uom" in item
        assert "has_vendor" in item
        assert "recommended_vendor" in item
        assert "vendors" in item


def test_vendor_lead_times_vendors_is_list(handler):
    """vendors field on every component must be a list."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    for item in result["components"]:
        assert isinstance(item["vendors"], list)


def test_vendor_lead_times_vendor_keys(handler):
    """Every vendor entry must have required keys."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    for item in result["components"]:
        for v in item["vendors"]:
            assert "vendor_name" in v
            assert "price" in v
            assert "min_qty" in v
            assert "lead_time_days" in v
            assert "currency" in v


def test_vendor_lead_times_no_vendor_count(handler):
    """no_vendor_count must be an integer >= 0."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    assert isinstance(result["no_vendor_count"], int)
    assert result["no_vendor_count"] >= 0


def test_vendor_lead_times_has_vendor_flag_matches(handler):
    """has_vendor must be True if vendors list is non-empty, False if empty."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    for item in result["components"]:
        assert item["has_vendor"] == (len(item["vendors"]) > 0)


def test_vendor_lead_times_recommended_vendor_is_string_or_none(handler):
    """recommended_vendor must be a string when has_vendor is True, None otherwise."""
    result = handler.get_vendor_lead_times("B-1300", qty=1)
    for item in result["components"]:
        if item["has_vendor"]:
            assert isinstance(item["recommended_vendor"], str)
        else:
            assert item["recommended_vendor"] is None


def test_vendor_lead_times_not_found(handler):
    """A product that does not exist must return found=False."""
    result = handler.get_vendor_lead_times("PRODUCT_DOES_NOT_EXIST_XYZ", qty=1)
    assert result["found"] is False


def test_vendor_lead_times_not_found_has_message(handler):
    """found=False result must include a message."""
    result = handler.get_vendor_lead_times("PRODUCT_DOES_NOT_EXIST_XYZ", qty=1)
    assert "message" in result