from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app
from executive_brief import build_executive_brief, render_brief_csv, render_brief_markdown, write_brief_pdf


def test_executive_brief_citations_and_three_urgent_exceptions(tmp_path):
    context = {
        "executed": True,
        "po_id": "PO #8842",
        "inv_id": "INV-2024-001",
        "scenario_name": "Scenario A",
        "po_amount": 500.0,
        "inv_total": 600.0,
        "policy_rule_count": 2,
        "po_text": """PURCHASE ORDER NO.: PO #8842
VENDOR: Apex Cognitive Systems LLC
01. 1x AI Software License ........ $500.00
MAXIMUM AUTHORIZED AMOUNT: $500.00 USD
1.2 NON-BILLABLE EXTRAS: Setup charges require countersigned approval.""",
        "invoice_text": """INVOICE NO.: INV-2024-001
01. 1x AI Software License ........ $500.00
02. Setup Fee (Post-Deployment Configuration) .... $100.00
TOTAL DUE: $600.00""",
        "po_data": {"vendor": "Apex Cognitive Systems LLC", "line_items": [{"description": "1x AI Software License", "amount": 500.0}]},
        "invoice_data": {"line_items": [
            {"description": "1x AI Software License", "amount": 500.0},
            {"description": "Setup Fee (Post-Deployment Configuration)", "amount": 100.0},
        ]},
        "gr_data": {"vision_summary": "1 Item Delivered. Match Confirmed."},
        "discrepancy": {
            "detected": True, "po_authorized": 500.0, "invoice_billed": 600.0,
            "variance": 100.0, "recovered": 100.0,
            "flagged_items": [{
                "description": "Setup Fee (Post-Deployment Configuration)",
                "amount": 100.0, "reason": "Uncontracted line item not authorized in PO",
            }],
        },
        "policy_violations": [{
            "rule_id": "POL-FEE-001", "rule_name": "Prohibited ancillary fees", "severity": "HIGH",
            "reason": "Invoice text contains setup fee.", "action": "BLOCK_PAYMENT_AND_REQUEST_CREDIT",
            "field": "invoice_text", "operator": "contains_any", "expected": ["setup fee"],
            "actual": "Vendor invoice contains setup fee",
        }],
        "telemetry": "[05:00:00] [POLICY ENGINE // HIGH] POL-FEE-001 — Prohibited ancillary fees",
    }
    brief = build_executive_brief(context)
    assert brief["summary"]["documents_processed"] == 3
    assert brief["summary"]["line_items_processed"] == 3
    assert brief["summary"]["overcharge_exposure"] == 100.0
    assert brief["summary"]["policy_payment_hold"] == 600.0
    assert brief["top_exceptions"][0]["id"] == "POL-FEE-001"
    citations = brief["top_exceptions"][0]["citations"]
    assert any(citation["reference"] == "Vendor invoice, line 3" for citation in citations)
    assert any("POLICY ENGINE // HIGH" in citation["quote"] for citation in citations)

    markdown = render_brief_markdown(brief)
    csv_text = render_brief_csv(brief)
    assert "Executive summary" in markdown
    assert "POLICY EXCEPTION" in markdown
    assert "Vendor invoice, line 3" in markdown
    assert "citation_reference" in csv_text and "POL-FEE-001" in csv_text

    pdf_path = tmp_path / "boardroom.pdf"
    write_brief_pdf(markdown, pdf_path)
    assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_clean_match_brief_reports_zero_exceptions():
    context = {
        "executed": True, "po_id": "PO #8850", "inv_id": "INV-2024-019",
        "po_amount": 1200.0, "inv_total": 1200.0, "policy_rule_count": 2,
        "po_data": {"vendor": "CloudScale", "line_items": [{"description": "SOC2", "amount": 1200.0}]},
        "invoice_data": {"line_items": [{"description": "SOC2", "amount": 1200.0}]},
        "discrepancy": {"detected": False, "po_authorized": 1200.0, "invoice_billed": 1200.0, "variance": 0.0, "recovered": 0.0, "flagged_items": []},
        "policy_violations": [],
    }
    brief = build_executive_brief(context)
    assert brief["summary"]["decision"].startswith("CLEARED")
    assert brief["summary"]["maximum_quantified_exposure"] == 0.0
    assert brief["summary"]["exceptions_found"] == 0


def test_gradio_report_export_callback_returns_downloadable_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CERT_EXPORT_DIR", str(tmp_path))
    context = {
        "executed": True, "po_id": "PO #1", "inv_id": "INV-1", "scenario_name": "Integration smoke",
        "po_amount": 10.0, "inv_total": 10.0, "policy_rule_count": 2,
        "po_data": {"vendor": "Example", "line_items": [{"description": "Service", "amount": 10.0}]},
        "invoice_data": {"line_items": [{"description": "Service", "amount": 10.0}]},
        "discrepancy": {"detected": False, "po_authorized": 10.0, "invoice_billed": 10.0, "variance": 0.0, "recovered": 0.0, "flagged_items": []},
        "policy_violations": [],
    }
    path, status, preview = app.export_executive_boardroom_brief(context, "CSV")
    assert path and os.path.isfile(path) and path.endswith(".csv")
    assert "Generated citation-backed CSV" in status
    assert "record_type" in preview
