# Phase 1 Go/No-Go Checklist
**Date:** 30/06/2026 (Week 3, Day 5)
**Decision:** GO — proceed to Phase 2

---

## Tools Implemented
- [x] explain_bom
- [x] what_can_i_build_today
- [x] simulate_order
- [x] cost_estimate
- [x] vendor_comparison
- [x] get_bom_with_stock
- [x] get_shortage_report
- [x] get_vendor_lead_times
- [x] explode_bom_multilevel (core helper, multi-level BOM with circular-reference guard)

## Infrastructure
- [x] Input validation (Pydantic) on all tools — empty/whitespace/negative/zero qty rejected
- [x] Error handling — Odoo faults, timeouts, unexpected exceptions all caught and returned as `{"error": ...}`
- [x] Caching layer (`_cache`, `_cache_get`, `_cache_set`) wired into get_bom_with_stock, get_shortage_report, get_vendor_lead_times
- [x] Immutable audit log (`csa_audit_log.py`) — every tool call recorded, append-only JSONL
- [x] Human approval log (`csa_human_approval_log.py`) — request/decision pattern, append-only JSONL, ready for Phase 2 write-tools
- [x] `.env` confirmed in `.gitignore` — credentials never pushed to GitHub

## Testing
- [x] 142 total tests in `tests/csa`, all passing
- [x] All tests offline/mocked (FakeHandler pattern) — no live Odoo dependency for correctness
- [x] New tests added: caching (4), audit log (4), human approval log (4)

## Known Issues (carried into Phase 2, not blockers)
- `conftest.py` timeout settings cause "offline" test files to still take 200-450+ seconds due to live Odoo calls in fixture setup — needs investigation, not urgent
- `erp.csaerotherm.com` has shown intermittent 502 Bad Gateway errors during long live test runs (e.g. B-1300G3ANG needing ~149 sequential calls) — flag to whoever manages the Odoo server
- Fork commits don't show on GitHub profile graph — cosmetic only, not a real issue

## Bug Found & Fixed This Session
**What happened:** When caching was added to `CSAToolHandler` (the real class), it was only mirrored into the `FakeHandler` inside `test_validation_and_errors.py`. Two other test files — `test_get_shortage_report.py` and `test_get_vendor_lead_times.py` — each have their OWN separate `FakeHandler` class (per project convention, no shared import from conftest.py). These two were missed, causing 24 test failures with `AttributeError: 'FakeHandler' object has no attribute '_cache_get'`.

**Why it happened:** Multiple independent `FakeHandler` copies exist across different test files instead of one shared source. Any change to `CSAToolHandler`'s internals (new attribute, new method) must be manually mirrored into every `FakeHandler` copy, or tests silently break the next time the full suite runs.

**Fix applied:** Added the same 3 lines (`self._cache = {}`, `self._cache_get`, `self._cache_set`) to both missed `FakeHandler.__init__` methods.

**Lesson for Phase 2 and beyond:** Whenever `CSAToolHandler.__init__` gains a new attribute or method other code depends on, immediately grep for every `FakeHandler` class across `tests/csa/*.py` and update all of them in the same session — don't assume updating one file is enough. Consider eventually refactoring to one shared `FakeHandler` in `conftest.py` to eliminate this whole class of bug, if conftest.py limitations allow it later.

## Manufacturing Process Understanding (captured this session)
- Confirmed BOM structure: Fabrication, Machined, Electrical, Other Bought-outs, Consumables, Fasteners, Dispatch components
- Confirmed ROR (Re-Ordering Rules) logic: nightly check, min/max thresholds, auto-creates MO (in-house, no approval) or PO (outsourced, needs next-day human approval)
- Confirmed MTO (Make to Order): no automation, manufacture exact order qty only
- Confirmed only ONE human approval gate exists in the current automated flow: outsourced PO approval. In-house MOs (whether sale-order-triggered or ROR-triggered) require zero human approval.
- Confirmed Phase 4 Web UI will use real per-user Odoo login credentials (XML-RPC authenticate()), not a separate auth system

---
**Signed off by:** Preeyanka
**Next phase:** Phase 2 — proactive watchers, async tool execution, connection pooling