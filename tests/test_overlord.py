from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


def test_dynamic_edited_invoice_parsing():
    custom_po = (
        "PURCHASE ORDER NO.: PO #7711\n"
        "VENDOR: Meridian Labs\n"
        "01. 1x Cloud Audit Node ........ $1,000.00\n"
        "MAXIMUM AUTHORIZED AMOUNT: $1,000.00\n"
    )
    custom_inv = (
        "INVOICE NO.: INV-7711\n"
        "01. 1x Cloud Audit Node ........ $1,000.00\n"
        "02. Rush Onboarding Fee ........ $250.00\n"
        "TOTAL DUE: $1,250.00\n"
    )
    steps = list(
        app.run_audit(
            app.DEFAULT_SCENARIO,
            "3-Way Match",
            po_text_input=custom_po,
            inv_text_input=custom_inv,
            gr_image=None,
            chaos_mode=False,
            apply_tax=False,
        )
    )
    last = steps[-1]
    assert last[0]["interactive"] is True
    assert "TOTAL RECOVERED: $250.00" in last[1]
    assert "DISCREPANCY DETECTED: $250.00 OVERCHARGE" in last[4]
    assert "INV-7711" in last[5]
    assert "PO #7711" in last[5]


def test_pdf_extraction_via_pymupdf():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name
    try:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PURCHASE ORDER NO.: PO #5555\n01. 1x GPU Cluster ........ $2,000.00")
        doc.save(pdf_path)
        doc.close()
        text = app.extract_uploaded_document_text(pdf_path)
        parsed = app.parse_po_document(text)
        assert parsed["po_number"] == "PO #5555"
        assert parsed["authorized_amount"] == 2000.00
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


def test_xai_chatbot_guardrail_and_exact_reply():
    steps = list(app.run_audit(app.DEFAULT_SCENARIO, "3-Way Match"))
    ctx = steps[-1][9]
    po_text = app.SCENARIOS[app.DEFAULT_SCENARIO]["po_text"]
    inv_text = app.SCENARIOS[app.DEFAULT_SCENARIO]["inv_text"]

    about_hist, _ = app.chat_with_auditor("What is the invoice about?", [], ctx, po_text, inv_text)
    about_reply = about_hist[-1]["content"]
    assert "600" in about_reply and "can only answer" not in about_reply.lower()

    why_hist, _ = app.chat_with_auditor("Why did you flag this?", [], ctx, po_text, inv_text)
    assert "100" in why_hist[-1]["content"]

    memo_hist, _ = app.chat_with_auditor(
        "Draft a 2-sentence internal memo approving the base $500 payment but rejecting the $100 fee.",
        [], ctx, po_text, inv_text,
    )
    assert "500" in memo_hist[-1]["content"] and "100" in memo_hist[-1]["content"]

    hypo_hist, _ = app.chat_with_auditor(
        "Explain what the system would do if the invoice was $450 instead of $600. Would it pass or fail?",
        [], ctx, po_text, inv_text,
    )
    assert "pass" in hypo_hist[-1]["content"].lower()

    refusal_hist, _ = app.chat_with_auditor("What is the capital of France?", [], ctx, po_text, inv_text)
    refusal = refusal_hist[-1]["content"].lower()
    assert "paris" not in refusal
    assert any(w in refusal for w in ("audit", "invoice", "purchase order", "po", "3-way"))


def test_chaos_mode_and_certificate_export():
    steps = list(app.run_audit("Scenario C: Clean 3-Way Match ($0.00 Variance)", "3-Way Match", chaos_mode=True))
    last = steps[-1]
    assert "[VISION ALERT]" in last[3]
    assert "ov-vision-badge--alert" in last[8]
    app.gr.Info = lambda *_a, **_kw: None
    cert_path = app.export_audit_certificate(last[9])
    assert cert_path is not None and Path(cert_path).is_file()


