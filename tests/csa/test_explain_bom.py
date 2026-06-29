"""
Unit tests for explain_bom.
Uses FakeHandler -- no live Odoo connection required.
"""

import pytest
from mcp_server_odoo.csa_tools import CSAToolHandler


# ── FakeHandler ────────────────────────────────────────────────────────────────
# A fake version of CSAToolHandler that intercepts all Odoo calls
# and returns hardcoded data instead of hitting the real server.

class FakeConnection:
    """Pretends to be OdooConnection. Returns hardcoded Odoo responses."""

    def execute_kw(self, model, method, args, kwargs=None):
        kwargs = kwargs or {}

        # ── mrp.bom search ────────────────────────────────────────────────────
        if model == "mrp.bom" and method == "search_read":
            domain = args[0] if args else []
            # Return empty if searching for unknown product
            if domain and "UNKNOWN_PRODUCT_XYZ" in str(domain):
                return []
            # Return one BOM for any other product
            return [{
                "id": 101,
                "product_tmpl_id": [55, "Test Oven B-100"],
                "product_qty": 1.0,
                "product_uom_id": [1, "Nos"],
                "bom_line_ids": [201, 202, 203],
            }]

        # ── mrp.bom.line fetch ────────────────────────────────────────────────
        if model == "mrp.bom.line" and method == "search_read":
            return [
                # comp 201: has its own BOM -> sub-assembly
                {"id": 201, "product_id": [301, "Burner Assembly"], "product_qty": 2.0, "product_uom_id": [1, "Nos"]},
                # comp 202: no BOM -> raw material
                {"id": 202, "product_id": [302, "Steel Sheet 2mm"], "product_qty": 4.0, "product_uom_id": [1, "Nos"]},
                # comp 203: no BOM -> raw material
                {"id": 203, "product_id": [303, "Bolt M8"], "product_qty": 16.0, "product_uom_id": [1, "Nos"]},
            ]

        # ── product.product read (used by _get_bom_for_product_id) ────────────
        if model == "product.product" and method == "read":
            product_id = args[0][0]
            return [{"id": product_id, "product_tmpl_id": [product_id + 1000, f"Template {product_id}"]}]

        # ── mrp.bom search for sub-assembly check ─────────────────────────────
        # product_id 301 (Burner Assembly) HAS a BOM -> sub-assembly
        # product_id 302, 303 have NO BOM -> raw material
        if model == "mrp.bom" and method == "search_read":
            return []

        return []


class FakeHandler(CSAToolHandler):
    """CSAToolHandler with real Odoo connection replaced by FakeConnection."""

    def __init__(self):
        # Skip the real __init__ (which connects to Odoo)
        # Set only what explain_bom needs
        self.connection = FakeConnection()

    def _get_bom_for_product_id(self, product_id: int):
        """
        Override: product 301 has a sub-BOM, others do not.
        301 = Burner Assembly (sub-assembly)
        302 = Steel Sheet (raw material)
        303 = Bolt M8 (raw material)
        """
        if product_id == 301:
            return {"id": 999, "product_qty": 1.0, "bom_line_ids": []}
        return None


# ── Fixture ────────────────────────────────────────────────────────────────────

@pytest.fixture
def handler():
    return FakeHandler()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_explain_bom_found(handler):
    """A known product must return found=True."""
    result = handler.explain_bom("B-100")
    assert result["found"] is True


def test_explain_bom_not_found(handler):
    """An unknown product must return found=False."""
    result = handler.explain_bom("UNKNOWN_PRODUCT_XYZ")
    assert result["found"] is False


def test_explain_bom_not_found_has_message(handler):
    """found=False result must include a message field."""
    result = handler.explain_bom("UNKNOWN_PRODUCT_XYZ")
    assert "message" in result


def test_explain_bom_has_finished_product(handler):
    """Result must include finished_product name."""
    result = handler.explain_bom("B-100")
    assert "finished_product" in result
    assert result["finished_product"] == "Test Oven B-100"


def test_explain_bom_total_components_correct(handler):
    """total_components must equal number of items in components list."""
    result = handler.explain_bom("B-100")
    assert result["total_components"] == len(result["components"])


def test_explain_bom_sub_assembly_count(handler):
    """sub_assembly_count must equal components with type=sub_assembly."""
    result = handler.explain_bom("B-100")
    actual = sum(1 for c in result["components"] if c["type"] == "sub_assembly")
    assert result["sub_assembly_count"] == actual


def test_explain_bom_raw_material_count(handler):
    """raw_material_count must equal components with type=raw_material."""
    result = handler.explain_bom("B-100")
    actual = sum(1 for c in result["components"] if c["type"] == "raw_material")
    assert result["raw_material_count"] == actual


def test_explain_bom_counts_add_up(handler):
    """sub_assembly_count + raw_material_count must equal total_components."""
    result = handler.explain_bom("B-100")
    assert result["sub_assembly_count"] + result["raw_material_count"] == result["total_components"]


def test_explain_bom_component_has_required_keys(handler):
    """Every component must have product_id, product_name, qty_needed, uom, type."""
    result = handler.explain_bom("B-100")
    required_keys = {"product_id", "product_name", "qty_needed", "uom", "type"}
    for comp in result["components"]:
        assert required_keys.issubset(comp.keys()), f"Missing keys in: {comp}"


def test_explain_bom_type_values_valid(handler):
    """Every component type must be either sub_assembly or raw_material."""
    result = handler.explain_bom("B-100")
    for comp in result["components"]:
        assert comp["type"] in ("sub_assembly", "raw_material")


def test_explain_bom_has_summary(handler):
    """Result must include a summary string."""
    result = handler.explain_bom("B-100")
    assert "summary" in result
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


def test_explain_bom_qty_scales(handler):
    """qty_needed for each component must scale with qty parameter."""
    result_1 = handler.explain_bom("B-100", qty=1)
    result_2 = handler.explain_bom("B-100", qty=2)
    for c1, c2 in zip(result_1["components"], result_2["components"]):
        assert round(c2["qty_needed"], 4) == round(c1["qty_needed"] * 2, 4)


def test_explain_bom_empty_name_returns_error(handler):
    """Empty product name must return an error, not crash."""
    result = handler.explain_bom("   ")
    assert "error" in result