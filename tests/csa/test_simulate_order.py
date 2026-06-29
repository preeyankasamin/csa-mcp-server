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

    def get_shortage_report(self, product_name, qty=1.0):
        if product_name == "":
            return {"error": "product_name cannot be empty"}
        return {
            "product_name": product_name,
            "qty": qty,
            "shortages": [
                {
                    "product_name": "Copper Wire",
                    "qty_needed": qty * 3.0,
                    "stock_qty": qty * 1.0,
                    "shortage_qty": qty * 2.0,
                    "uom": "Mtr",
                },
            ],
            "shortage_count": 1,
        }


@pytest.fixture
def handler():
    return FakeHandler()


def test_simulate_order_returns_dict(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert isinstance(result, dict)


def test_simulate_order_has_required_keys(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert "product_name" in result
    assert "requested_qty" in result
    assert "max_buildable_qty" in result
    assert "can_fulfill" in result
    assert "total_materials" in result
    assert "shortage_count" in result
    assert "materials" in result


def test_simulate_order_correct_product_name(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert result["product_name"] == "B-1300"


def test_simulate_order_correct_requested_qty(handler):
    result = handler.simulate_order("B-1300", qty=5.0)
    assert result["requested_qty"] == 5.0


def test_simulate_order_detects_shortage(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert result["shortage_count"] == 1


def test_simulate_order_cannot_fulfill_when_short(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert result["can_fulfill"] is False


def test_simulate_order_materials_list_has_correct_count(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert result["total_materials"] == 2


def test_simulate_order_material_has_required_keys(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    mat = result["materials"][0]
    assert "product_name" in mat
    assert "qty_needed" in mat
    assert "stock_qty" in mat
    assert "is_short" in mat
    assert "shortage_qty" in mat


def test_simulate_order_steel_rod_not_short(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    steel = next(m for m in result["materials"] if m["product_name"] == "Steel Rod")
    assert steel["is_short"] is False


def test_simulate_order_copper_wire_is_short(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    copper = next(m for m in result["materials"] if m["product_name"] == "Copper Wire")
    assert copper["is_short"] is True


def test_simulate_order_empty_product_name_returns_error(handler):
    result = handler.simulate_order("", qty=1.0)
    assert "error" in result


def test_simulate_order_max_buildable_limited_by_shortage(handler):
    result = handler.simulate_order("B-1300", qty=1.0)
    assert result["max_buildable_qty"] >= 0