def test_mega_update_modules():
    # 1. Supervisor Agent 5th node on Scenario A
    steps_a = list(app.run_audit(app.DEFAULT_SCENARIO, "3-Way Match"))
    logs_a = steps_a[-1][3]
    assert "[SUPERVISOR AGENT] Verifying Auditor's math..." in logs_a
    assert "[SUPERVISOR AGENT] 600 - 500 = 100. Calculations mathematically verified. Routing to Dispute." in logs_a

    # 2. Vision XAI Bounding Box on Scenario B
    steps_b = list(app.run_audit("Scenario B: Short-Delivery GPU Fraud ($2,000 Overcharge)", "3-Way Match"))
    logs_b = steps_b[-1][3]
    bbox_img_path = steps_b[-1][15]
    assert "[VISION XAI] Bounding box drawn over missing inventory." in logs_b
    assert bbox_img_path and Path(bbox_img_path).is_file()

    # 3. UPI QR Checkout & Simulate Payment Success
    col_upd, qr_upd, _fb, _st = app.open_upi_checkout(steps_a[-1][9])
    assert col_upd["visible"] is True
    assert qr_upd["value"] and Path(qr_upd["value"]).is_file()
    pay_banner, _rows, _kpi = app.simulate_payment_success(steps_a[-1][9])
    assert "Payment of $500.00 successful. Ledger updated." in pay_banner

    # 4. CFO ROI Calculator & Popup Flex
    roi_md = app.calculate_cfo_roi(5000, 600, 2.5)
    assert "Project Overlord will save you **$900,000** annually." in roi_md
    toasts: list[str] = []
    app.gr.Info = lambda msg: toasts.append(msg)
    app.send_dispute_to_vendor(steps_a[-1][5], steps_a[-1][9])
    assert any("Dispute sent. You just saved $100. At your current scale, this amounts to $120,000 saved this year." in t for t in toasts)


def test_zero_code_policy_engine_hot_swap():
    import policy_engine

    original_policies = policy_engine.load_policies()
    scenario_c = "Scenario C: Clean 3-Way Match ($0.00 Variance)"
    try:
        # 1. Baseline Scenario C passes cleanly under default POL-001 / POL-002
        clean_steps = list(app.run_audit(scenario_c, "3-Way Match"))
        clean_last = clean_steps[-1]
        assert not clean_last[9].get("policy_violations")
        assert "3-WAY MATCH VERIFIED: CLEARED FOR PAYMENT" in clean_last[4]

        # 2. Live Quick Rule Builder hot-swap: invoice_total > 400 -> BLOCK_PAYMENT flips Scenario C!
        hs_steps = list(
            app.add_rule_and_reaudit(
                "Cap Over 400",
                "invoice_total",
                ">",
                "400",
                "CRITICAL",
                "BLOCK_PAYMENT",
                scenario_c,
                "3-Way Match",
            )
        )
        updated_json, banner, *audit_last = hs_steps[-1]
        assert "POL-003" in updated_json
        assert "Hot-Swapped Rule `POL-003`" in banner
        assert "[POLICY ENGINE // CRITICAL] POL-003" in audit_last[3]
        assert "POLICY HOLD" in audit_last[2]
        assert "alert-box" in audit_last[4] and "DISCREPANCY DETECTED // POLICY EXCEPTION" in audit_last[4]
        assert "ov-pill--alert" in audit_last[7] and "ov-line-row--flagged" in audit_last[7] and "hl-flag-pulse" in audit_last[7]
        assert "[POLICY ENGINE VIOLATION]" in audit_last[16]

        # Check (3): Policy violations injected into XAI Chatbot context
        sc_c = app.SCENARIOS[scenario_c]
        chat_hist, _ = app.chat_with_auditor("Why did you flag this rule?", [], audit_last[9], sc_c["po_text"], sc_c["inv_text"])
        bot_reply = chat_hist[-1]["content"]
        assert "POL-003" in bot_reply or "Cap Over 400" in bot_reply or "BLOCK_PAYMENT" in bot_reply

        # Check (1): Invalid JSON/YAML config pads all remaining outputs with gr.update()
        bad_frames = list(app.hotswap_config_and_reaudit("{{{invalid-json-and-yaml"))
        assert len(bad_frames) == 1
        assert len(bad_frames[0]) == 19
        assert "Hot-Swap Rejected" in bad_frames[0][1]
        assert all(isinstance(x, dict) and "__type__" in x for x in bad_frames[0][2:])

        # Check (4): pyyaml present in requirements.txt
        req_text = Path("requirements.txt").read_text(encoding="utf-8").lower()
        assert "pyyaml" in req_text

        # 3. YAML config hot-swap parses & applies cleanly
        yaml_cfg = (
            "- id: POL-YAML-1\n"
            "  name: Block CloudScale Vendor\n"
            "  field: vendor_name\n"
            "  operator: contains_any\n"
            "  value: [cloudscale]\n"
            "  severity: HIGH\n"
            "  action: FLAG_CFO_REVIEW\n"
            "  active: true\n"
        )
        rules, msg = policy_engine.parse_policy_text(yaml_cfg)
        assert len(rules) == 1 and "YAML" in msg
        hits = policy_engine.evaluate_policies({"vendor_name": "CloudScale Security Corp."}, rules)
        assert len(hits) == 1 and hits[0]["id"] == "POL-YAML-1"
    finally:
        policy_engine.save_policies(original_policies)
