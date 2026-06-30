"""
Tests for caching, audit log, and human approval log.
Added Phase 1 Week 3 Day 5.
"""

import json
import pytest
from mcp_server_odoo import csa_audit_log
from mcp_server_odoo import csa_human_approval_log


# ── Caching tests ────────────────────────────────────────────────

class FakeHandlerForCache:
    """Minimal handler exposing only the cache methods, for isolated testing."""
    def __init__(self):
        from mcp_server_odoo.csa_tools import CSAToolHandler
        self._cache = {}
        self._cache_get = lambda key: CSAToolHandler._cache_get(self, key)
        self._cache_set = lambda key, val: CSAToolHandler._cache_set(self, key, val)


@pytest.fixture
def cache_handler():
    return FakeHandlerForCache()


class TestCaching:

    def test_cache_miss_returns_none(self, cache_handler):
        result = cache_handler._cache_get("nonexistent_key")
        assert result is None

    def test_cache_set_then_get_returns_value(self, cache_handler):
        cache_handler._cache_set("my_key", {"data": 123})
        result = cache_handler._cache_get("my_key")
        assert result == {"data": 123}

    def test_cache_set_overwrites_existing_key(self, cache_handler):
        cache_handler._cache_set("my_key", {"data": 1})
        cache_handler._cache_set("my_key", {"data": 2})
        result = cache_handler._cache_get("my_key")
        assert result == {"data": 2}

    def test_different_keys_do_not_collide(self, cache_handler):
        cache_handler._cache_set("key_a", "value_a")
        cache_handler._cache_set("key_b", "value_b")
        assert cache_handler._cache_get("key_a") == "value_a"
        assert cache_handler._cache_get("key_b") == "value_b"


# ── Audit log tests ──────────────────────────────────────────────

class TestAuditLog:

    def test_log_tool_call_writes_one_line(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr(csa_audit_log, "AUDIT_LOG_PATH", str(fake_path))

        csa_audit_log.log_tool_call(
            tool_name="test_tool",
            inputs={"product_name": "B-1300"},
            result={"ok": True},
            cached=False,
        )

        lines = fake_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

    def test_log_tool_call_records_correct_fields(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr(csa_audit_log, "AUDIT_LOG_PATH", str(fake_path))

        csa_audit_log.log_tool_call(
            tool_name="get_shortage_report",
            inputs={"product_name": "B-1300", "qty": 2},
            result={"ok": True},
            cached=True,
        )

        entry = json.loads(fake_path.read_text(encoding="utf-8").strip())
        assert entry["tool"] == "get_shortage_report"
        assert entry["inputs"] == {"product_name": "B-1300", "qty": 2}
        assert entry["cached"] is True
        assert entry["success"] is True

    def test_log_tool_call_marks_error_results_as_failure(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr(csa_audit_log, "AUDIT_LOG_PATH", str(fake_path))

        csa_audit_log.log_tool_call(
            tool_name="get_shortage_report",
            inputs={"product_name": ""},
            result={"error": "Product name is required"},
            cached=False,
        )

        entry = json.loads(fake_path.read_text(encoding="utf-8").strip())
        assert entry["success"] is False

    def test_multiple_calls_append_not_overwrite(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr(csa_audit_log, "AUDIT_LOG_PATH", str(fake_path))

        csa_audit_log.log_tool_call("tool_one", {}, {"ok": True})
        csa_audit_log.log_tool_call("tool_two", {}, {"ok": True})

        lines = fake_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2


# ── Human approval log tests ─────────────────────────────────────

class TestHumanApprovalLog:

    def test_request_returns_a_request_id(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "approvals.jsonl"
        monkeypatch.setattr(csa_human_approval_log, "APPROVAL_LOG_PATH", str(fake_path))

        request_id = csa_human_approval_log.log_approval_request(
            tool_name="create_po", inputs={"vendor": "ABC Corp"}, requested_by="MCP-AI-Agent"
        )

        assert isinstance(request_id, str)
        assert len(request_id) > 0

    def test_request_writes_pending_status(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "approvals.jsonl"
        monkeypatch.setattr(csa_human_approval_log, "APPROVAL_LOG_PATH", str(fake_path))

        csa_human_approval_log.log_approval_request(
            tool_name="create_po", inputs={"vendor": "ABC Corp"}, requested_by="MCP-AI-Agent"
        )

        entry = json.loads(fake_path.read_text(encoding="utf-8").strip())
        assert entry["status"] == "pending"
        assert entry["type"] == "request"

    def test_decision_links_to_request_via_id(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "approvals.jsonl"
        monkeypatch.setattr(csa_human_approval_log, "APPROVAL_LOG_PATH", str(fake_path))

        request_id = csa_human_approval_log.log_approval_request(
            tool_name="create_po", inputs={"vendor": "ABC Corp"}, requested_by="MCP-AI-Agent"
        )
        csa_human_approval_log.log_approval_decision(
            request_id=request_id, decision="approved", decided_by="Preeyanka"
        )

        lines = fake_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        request_entry = json.loads(lines[0])
        decision_entry = json.loads(lines[1])
        assert request_entry["request_id"] == decision_entry["request_id"]
        assert decision_entry["decision"] == "approved"
        assert decision_entry["decided_by"] == "Preeyanka"

    def test_rejected_decision_is_recorded_correctly(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "approvals.jsonl"
        monkeypatch.setattr(csa_human_approval_log, "APPROVAL_LOG_PATH", str(fake_path))

        request_id = csa_human_approval_log.log_approval_request(
            tool_name="create_po", inputs={}, requested_by="MCP-AI-Agent"
        )
        csa_human_approval_log.log_approval_decision(
            request_id=request_id, decision="rejected", decided_by="Preeyanka", reason="Wrong vendor"
        )

        lines = fake_path.read_text(encoding="utf-8").strip().split("\n")
        decision_entry = json.loads(lines[1])
        assert decision_entry["decision"] == "rejected"
        assert decision_entry["reason"] == "Wrong vendor"