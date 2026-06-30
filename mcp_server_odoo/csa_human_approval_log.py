"""
CSA Aerotherm - Human Approval Log
Records when a risky AI action requests human approval, and the human's decision.
Two-step process: request first, decision later. Append-only (never edited or deleted).
"""
import json
import os
import uuid
from datetime import datetime, timezone

APPROVAL_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "csa_human_approvals.jsonl")


def _ensure_log_dir():
    """Create the logs directory if it does not exist."""
    log_dir = os.path.dirname(APPROVAL_LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)


def log_approval_request(tool_name: str, inputs: dict, requested_by: str) -> str:
    """
    Record that a risky action is asking for human approval.
    Returns a request_id that must be used later to record the decision.

    tool_name    -- name of the risky MCP tool requesting approval
    inputs       -- the input parameters the tool wants to run with
    requested_by -- who/what is asking (e.g. "MCP-AI-Agent")
    """
    _ensure_log_dir()
    request_id = str(uuid.uuid4())
    entry = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "request",
        "tool": tool_name,
        "inputs": inputs,
        "requested_by": requested_by,
        "status": "pending",
    }
    with open(APPROVAL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return request_id


def log_approval_decision(request_id: str, decision: str, decided_by: str, reason: str = None):
    """
    Record a human's decision on a previously requested approval.

    request_id -- the ID returned by log_approval_request
    decision   -- "approved" or "rejected"
    decided_by -- who made the decision (e.g. "Preeyanka")
    reason     -- optional free-text reason
    """
    _ensure_log_dir()
    entry = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "decision",
        "decision": decision,
        "decided_by": decided_by,
        "reason": reason,
    }
    with open(APPROVAL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")