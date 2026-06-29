import pytest
from unittest.mock import MagicMock
from mcp_server_odoo.csa_tools import CSAToolHandler


class FakeConnection:
    def __init__(self):
        self._db = "csaerotherm"
        self._uid = 33831
        self._api_key = "fake_key"
        self._models = MagicMock()

    def execute_kw(self, model, method, args, kwargs=None):
        if model == "product.product":
            return [
                {"id": 101, "name": "Steel Rod", "default_code": "SR-001"}
            ]
        if model == "product.supplierinfo":
            return [
                {
                    "partner_id": [1, "Vendor A"],
                    "price": 450.0,
                    "delay": 3,
                    "min_qty": 10.0,
                    "currency_id": [1, "INR"],
                },
                {
                    "partner_id": [2, "Vendor B"],
                    "price": 400.0,
                    "delay": 7,
                    "min_qty": 5.0,
                    "currency_id": [1, "INR"],
                },
                {
                    "partner_id": [3, "Vendor C"],
                    "price": 400.0,
                    "delay": 4,
                    "min_qty": 20.0,
                    "currency_id": [1, "INR"],
                },
            ]
        return []


class FakeConnectionNoVendors(FakeConnection):
    def execute_kw(self, model, method, args, kwargs=None):
        if model == "product.product":
            return [
                {"id": 101, "name": "Steel Rod", "default_code": "SR-001"}
            ]
        if model == "product.supplierinfo":
            return []
        return []


class FakeConnectionNoProduct(FakeConnection):
    def execute_kw(self, model, method, args, kwargs=None):
        return []


class FakeHandler(CSAToolHandler):
    def __init__(self, connection=None):
        self.connection = connection or FakeConnection()
        import socket
        socket.setdefaulttimeout(30)


@pytest.fixture
def handler():
    return FakeHandler()


@pytest.fixture
def handler_no_vendors():
    return FakeHandler(connection=FakeConnectionNoVendors())


@pytest.fixture
def handler_no_product():
    return FakeHandler(connection=FakeConnectionNoProduct())


def test_vendor_comparison_returns_dict(handler):
    result = handler.vendor_comparison("Steel Rod")
    assert isinstance(result, dict)


def test_vendor_comparison_has_required_keys(handler):
    result = handler.vendor_comparison("Steel Rod")
    assert "product_name" in result
    assert "internal_ref" in result
    assert "vendor_count" in result
    assert "vendors" in result


def test_vendor_comparison_correct_vendor_count(handler):
    result = handler.vendor_comparison("Steel Rod")
    assert result["vendor_count"] == 3


def test_vendor_comparison_vendor_has_required_keys(handler):
    result = handler.vendor_comparison("Steel Rod")
    vendor = result["vendors"][0]
    assert "vendor_name" in vendor
    assert "unit_price" in vendor
    assert "currency" in vendor
    assert "lead_time_days" in vendor
    assert "min_qty" in vendor


def test_vendor_comparison_sorted_by_price(handler):
    result = handler.vendor_comparison("Steel Rod")
    prices = [v["unit_price"] for v in result["vendors"]]
    assert prices == sorted(prices)


def test_vendor_comparison_same_price_sorted_by_lead_time(handler):
    result = handler.vendor_comparison("Steel Rod")
    same_price = [v for v in result["vendors"] if v["unit_price"] == 400.0]
    lead_times = [v["lead_time_days"] for v in same_price]
    assert lead_times == sorted(lead_times)


def test_vendor_comparison_correct_product_name(handler):
    result = handler.vendor_comparison("Steel Rod")
    assert result["product_name"] == "Steel Rod"


def test_vendor_comparison_correct_internal_ref(handler):
    result = handler.vendor_comparison("Steel Rod")
    assert result["internal_ref"] == "SR-001"


def test_vendor_comparison_no_vendors_returns_message(handler_no_vendors):
    result = handler_no_vendors.vendor_comparison("Steel Rod")
    assert result["vendor_count"] == 0
    assert "message" in result


def test_vendor_comparison_no_product_returns_error(handler_no_product):
    result = handler_no_product.vendor_comparison("NonExistent")
    assert "error" in result


def test_vendor_comparison_empty_name_returns_error(handler):
    result = handler.vendor_comparison("")
    assert "error" in result


def test_vendor_comparison_currency_present(handler):
    result = handler.vendor_comparison("Steel Rod")
    for vendor in result["vendors"]:
        assert vendor["currency"] == "INR"