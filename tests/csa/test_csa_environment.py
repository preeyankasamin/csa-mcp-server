"""
CSA Environment and Connection Tests
Verifies that .env is correctly configured and Odoo 17 is reachable.
Run these before any other CSA tests.
"""

import os
import xmlrpc.client

import pytest
from dotenv import load_dotenv

load_dotenv()


# ── Test 1: Environment variables ─────────────────────────────────────────────

def test_required_env_vars_present(csa_env):
    """
    Checks that all required .env variables are set.
    If any are missing, every other test will fail — so check this first.
    """
    assert csa_env["url"], "ODOO_URL is missing from .env"
    assert csa_env["db"], "ODOO_DB is missing from .env"
    assert csa_env["user"], "ODOO_USER is missing from .env"
    assert csa_env["api_key"], "ODOO_API_KEY is missing from .env"
    assert csa_env["log_level"], "ODOO_MCP_LOG_LEVEL is missing from .env"
    assert csa_env["log_file"], "ODOO_MCP_LOG_FILE is missing from .env"


def test_env_is_dev(csa_env):
    """
    Confirms ENV=dev is set.
    Prevents accidentally running dev tests against production config.
    """
    assert csa_env["env"] == "dev", f"Expected ENV=dev, got ENV={csa_env['env']}"


def test_yolo_is_read(csa_env):
    """
    Confirms ODOO_YOLO=read is set.
    This ensures the MCP server cannot write to Odoo during tests.
    """
    assert csa_env["yolo"] == "read", f"Expected ODOO_YOLO=read, got {csa_env['yolo']}"


def test_log_file_directory_exists(csa_env):
    """
    Confirms the logs folder exists on disk.
    If missing, the server will crash when it tries to write logs.
    """
    import pathlib
    log_file = csa_env["log_file"]
    log_dir = pathlib.Path(log_file).parent
    assert log_dir.exists(), f"Logs directory does not exist: {log_dir}"


# ── Test 2: Odoo 17 connectivity ──────────────────────────────────────────────

def test_odoo_version_is_17():
    """
    Connects to Odoo without authentication and checks version.
    Confirms we are talking to Odoo 17 specifically.
    """
    url = os.getenv("ODOO_URL")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    version = common.version()

    assert version["server_version"] == "17.0", \
        f"Expected Odoo 17.0, got {version['server_version']}"


def test_odoo_authentication_succeeds():
    """
    Authenticates with real credentials from .env.
    Confirms API key and UID are valid and accepted by Odoo.
    """
    url = os.getenv("ODOO_URL")
    db = os.getenv("ODOO_DB")
    uid = 33831
    api_key = os.getenv("ODOO_API_KEY")

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    # execute_kw = the main Odoo XML-RPC method for querying data
    # 'res.users' = Odoo model for users
    # 'read' = read operation
    # [[uid]] = read the record with this specific ID
    # ['name', 'login'] = only return these two fields
    result = models.execute_kw(
        db, uid, api_key,
        'res.users', 'read',
        [[uid]],
        {'fields': ['name', 'login']}
    )

    assert result, "Authentication failed — no result returned"
    assert result[0]["login"] == "preeyanka", \
        f"Expected login=preeyanka, got {result[0]['login']}"


# ── Test 3: Odoo 17 specific API check ───────────────────────────────────────

def test_mrp_bom_model_accessible(csa_connection):
    """
    Confirms mrp.bom model (Bill of Materials) is accessible.
    This is the core model for all BOM automation tools.
    """
    models, db, uid, api_key = csa_connection

    count = models.execute_kw(
        db, uid, api_key,
        'mrp.bom', 'search_count',
        [[]]
    )

    assert count > 0, "mrp.bom returned 0 records — BOM data missing or inaccessible"


def test_sale_order_model_accessible(csa_connection):
    """
    Confirms sale.order model is accessible.
    Sale Orders are the trigger for the entire automation pipeline.
    """
    models, db, uid, api_key = csa_connection

    count = models.execute_kw(
        db, uid, api_key,
        'sale.order', 'search_count',
        [[]]
    )

    assert count > 0, "sale.order returned 0 records — check access rights"


def test_stock_picking_model_accessible(csa_connection):
    """
    Confirms stock.picking model is accessible.
    Delivery orders live here — needed for delivery automation.
    """
    models, db, uid, api_key = csa_connection

    count = models.execute_kw(
        db, uid, api_key,
        'stock.picking', 'search_count',
        [[]]
    )

    assert count > 0, "stock.picking returned 0 records — check access rights"