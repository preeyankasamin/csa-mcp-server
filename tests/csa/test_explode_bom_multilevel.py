"""
Tests for explode_bom_multilevel in CSAToolHandler.
All tests run against live Odoo at erp.csaerotherm.com.
"""
import pytest
from tests.csa.conftest import get_csa_connection
import xmlrpc.client
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ── Simple connection wrapper (same pattern as quick test) ─────────────────

url = os.getenv("ODOO_URL")
db = os.getenv("ODOO_DB")
uid = 33831
api_key = os.getenv("ODOO_API_KEY")

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")


class SimpleConnection:
    """Wraps raw xmlrpc so CSAToolHandler methods can call self.connection.execute_kw"""
    def execute_kw(self, model, method, args, kwargs=None):
        if kwargs is None:
            kwargs = {}
        return models.execute_kw(db, uid, api_key, model, method, args, kwargs)


from mcp_server_odoo.csa_tools import CSAToolHandler
from mcp.server.fastmcp import FastMCP


class FakeHandler:
    """
    Minimal stand-in for CSAToolHandler.
    Borrows the three methods we need without going through OdooConnection.
    """
    def __init__(self):
        self.connection = SimpleConnection()

    _get_bom_for_product_id = CSAToolHandler._get_bom_for_product_id
    _explode = CSAToolHandler._explode
    explode_bom_multilevel = CSAToolHandler.explode_bom_multilevel


@pytest.fixture(scope="module")
def handler():
    """One FakeHandler instance shared across all tests in this file."""
    return FakeHandler()


# ── Tests ──────────────────────────────────────────────────────────────────

def test_explode_returns_found_true_for_known_product(handler):
    """B-1300G3ANG exists in Odoo and has a BOM — must return found=True."""
    result = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    assert result["found"] is True


def test_explode_returns_found_false_for_unknown_product(handler):
    """A product that does not exist must return found=False cleanly."""
    result = handler.explode_bom_multilevel("XXXXDOESNOTEXIST9999", qty=1)
    assert result["found"] is False


def test_explode_returns_raw_materials_list(handler):
    """Result must contain a non-empty raw_materials list for a known product."""
    result = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    assert "raw_materials" in result
    assert len(result["raw_materials"]) > 0


def test_explode_goes_deeper_than_single_level(handler):
    """
    B-1300G3ANG has 6 direct components — all of which have sub-BOMs.
    So the exploded list must be larger than 6.
    """
    result = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    assert result["total_unique_raw_materials"] > 6


def test_explode_each_raw_material_has_required_fields(handler):
    """Every item in raw_materials must have product_id, product_name, qty_needed, uom."""
    result = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    for mat in result["raw_materials"]:
        assert "product_id" in mat
        assert "product_name" in mat
        assert "qty_needed" in mat
        assert "uom" in mat


def test_explode_qty_scales_correctly(handler):
    """
    If qty=2, every raw material quantity must be exactly double qty=1.
    """
    result_1 = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    result_2 = handler.explode_bom_multilevel("B-1300G3ANG", qty=2)

    mats_1 = {m["product_id"]: m["qty_needed"] for m in result_1["raw_materials"]}
    mats_2 = {m["product_id"]: m["qty_needed"] for m in result_2["raw_materials"]}

    assert set(mats_1.keys()) == set(mats_2.keys()), "Same products must appear for qty=1 and qty=2"

    for pid in mats_1:
        assert round(mats_2[pid], 4) == round(mats_1[pid] * 2, 4), (
            f"product_id={pid} qty should double: "
            f"got {mats_2[pid]} expected {mats_1[pid] * 2}"
        )


def test_explode_no_duplicate_product_ids(handler):
    """
    Each product_id must appear only once in raw_materials.
    Duplicates mean the merge step failed.
    """
    result = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    ids = [m["product_id"] for m in result["raw_materials"]]
    assert len(ids) == len(set(ids)), "Duplicate product_ids found in raw_materials"


def test_explode_all_qty_needed_are_positive(handler):
    """Every raw material must have qty_needed > 0."""
    result = handler.explode_bom_multilevel("B-1300G3ANG", qty=1)
    for mat in result["raw_materials"]:
        assert mat["qty_needed"] > 0, (
            f"'{mat['product_name']}' has qty_needed={mat['qty_needed']}"
        )