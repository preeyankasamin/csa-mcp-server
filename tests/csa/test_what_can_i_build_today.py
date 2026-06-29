"""
Unit tests for what_can_i_build_today.
Uses FakeHandler -- no live Odoo connection required.
"""

import pytest
from mcp_server_odoo.csa_tools import CSAToolHandler


# ── FakeHandler ────────────────────────────────────────────────────────────────

class FakeConnection:
    """Returns hardcoded Odoo responses for what_can_i_build_today tests."""

    def execute_kw(self, model, method, args, kwargs=None):
        kwargs = kwargs or {}

        # ── mrp.bom: return 3 products ────────────────────────────────────────
        if model == "mrp.bom" and method == "search_read":
            return [
                {"id": 1, "product_tmpl_id": [10, "Deck Oven DO-1"], "product_qty": 1.0, "product_uom_id": [1, "Nos"]},
                {"id": 2, "product_tmpl_id": [20, "Proofer PR-2"],   "product_qty": 1.0, "product_uom_id": [1, "Nos"]},
                {"id": 3, "product_tmpl_id": [30, "Mixer MX-3"],     "product_qty": 1.0, "product_uom_id": [1, "Nos"]},
            ]

        return []


class FakeHandler(CSAToolHandler):
    """CSAToolHandler with get_shortage_report overridden to return fake data."""

    def __init__(self):
        self.connection = FakeConnection()

    def get_shortage_report(self, product_name: str, qty: float = 1.0):
        """
        Deck Oven  -> no shortages (can build)
        Proofer    -> has shortages (cannot build)
        Mixer      -> no shortages (can build)
        """
        if "Deck Oven" in product_name:
            return {
                "found": True,
                "finished_product": product_name,
                "qty_requested": qty,
                "total_raw_materials": 10,
                "shortage_count": 0,
                "has_shortages": False,
                "shortages": [],
            }
        if "Proofer" in product_name:
            return {
                "found": True,
                "finished_product": product_name,
                "qty_requested": qty,
                "total_raw_materials": 8,
                "shortage_count": 3,
                "has_shortages": True,
                "shortages": [
                    {"product_name": "Steel Sheet", "shortage_qty": 2.0},
                ],
            }
        if "Mixer" in product_name:
            return {
                "found": True,
                "finished_product": product_name,
                "qty_requested": qty,
                "total_raw_materials": 12,
                "shortage_count": 0,
                "has_shortages": False,
                "shortages": [],
            }
        return {"error": "not found"}


# ── Fixture ────────────────────────────────────────────────────────────────────

@pytest.fixture
def handler():
    return FakeHandler()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_returns_total_products_checked(handler):
    """total_products_checked must equal can_build + cannot_build counts."""
    result = handler.what_can_i_build_today()
    assert result["total_products_checked"] == 3


def test_can_build_count_correct(handler):
    """2 products have zero shortages -- can_build_count must be 2."""
    result = handler.what_can_i_build_today()
    assert result["can_build_count"] == 2


def test_cannot_build_count_correct(handler):
    """1 product has shortages -- cannot_build_count must be 1."""
    result = handler.what_can_i_build_today()
    assert result["cannot_build_count"] == 1


def test_can_build_is_list(handler):
    """can_build must be a list."""
    result = handler.what_can_i_build_today()
    assert isinstance(result["can_build"], list)


def test_cannot_build_is_list(handler):
    """cannot_build must be a list."""
    result = handler.what_can_i_build_today()
    assert isinstance(result["cannot_build"], list)


def test_can_build_products_have_zero_shortages(handler):
    """Every product in can_build must have shortage_count == 0."""
    result = handler.what_can_i_build_today()
    for item in result["can_build"]:
        assert item["shortage_count"] == 0


def test_cannot_build_products_have_shortages(handler):
    """Every product in cannot_build must have shortage_count > 0."""
    result = handler.what_can_i_build_today()
    for item in result["cannot_build"]:
        assert item["shortage_count"] > 0


def test_can_build_entry_has_required_keys(handler):
    """Every can_build entry must have product_name, produces_qty, uom, shortage_count."""
    result = handler.what_can_i_build_today()
    required_keys = {"product_name", "produces_qty", "uom", "shortage_count", "total_raw_materials"}
    for item in result["can_build"]:
        assert required_keys.issubset(item.keys()), f"Missing keys in: {item}"


def test_cannot_build_entry_has_required_keys(handler):
    """Every cannot_build entry must have required keys."""
    result = handler.what_can_i_build_today()
    required_keys = {"product_name", "produces_qty", "uom", "shortage_count", "total_raw_materials"}
    for item in result["cannot_build"]:
        assert required_keys.issubset(item.keys()), f"Missing keys in: {item}"


def test_counts_add_up(handler):
    """can_build_count + cannot_build_count must equal total_products_checked."""
    result = handler.what_can_i_build_today()
    assert result["can_build_count"] + result["cannot_build_count"] == result["total_products_checked"]


def test_proofer_is_in_cannot_build(handler):
    """Proofer has shortages -- must appear in cannot_build."""
    result = handler.what_can_i_build_today()
    names = [item["product_name"] for item in result["cannot_build"]]
    assert any("Proofer" in n for n in names)


def test_deck_oven_is_in_can_build(handler):
    """Deck Oven has no shortages -- must appear in can_build."""
    result = handler.what_can_i_build_today()
    names = [item["product_name"] for item in result["can_build"]]
    assert any("Deck Oven" in n for n in names)