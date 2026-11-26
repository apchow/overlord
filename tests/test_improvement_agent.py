from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import improvement_agent
import overlord_db
import policy_engine


def test_repeated_confirmed_feedback_drafts_not_activates_severity_change(tmp_path, monkeypatch):
    policy_path = tmp_path / "policies.json"
    monkeypatch.setattr(policy_engine, "POLICY_FILE", policy_path)
    policy_engine.save_policies({
        "version": 1,
        "rules": [{
            "rule_id": "LEARN-001", "rule_name": "Recurring overage", "field": "variance",
            "operator": ">", "value": 25, "severity": "HIGH", "action": "HOLD",
        }],
    }, policy_path)
    overlord_db.configure_database(f"sqlite:///{(tmp_path / 'learning.sqlite3').as_posix()}")
    try:
        for index in range(2):
            audit = overlord_db.persist_audit_record({
                "event": "OVERLORD_AUDIT", "timestamp": f"2026-11-26T00:00:0{index}+00:00",
                "po_id": f"PO-{index}", "invoice_id": f"INV-{index}", "status": "FLAGGED",
                "po_authorized": 100, "invoice_billed": 150, "variance": 50, "recovered": 50,
                "policy_violations": [],
            })
            overlord_db.record_audit_feedback(audit["audit_id"], "LEARN-001", "confirmed", "Evidence checked.")

        result = improvement_agent.analyze_feedback()
        assert result["requires_human_approval"] is True
        assert result["proposals"][0]["kind"] == "severity_review"
        assert result["draft_config"]["rules"][0]["severity"] == "CRITICAL"
        # A proposal is not activation: the source policy file is unchanged.
        assert policy_engine.load_policies()["rules"][0]["severity"] == "HIGH"
    finally:
        overlord_db.configure_database(None)
