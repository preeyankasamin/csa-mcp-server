"""CSA Aerotherm specific test configuration and fixtures."""

import os
import xmlrpc.client

import pytest
from dotenv import load_dotenv

# Load .env file
load_dotenv()


# ── CSA known test data ──────────────────────────────────────────────────────
# These are real records we confirmed exist in erp.csaerotherm.com
# Used as reliable inputs for CSA tool tests

CSA_TEST_PRODUCT_WITH_BOM = "CSA-CRM11"       # Middle Frame — has a BOM
CSA_TEST_PRODUCT_NO_VENDOR = "B-1300"         # Finished oven — no vendor needed
CSA_TEST_DUPLICATE_LOCATION = "WH/CSAPL Stock (copy)"  # Duplicate found in audit
CSA_ODOO_UID = 33831                          # preeyanka's UID on erp.csaerotherm.com


# ── Connection helper ────────────────────────────────────────────────────────

def get_csa_connection():
    """
    Returns a raw XML-RPC object model proxy authenticated with CSA credentials.
    This is NOT a full OdooConfig — just a direct XML-RPC connection for
    lightweight CSA-specific checks.
    """
    url = os.getenv("ODOO_URL")
    db = os.getenv("ODOO_DB")
    uid = CSA_ODOO_UID
    api_key = os.getenv("ODOO_API_KEY")

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return models, db, uid, api_key


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def csa_connection():
    """
    Fixture that provides a live XML-RPC connection to CSA Odoo.
    Any test that needs to query Odoo directly uses this fixture.

    Usage in a test:
        def test_something(csa_connection):
            models, db, uid, api_key = csa_connection
            result = models.execute_kw(db, uid, api_key, 'mrp.bom', 'search_read', ...)
    """
    models, db, uid, api_key = get_csa_connection()
    return models, db, uid, api_key


@pytest.fixture
def csa_env():
    """
    Fixture that returns all CSA .env variables as a dict.
    Use this when a test needs to verify environment is correctly configured.
    """
    return {
        "url": os.getenv("ODOO_URL"),
        "db": os.getenv("ODOO_DB"),
        "user": os.getenv("ODOO_USER"),
        "api_key": os.getenv("ODOO_API_KEY"),
        "yolo": os.getenv("ODOO_YOLO"),
        "env": os.getenv("ENV"),
        "log_level": os.getenv("ODOO_MCP_LOG_LEVEL"),
        "log_file": os.getenv("ODOO_MCP_LOG_FILE"),
    }