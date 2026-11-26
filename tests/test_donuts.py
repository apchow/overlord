from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("OVERLORD_LIVE_LLM", "0")
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app  # noqa: E402
import executive_brief  # noqa: E402
import policy_engine  # noqa: E402


def test_donut1_clean_match_flip_reset_and_error_padding():
    original_policies = policy_engine.load_policies()
    scenario_c = "Scenario C: Clean 3-Way Match ($0.00 Variance)"
    try:
        # 1. Baseline Scenario C passes cleanly
        clean_last = list(app.run_audit(scenario_c, "3-Way Match"))[-1]
        assert clean_last[9].get("status") == "cleared"
        assert not clean_last[9].get("policy_violations")

        # 2. Hot-swap custom rule invoice_total > 400 -> flips Scenario C cleanly
        hs_steps = list(
            app.add_rule_and_reaudit(
                "Max 400 Policy",
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
        assert audit_last[9].get("status") == "flagged"
        assert any(v.get("id") == "POL-003" for v in (audit_last[9].get("policy_violations") or []))
        assert "[SUPERVISOR AGENT] Verifying Policy Engine exception (POL-003)..." in audit_last[3]

        # 3. Reset Defaults restores POL-001 & POL-002 cleanly
        reset_last = list(app.reset_policies_and_reaudit(scenario_c, "3-Way Match"))[-1]
        reset_json, reset_banner, *reset_audit = reset_last
        assert "POL-001" in reset_json and "POL-002" in reset_json and "POL-003" not in reset_json
        assert "Policies Reset" in reset_banner
        assert reset_audit[9].get("status") == "cleared"

        # 4. Invalid JSON/YAML never raises and pads remaining outputs cleanly
        bad_frames = list(app.hotswap_config_and_reaudit(":::invalid [yaml & json"))
        assert len(bad_frames) == 1
        assert len(bad_frames[0]) == 2 + app.AUDIT_OUTPUT_COUNT
        assert "Hot-Swap Rejected" in bad_frames[0][1]
    finally:
        policy_engine.save_policies(original_policies)


def test_donut2_executive_brief_exports_and_citations():
    original_policies = policy_engine.load_policies()
    scenario_c = "Scenario C: Clean 3-Way Match ($0.00 Variance)"
    try:
        hs_steps = list(
            app.add_rule_and_reaudit(
                "Cap 400 Audit Rule",
                "invoice_total",
                ">",
                "400",
                "CRITICAL",
                "BLOCK_PAYMENT",
                scenario_c,
                "3-Way Match",
            )
        )
        audit_ctx = hs_steps[-1][2 + 9]
        assert audit_ctx.get("executed") is True
        assert audit_ctx.get("vendor")
        assert audit_ctx.get("telemetry_logs")

        rows, cum_total = app.build_ledger_rows_and_total()
        with tempfile.TemporaryDirectory() as td:
            pdf_path, pdf_md = executive_brief.export_executive_brief(
                audit_ctx, "PDF", td, rows, cum_total, 5000, 600, 2.5
            )
            md_path, md_md = executive_brief.export_executive_brief(
                audit_ctx, "Markdown (.md)", td, rows, cum_total, 5000, 600, 2.5
            )
            csv_path, _ = executive_brief.export_executive_brief(
                audit_ctx, "CSV", td, rows, cum_total, 5000, 600, 2.5
            )

            assert Path(pdf_path).is_file() and Path(pdf_path).stat().st_size > 1000
            assert Path(md_path).is_file() and Path(md_path).stat().st_size > 200
            assert Path(csv_path).is_file() and Path(csv_path).stat().st_size > 200

            md_text = Path(md_path).read_text(encoding="utf-8")
            assert "POL-003" in md_text
            assert "$900,000.00" in md_text
            assert "Telemetry Log:" in md_text and "[POLICY ENGINE" in md_text
            assert pdf_md.split("\n", 2)[2] == md_md.split("\n", 2)[2]

            with open(csv_path, encoding="utf-8", newline="") as f:
                csv_rows = list(csv.DictReader(f))
            assert len(csv_rows) >= 1
            assert any("POL-003" in r["title"] or "POL-003" in r["citation_clause_or_rule"] for r in csv_rows)
            assert any(float(r["annualized_cfo_roi"]) == 900000.0 for r in csv_rows)
            assert any(bool(r["citation_log_entry"].strip()) for r in csv_rows)

        # Handler test with live UI wrapper
        app.gr.Info = lambda *_a, **_kw: None
        out_path, preview = app.handle_export_executive_brief(audit_ctx, "Markdown (.md)", 5000, 600, 2.5)
        try:
            assert out_path and Path(out_path).is_file() and "POL-003" in preview
        finally:
            if out_path:
                Path(out_path).unlink(missing_ok=True)
    finally:
        policy_engine.save_policies(original_policies)


def test_local_ollama_fallback_safe_unreachable_fast_fail():
    prev_host = os.environ.get("OLLAMA_HOST")
    prev_backend = app._RUNTIME_STATE.get("llm_backend", "Auto (Gemini → Local Ollama)")
    try:
        # Unreachable local port (simulating Render cloud without Ollama) must fail gracefully in <1s
        os.environ["OLLAMA_HOST"] = "http://127.0.0.1:59999"
        t0 = time.monotonic()
        res = app._call_local_ollama_safe("Summarize this invoice", system_instruction="You are an auditor.")
        elapsed = time.monotonic() - t0
        assert res is None
        assert elapsed < 1.0, f"Unreachable Ollama check took too long: {elapsed:.2f}s"

        app.on_llm_backend_change("Local Only (Ollama: Qwen 5B / OLMoE)")
        t1 = time.monotonic()
        res_local = app._call_gemini_safe("Why did you flag this?", max_wait_s=5.0)
        assert res_local is None
        assert (time.monotonic() - t1) < 1.0

        app.on_llm_backend_change("Offline Deterministic")
        assert app._call_gemini_safe("Why did you flag this?") is None
    finally:
        app.on_llm_backend_change(prev_backend)
        if prev_host is None:
            os.environ.pop("OLLAMA_HOST", None)
        else:
            os.environ["OLLAMA_HOST"] = prev_host
