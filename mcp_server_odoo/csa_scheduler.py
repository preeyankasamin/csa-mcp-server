"""
CSA Aerotherm - Scheduler
Runs all watchers automatically on a fixed schedule using APScheduler.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from mcp_server_odoo.config import load_config
from mcp_server_odoo.odoo_connection import OdooConnection
from mcp_server_odoo.csa_stock_alert_watcher import run_stock_alert_watcher
from mcp_server_odoo.logging_config import get_logger
from pathlib import Path

logger = get_logger(__name__)


def _get_connection():
    """
    Creates a fresh, authenticated Odoo connection.
    Called fresh each time a watcher runs, so we never reuse
    a stale/expired session.
    """
    config = load_config(env_file=Path(__file__).parent.parent.parent / ".env")
    conn = OdooConnection(config)
    conn.connect()
    conn.authenticate()
    return conn


def stock_alert_job():
    """
    Wrapper function APScheduler will call on schedule.
    Creates its own connection, runs the watcher, logs the result.
    """
    logger.info("Scheduled job started: stock_alert_job")
    try:
        conn = _get_connection()
        result = run_stock_alert_watcher(conn)
        logger.info(
            f"stock_alert_job complete: "
            f"{len(result['critical_new'])} new critical alerts"
        )
    except Exception as e:
        logger.error(f"stock_alert_job failed: {e}")

def start_scheduler():
    """
    Creates and starts the background scheduler with all watcher jobs.
    Call this once when the MCP server starts up.
    """
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        stock_alert_job,
        trigger="cron",
        hour=2,
        minute=0,
        id="stock_alert_watcher",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("CSA Scheduler started. Stock Alert Watcher runs daily at 02:00.")
    return scheduler

