from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app
import policy_engine


def test_json_yaml_policy_hot_swap_parsing_and_atomic_save(tmp_path):
    json_text = json.dumps({
        "version": 1,
        "rules": [{
            "rule_id": "TEST-JSON", "rule_name": "Invoice cap", "field": "invoice_total",
            "operator": ">", "value": 1000, "severity": "HIGH", "action": "HOLD",
        }],
    })
    yaml_text = """version: 1
rules:
  - rule_id: TEST-YAML
    rule_name: Block rush fees
    field: invoice_text
    operator: contains_any
    value:
      - rush surcharge
    severity: CRITICAL
    action: BLOCK_PAYMENT
"""
    parsed_json = policy_engine.parse_policy_config(json_text, "rules.json")
    parsed_yaml = policy_engine.parse_policy_config(yaml_text, "rules.yaml")
    assert parsed_json["rules"][0]["rule_id"] == "TEST-JSON"
    assert parsed_yaml["rules"][0]["value"] == ["rush surcharge"]

    target = tmp_path / "policies.json"
    policy_engine.save_policies(parsed_yaml, target)
    assert policy_engine.load_policies(target) == parsed_yaml
    assert not list(tmp_path.glob("*.tmp"))


def test_custom_policy_forces_clean_match_into_red_policy_exception(tmp_path, monkeypatch):
    active_path = tmp_path / "policies.json"
    monkeypatch.setattr(policy_engine, "POLICY_FILE", active_path)
    policy_engine.save_policies({"version": 1, "rules": []}, active_path)
    policy_engine.add_policy_rule({
        "rule_id": "JUDGE-CUSTOM-001",
        "rule_name": "Block CloudScale vendor",
        "field": "vendor_name",
        "operator": "contains_any",
        "value": ["CloudScale Security"],
        "severity": "CRITICAL",
        "reason": "This vendor is suspended pending compliance review.",
        "action": "BLOCK_PAYMENT_AND_ESCALATE",
    }, active_path)

    frames = list(app.run_audit(
        "Scenario C: Clean 3-Way Match ($0.00 Variance)",
        "3-Way Match",
        chaos_mode=False,
        apply_tax=False,
    ))
    last = frames[-1]
    assert "POLICY EXCEPTION (PAYMENT BLOCKED)" in last[1]
    assert "POLICY EXCEPTION (PAYMENT BLOCKED)" in last[4]
    assert "JUDGE-CUSTOM-001" in last[16]
    assert last[9]["policy_violations"][0]["rule_id"] == "JUDGE-CUSTOM-001"
    assert last[9]["audit_id"]
    assert "[POLICY ENGINE // CRITICAL]" in last[3]
