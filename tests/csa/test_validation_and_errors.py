"""
Tests for Pydantic input validation and error handling
added to all 3 CSA tools in Phase 1 Week 2 Day 5.
"""

import os
import pytest
import xmlrpc.client
import socket
from unittest.mock import MagicMock
from dotenv import load_dotenv

load_dotenv('../.env')


# ── FakeConnection + FakeHandler ───────────────────────────────────────────────

class FakeConnection:
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
        self.get_vendor_lead_times = lambda *a, **kw: CSAToolHandler.get_vendor_lead_times(self, *a, **kw)
        self._get_vendor_info_for_product = lambda *a, **kw: CSAToolHandler._get_vendor_info_for_product(self, *a, **kw)
    def _handle_get_bom_with_stock_sync(self, product_name):
        from mcp_server_odoo.csa_tools import BomInput
        try:
            params = BomInput(product_name=product_name, qty=1.0)
            product_name = params.product_name
        except ValueError as e:
            return {"error": str(e)}
        return {"ok": True}


@pytest.fixture
def fake_handler():
    return FakeHandler()


# ── Pydantic validation tests ──────────────────────────────────────────────────

class TestBomInputValidation:

    def test_empty_product_name_returns_error(self, fake_handler):
        result = fake_handler._handle_get_bom_with_stock_sync("")
        assert "error" in result

    def test_whitespace_only_product_name_returns_error(self, fake_handler):
        result = fake_handler._handle_get_bom_with_stock_sync("   ")
        assert "error" in result

    def test_valid_product_name_does_not_return_error(self, fake_handler):
        result = fake_handler._handle_get_bom_with_stock_sync("B-1300")
        assert "error" not in result


class TestShortageInputValidation:

    def test_empty_product_name_returns_error(self, fake_handler):
        result = fake_handler.get_shortage_report("")
        assert "error" in result

    def test_whitespace_only_returns_error(self, fake_handler):
        result = fake_handler.get_shortage_report("   ")
        assert "error" in result

    def test_negative_qty_returns_error(self, fake_handler):
        result = fake_handler.get_shortage_report("B-1300", qty=-1)
        assert "error" in result

    def test_zero_qty_returns_error(self, fake_handler):
        result = fake_handler.get_shortage_report("B-1300", qty=0)
        assert "error" in result

    def test_valid_input_does_not_return_error(self, fake_handler):
        result = fake_handler.get_shortage_report("B-1300", qty=1.0)
        assert "error" not in result


class TestVendorInputValidation:

    def test_empty_product_name_returns_error(self, fake_handler):
        result = fake_handler.get_vendor_lead_times("")
        assert "error" in result

    def test_whitespace_only_returns_error(self, fake_handler):
        result = fake_handler.get_vendor_lead_times("   ")
        assert "error" in result

    def test_negative_qty_returns_error(self, fake_handler):
        result = fake_handler.get_vendor_lead_times("B-1300", qty=-1)
        assert "error" in result

    def test_zero_qty_returns_error(self, fake_handler):
        result = fake_handler.get_vendor_lead_times("B-1300", qty=0)
        assert "error" in result

    def test_valid_input_does_not_return_error(self, fake_handler):
        result = fake_handler.get_vendor_lead_times("B-1300", qty=1.0)
        assert "error" not in result


# ── Error handling tests ───────────────────────────────────────────────────────

class TestErrorHandling:

    def test_shortage_report_handles_odoo_fault(self, fake_handler):
        fake_handler.connection.execute_kw = MagicMock(
            side_effect=xmlrpc.client.Fault(1, "Access Denied")
        )
        result = fake_handler.get_shortage_report("B-1300")
        assert "error" in result
        assert "Odoo" in result["error"]

    def test_shortage_report_handles_timeout(self, fake_handler):
        fake_handler.connection.execute_kw = MagicMock(
            side_effect=socket.timeout()
        )
        result = fake_handler.get_shortage_report("B-1300")
        assert "error" in result
        assert "too long" in result["error"]

    def test_shortage_report_handles_unexpected_error(self, fake_handler):
        fake_handler.connection.execute_kw = MagicMock(
            side_effect=RuntimeError("something broke")
        )
        result = fake_handler.get_shortage_report("B-1300")
        assert "error" in result

    def test_vendor_lead_times_handles_odoo_fault(self, fake_handler):
        fake_handler.connection.execute_kw = MagicMock(
            side_effect=xmlrpc.client.Fault(1, "Access Denied")
        )
        result = fake_handler.get_vendor_lead_times("B-1300")
        assert "error" in result
        assert "Odoo" in result["error"]

    def test_vendor_lead_times_handles_timeout(self, fake_handler):
        fake_handler.connection.execute_kw = MagicMock(
            side_effect=socket.timeout()
        )
        result = fake_handler.get_vendor_lead_times("B-1300")
        assert "error" in result
        assert "too long" in result["error"]