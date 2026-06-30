"""
CSA Aerotherm - Immutable Audit Log
Every tool call is recorded here. Entries are append-only (never edited or deleted).
"""
import json
import os
from datetime import datetime, timezone

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "csa_audit.jsonl")


def _ensure_log_dir():
    """Create the logs directory if it does not exist."""
    log_dir = os.path.dirname(AUDIT_LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)


def log_tool_call(tool_name: str, inputs: dict, result: dict, cached: bool = False):
    """
    Append one audit entry to the log file.
    Each line is a valid JSON object (JSONL format).
    tool_name -- name of the MCP tool that was called
    inputs    -- the input parameters passed to the tool
    result    -- the result returned by the tool
    cached    -- True if result came from cache, False if from live Odoo
    """
    _ensure_log_dir()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "inputs": inputs,
        "cached": cached,
        "success": "error" not in result,
    }
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")