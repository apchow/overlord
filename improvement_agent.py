"""Governed continuous-improvement agent for policy tuning.

This agent learns only from explicit human review labels. It can draft a policy
revision, but it never edits application source or silently changes payment
controls. A reviewer must activate the draft through the existing policy
hot-swap and re-audit flow.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

import overlord_db
from policy_engine import load_policies, validate_policy_config

SEVERITY_LADDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def analyze_feedback(limit: int = 500) -> dict[str, Any]:
    """Build a draft from repeated independent feedback; require human approval to activate."""
    config = load_policies()
    draft = deepcopy(config)
    active_by_id = {rule["rule_id"]: rule for rule in draft["rules"]}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    feedback_rows = overlord_db.list_audit_feedback(limit)
    for row in feedback_rows:
        grouped[row["rule_id"]].append(row)

    proposals: list[dict[str, Any]] = []
    for rule_id, rows in grouped.items():
        distinct_audits = {row["audit_id"] for row in rows}
        confirmed = {row["audit_id"] for row in rows if row["verdict"] == "confirmed"}
        false_positive = {row["audit_id"] for row in rows if row["verdict"] == "false_positive"}
        needs_review = {row["audit_id"] for row in rows if row["verdict"] == "needs_review"}
        rule = active_by_id.get(rule_id)
        if len(distinct_audits) < 2:
            continue
        if len(confirmed) >= 2 and not false_positive and rule:
            current = str(rule.get("severity", "MEDIUM")).upper()
            level = SEVERITY_LADDER.index(current) if current in SEVERITY_LADDER else 1
            next_level = SEVERITY_LADDER[min(level + 1, len(SEVERITY_LADDER) - 1)]
            if next_level != current:
                rule["severity"] = next_level
                proposals.append({
                    "rule_id": rule_id, "kind": "severity_review", "evidence_audits": len(confirmed),
                    "recommendation": f"Escalate {rule_id} severity from {current} to {next_level}: repeated confirmed findings, zero false-positive labels.",
                    "drafted_change": {"severity": next_level},
                })
            else:
                proposals.append({
                    "rule_id": rule_id, "kind": "retain_critical_rule", "evidence_audits": len(confirmed),
                    "recommendation": f"Keep {rule_id} at CRITICAL; multiple independent audits were confirmed.",
                    "drafted_change": None,
                })
        elif len(false_positive) >= 2 and len(false_positive) / len(distinct_audits) >= 0.5:
            proposals.append({
                "rule_id": rule_id, "kind": "narrow_rule_review", "evidence_audits": len(false_positive),
                "recommendation": (
                    f"Review and narrow {rule_id}: {len(false_positive)} of {len(distinct_audits)} independent "
                    "audit labels were false positives. No automatic downgrade is drafted."
                ),
                "drafted_change": None,
            })
        elif len(needs_review) >= 2:
            proposals.append({
                "rule_id": rule_id, "kind": "collect_more_evidence", "evidence_audits": len(needs_review),
                "recommendation": f"Collect more reviewer labels for {rule_id}; current evidence is inconclusive.",
                "drafted_change": None,
            })

    safe_draft = validate_policy_config(draft)
    return {
        "feedback_rows_analyzed": len(feedback_rows),
        "distinct_rules_reviewed": len(grouped),
        "proposals": proposals,
        "draft_config": safe_draft,
        "requires_human_approval": True,
        "safety_note": (
            "No code or live payment rule was changed. Review the draft, then use the policy editor's "
            "Hot-Swap Config & Re-Run Audit action to activate an approved change."
        ),
    }
