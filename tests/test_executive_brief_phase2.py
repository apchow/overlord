from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app
import policy_engine
from executive_brief import build_brief_data, export_executive_brief, render_brief_markdown


def test_custom_invoice_total_policy_holds_scenario_c(tmp_path, monkeypatch):
    policy_path = tmp_path / "policies.json"
    monkeypatch.setattr(policy_engine, "POLICY_FILE", policy_path)
    policy_engine.save_policies({"version": 1, "rules": [{
        "rule_id": "TEST-OVER-400", "rule_name": "Approval ceiling", "field": "invoice_total",
        "operator": ">", "value": 400, "severity": "CRITICAL", "action": "BLOCK_PAYMENT",
    }]})
    frames = list(app.run_audit(
        "Scenario C: Clean 3-Way Match ($0.00 Variance)", "3-Way Match",
        chaos_mode=False, apply_tax=False,
    ))
    final = frames[-1]
    assert final[9]["executed"] is True
    assert final[9]["policy_violations"][0]["rule_id"] == "TEST-OVER-400"
    assert "POLICY EXCEPTION (PAYMENT BLOCKED)" in final[1]


def test_invalid_policy_config_returns_exact_gradio_output_count(tmp_path):
    outputs = app._policy_error_outputs("bad config")
    assert len(outputs) == 2 + len(app.audit_outputs)
    assert all(isinstance(item, app.gr.update().__class__) for item in outputs[1:])

    malformed_yaml = tmp_path / "malformed.yaml"
    malformed_yaml.write_text("rules: [not valid yaml: :", encoding="utf-8")
    for result in (
        list(app.hot_swap_config_and_reaudit("{not valid json", None)),
        list(app.hot_swap_config_and_reaudit("", str(malformed_yaml))),
    ):
        assert len(result) == 1
        assert len(result[0]) == 2 + len(app.audit_outputs)
        assert "Policy validation error" in result[0][0]


def test_brief_exports_have_citations_and_quantified_roi(tmp_path):
    ctx = {
        "executed": True, "po_id": "PO-EX-1", "inv_id": "INV-EX-1", "vendor": "Northwind",
        "po_amount": 300, "inv_total": 450, "variance": 150, "funds_protected": 150,
        "po_text": "PO PO-EX-1\nMAXIMUM AUTHORIZED AMOUNT: $300.00\nNON-BILLABLE EXTRAS clause applies.",
        "invoice_text": "Invoice INV-EX-1\nTOTAL DUE: $450.00\nRush fee $150.00",
        "po_data": {"vendor": "Northwind", "line_items": [{"description": "Service", "amount": 300}]},
        "invoice_data": {"line_items": [{"description": "Service", "amount": 300}, {"description": "Rush fee", "amount": 150}]},
        "discrepancy": {"detected": True, "variance": 150, "recovered": 150,
                        "flagged_items": [{"description": "Rush fee", "amount": 150, "reason": "Unauthorized surcharge"}]},
        "policy_violations": [{"rule_id": "TEST-RUSH", "rule_name": "No rush fee", "field": "invoice_text",
                               "operator": "contains_any", "expected": ["rush fee"], "actual": "Rush fee",
                               "severity": "HIGH", "reason": "Not authorized", "action": "BLOCK_PAYMENT"}],
        "telemetry": "[12:00:01] [POLICY ENGINE // HIGH] TEST-RUSH — No rush fee\n[SUPERVISOR AGENT] Invoice total $450 - PO total $300 = $150",
        "rag_context": "NON-BILLABLE EXTRAS require a signed change order.",
        "audit_mode": "3-Way Match",
    }
    brief = build_brief_data(ctx, [["r1"]], 900.0, 1000, 500, 2.5)
    assert brief["annualized_cfo_roi"] == 150000.0
    markdown = render_brief_markdown(brief)
    assert "TEST-RUSH" in markdown and "POLICY ENGINE" in markdown and "$150.00" in markdown
    for fmt, suffix in (("PDF", ".pdf"), ("Markdown", ".md"), ("CSV", ".csv")):
        path = export_executive_brief(brief, fmt, tmp_path)
        payload = open(path, "rb").read()
        assert path.endswith(suffix) and payload
        if fmt == "PDF":
            assert payload.startswith(b"%PDF-")
        else:
            assert b"TEST-RUSH" in payload and b"POLICY ENGINE" in payload


def test_dashboard_embeds_positioning_and_real_agent_framework():
    positioning = app.render_positioning_panel_html()
    assert "spend visibility to provable financial action" in positioning
    assert "evidence + decision + action + audit receipt" in positioning
    assert "POLICY MATH IS DETERMINISTIC" in positioning
    runbook = app.render_agent_framework_html()
    assert "PO Parser" in runbook and "Supervisor" in runbook


def test_unreachable_ollama_returns_quickly(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OLLAMA_FALLBACK_MODELS", "qwen2.5:3b,gemma2:2b")
    start = time.monotonic()
    assert app._call_local_ollama_safe("hello") is None
    assert time.monotonic() - start < 1.0
