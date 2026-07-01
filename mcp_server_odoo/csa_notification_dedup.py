"""
CSA Aerotherm - Notification Deduplication
Prevents the same alert from being sent repeatedly within a 6-hour cooldown window.
Entries are append-only (never edited or deleted).
"""
import json
import os
from datetime import datetime, timezone, timedelta

DEDUP_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "csa_notification_dedup.jsonl")
COOLDOWN_HOURS = 6

def _ensure_log_dir():
    """Create the logs directory if it does not exist."""
    log_dir = os.path.dirname(DEDUP_LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)

def should_send(fingerprint: str) -> bool:
    """
    Return True if this alert should be sent (not sent in last 6 hours).
    Return False if it was already sent recently — skip it.

    fingerprint -- unique label for this alert e.g. "work_order_stuck|42"
    """
    _ensure_log_dir()
    if not os.path.exists(DEDUP_LOG_PATH):
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
    with open(DEDUP_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry["fingerprint"] == fingerprint:
                sent_at = datetime.fromisoformat(entry["sent_at"])
                if sent_at > cutoff:
                    return False
    return True

def mark_sent(fingerprint: str):
    """
    Record that this alert was just sent right now.
    fingerprint -- unique label for this alert e.g. "work_order_stuck|42"
    """
    _ensure_log_dir()
    entry = {
        "fingerprint": fingerprint,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(DEDUP_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")