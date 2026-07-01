"""
Tests for csa_notification_dedup.py
No live Odoo calls — tests use a temp directory for the log file.
"""
import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import mcp_server_odoo.csa_notification_dedup as dedup


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    """
    Before each test — point the dedup log to a fresh temp file.
    After each test — temp file is automatically deleted by pytest.
    """
    fake_log = tmp_path / "csa_notification_dedup.jsonl"
    monkeypatch.setattr(dedup, "DEDUP_LOG_PATH", str(fake_log))


# --- should_send ---

def test_should_send_true_when_no_log_exists():
    result = dedup.should_send("work_order_stuck|42")
    assert result is True

def test_should_send_true_when_fingerprint_never_seen():
    dedup.mark_sent("work_order_stuck|99")
    result = dedup.should_send("work_order_stuck|42")
    assert result is True

def test_should_send_false_immediately_after_mark_sent():
    dedup.mark_sent("work_order_stuck|42")
    result = dedup.should_send("work_order_stuck|42")
    assert result is False

def test_should_send_true_after_cooldown_expired(monkeypatch):
    # Write a log entry with sent_at = 7 hours ago
    old_time = datetime.now(timezone.utc) - timedelta(hours=7)
    entry = {"fingerprint": "work_order_stuck|42", "sent_at": old_time.isoformat()}
    with open(dedup.DEDUP_LOG_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    result = dedup.should_send("work_order_stuck|42")
    assert result is True

def test_should_send_false_within_cooldown(monkeypatch):
    # Write a log entry with sent_at = 2 hours ago
    recent_time = datetime.now(timezone.utc) - timedelta(hours=2)
    entry = {"fingerprint": "work_order_stuck|42", "sent_at": recent_time.isoformat()}
    with open(dedup.DEDUP_LOG_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    result = dedup.should_send("work_order_stuck|42")
    assert result is False

def test_different_fingerprints_tracked_independently():
    dedup.mark_sent("work_order_stuck|42")
    result = dedup.should_send("mcp_risky_action|delete_bom")
    assert result is True


# --- mark_sent ---

def test_mark_sent_creates_log_file():
    dedup.mark_sent("work_order_stuck|42")
    assert Path(dedup.DEDUP_LOG_PATH).exists()

def test_mark_sent_writes_correct_fingerprint():
    dedup.mark_sent("work_order_stuck|42")
    with open(dedup.DEDUP_LOG_PATH, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert entry["fingerprint"] == "work_order_stuck|42"

def test_mark_sent_writes_sent_at():
    dedup.mark_sent("work_order_stuck|42")
    with open(dedup.DEDUP_LOG_PATH, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert "sent_at" in entry

def test_mark_sent_multiple_appends():
    dedup.mark_sent("work_order_stuck|42")
    dedup.mark_sent("work_order_stuck|42")
    with open(dedup.DEDUP_LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2