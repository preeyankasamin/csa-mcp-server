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
        return self._models.execute_kw(
            self._db, self._uid, self._api_key, model, method, args, kwargs or {}
        )


class FakeHandler(CSAToolHandler):
    def __init__(self):
        self.connection = FakeConnection()
        import socket
        socket.setdefaulttimeout(30)

    def explode_bom_multilevel(self, product_name, qty=1.0):
        if product_name == "":
            return {"error": "product_name cannot be empty"}
        return {
            "product_name": product_name,
            "qty": qty,
            "components": [
                {
                    "product_name": "Steel Rod",
                    "qty_needed": qty * 2.0,
                    "uom": "Nos",
                    "stock_qty": qty * 4.0,
                    "depth": 1,
                },
                {
                    "product_name": "Copper Wire",
                    "qty_needed": qty * 3.0,
                    "uom": "Mtr",
                    "stock_qty": qty * 1.0,
                    "depth": 1,
                },
            ],
        }

    def get_vendor_lead_times(self, product_name, qty=1.0):
        if product_name == "":
            return {"error": "product_name cannot be empty"}
        return {
            "product_name": product_name,
            "qty": qty,
            "materials": [
                {
                    "product_name": "Steel Rod",
                    "recommended_vendor": {
                        "vendor_name": "Vendor A",
                        "unit_price": 450.0,
                        "lead_time_days": 3,
                        "min_qty": 1.0,
                    },
                },
                {
                    "product_name": "Copper Wire",
                    "recommended_vendor": {
                        "vendor_name": "Vendor B",
                        "unit_price": 120.0,
                        "lead_time_days": 5,
                        "min_qty": 1.0,
                    },
                },
            ],
        }


@pytest.fixture
def handler():
    return FakeHandler()


def test_cost_estimate_returns_dict(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    assert isinstance(result, dict)


def test_cost_estimate_has_required_keys(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    assert "product_name" in result
    assert "requested_qty" in result
    assert "total_cost" in result
    assert "currency" in result
    assert "total_materials" in result
    assert "missing_price_count" in result
    assert "line_items" in result


def test_cost_estimate_currency_is_inr(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    assert result["currency"] == "INR"


def test_cost_estimate_correct_total_materials(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    assert result["total_materials"] == 2


def test_cost_estimate_total_cost_is_correct(handler):
    # Steel Rod: 2 Nos x 450 = 900
    # Copper Wire: 3 Mtr x 120 = 360
    # Total = 1260
    result = handler.cost_estimate("B-1300", qty=1.0)
    assert result["total_cost"] == 1260.0


def test_cost_estimate_no_missing_prices(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    assert result["missing_price_count"] == 0


def test_cost_estimate_line_item_has_required_keys(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    item = result["line_items"][0]
    assert "product_name" in item
    assert "qty_needed" in item
    assert "unit_price" in item
    assert "line_cost" in item
    assert "price_available" in item


def test_cost_estimate_steel_rod_line_cost(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    steel = next(i for i in result["line_items"] if i["product_name"] == "Steel Rod")
    assert steel["line_cost"] == 900.0


def test_cost_estimate_copper_wire_line_cost(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    copper = next(i for i in result["line_items"] if i["product_name"] == "Copper Wire")
    assert copper["line_cost"] == 360.0


def test_cost_estimate_scales_with_qty(handler):
    result = handler.cost_estimate("B-1300", qty=2.0)
    assert result["total_cost"] == 2520.0


def test_cost_estimate_empty_product_name_returns_error(handler):
    result = handler.cost_estimate("", qty=1.0)
    assert "error" in result


def test_cost_estimate_price_available_true(handler):
    result = handler.cost_estimate("B-1300", qty=1.0)
    for item in result["line_items"]:
        assert item["price_available"] is True