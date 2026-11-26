from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import improvement_agent
import mcp_server
import overlord_db


def test_sql_persistence_hash_chain_and_mcp_tools(tmp_path):
    isolated_db = tmp_path / "competition.sqlite3"
    overlord_db.configure_database(f"sqlite:///{isolated_db.as_posix()}")
    try:
        overlord_db.init_db()
        overlord_db.persist_policy_revision(
            {"version": 1, "rules": []}, source="test"
        )
        audit = overlord_db.persist_audit_record({
            "event": "OVERLORD_AUDIT",
            "timestamp": "2026-11-26T00:00:00+00:00",
            "po_id": "PO-DB-1",
            "invoice_id": "INV-DB-1",
            "audit_mode": "3-Way Match",
            "status": "FLAGGED",
            "po_authorized": 100.0,
            "invoice_billed": 150.0,
            "variance": 50.0,
            "recovered": 50.0,
            "policy_violations": [{
                "rule_id": "MCP-DB-001", "rule_name": "Test hold", "severity": "HIGH",
                "reason": "Test rule matched.", "action": "HOLD",
            }],
        })
        audit_id = audit["audit_id"]

        assert overlord_db.get_audit(audit_id)["invoice_id"] == "INV-DB-1"
        assert overlord_db.list_audits(5)[0]["policy_violations"][0]["rule_id"] == "MCP-DB-001"
        feedback = overlord_db.record_audit_feedback(audit_id, "MCP-DB-001", "confirmed", "Rule matched evidence.")
        assert feedback["verdict"] == "confirmed"
        assert len(overlord_db.list_audit_feedback()) == 1
        learning_result = improvement_agent.analyze_feedback()
        assert learning_result["requires_human_approval"] is True
        assert learning_result["proposals"] == []

        verification = overlord_db.verify_compliance_ledger()
        assert verification["valid"] is True
        assert verification["events_checked"] == 3

        mcp_status = mcp_server.get_storage_status()
        assert mcp_status["database"]["audit_count"] == 1
        assert mcp_status["ledger_integrity"]["valid"] is True
        assert mcp_server.get_audit_details(audit_id)["po_id"] == "PO-DB-1"
    finally:
        overlord_db.configure_database(None)
