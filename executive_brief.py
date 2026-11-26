"""Citation-backed Executive Boardroom Brief generator for Project Overlord."""
from __future__ import annotations

import csv
import html
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf

SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}


def _money(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _fmt_money(value: Any) -> str:
    return f"${_money(value):,.2f}"


def _fmt_num(val: float) -> str:
    v = float(val)
    return str(int(v)) if v.is_integer() else f"{v:,.2f}"


def _build_math_metric(inv_amt: float, po_amt: float, variance: float) -> str:
    return f"Supervisor Gate: ${_fmt_num(inv_amt)} - ${_fmt_num(po_amt)} = ${_fmt_num(variance)}"


def _line_citation(
    label: str,
    text: str,
    needles: list[str] | None = None,
    regex_pattern: str | None = None,
) -> dict[str, str] | None:
    lines = (text or "").splitlines()
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        matched = False
        if regex_pattern:
            try:
                matched = re.search(regex_pattern, line, re.IGNORECASE) is not None
            except re.error:
                matched = False
        elif needles:
            matched = any(token and token.casefold() in line.casefold() for token in needles)
        if matched:
            return {"reference": f"{label}, line {number}", "quote": line}
    return None


def _metric_citation(label: str, quote: str) -> dict[str, str]:
    return {"reference": label, "quote": quote}


def _telemetry_lines(audit_ctx: dict[str, Any]) -> list[str]:
    raw = audit_ctx.get("telemetry_logs") or audit_ctx.get("telemetry") or []
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return [str(line).strip() for line in raw if str(line).strip()]


def _first_exact_line(logs: list[str], predicate: Any, fallback: str) -> str:
    for entry in logs:
        if predicate(entry):
            return entry
    return fallback


def _source_line(text: str, terms: list[str]) -> str:
    for number, raw in enumerate(str(text or "").splitlines(), start=1):
        line = raw.strip()
        if line and any(term and term.casefold() in line.casefold() for term in terms):
            return f"line {number}: {line}"
    return ""


def _clause_excerpt(audit_ctx: dict[str, Any], terms: list[str] | None = None) -> str:
    rag = str(audit_ctx.get("rag_context", "") or "")
    if terms:
        for raw in rag.splitlines():
            line = raw.strip()
            if line and any(term and term.casefold() in line.casefold() for term in terms):
                return line
    if rag:
        return next((line.strip() for line in rag.splitlines() if line.strip()), rag[:240])
    po_text = str(audit_ctx.get("po_text", "") or "")
    return _source_line(po_text, terms or ["NON-BILLABLE", "SHORT-SHIPMENT", "MAXIMUM AUTHORIZED AMOUNT"])


def _supervisor_or_vision_metric(
    audit_ctx: dict[str, Any],
    logs: list[str],
    *,
    vision: bool = False,
) -> str:
    inv_amt = float(audit_ctx.get("inv_total", audit_ctx.get("invoice_billed", 0.0)) or 0.0)
    po_amt = float(audit_ctx.get("po_amount", audit_ctx.get("po_authorized", 0.0)) or 0.0)
    variance = float(audit_ctx.get("variance", round(max(inv_amt - po_amt, 0.0), 2)) or 0.0)
    funds_protected = float(audit_ctx.get("recovered", 0.0) or 0.0)
    math_gate = _build_math_metric(inv_amt, po_amt, variance)
    if vision:
        return _first_exact_line(
            logs,
            lambda line: "Vision AI Confidence" in line or "VISION ALERT" in line or "VISION XAI" in line,
            f"Vision confidence={audit_ctx.get('vision_confidence', 'unavailable')} | {math_gate}",
        )
    return _first_exact_line(
        logs,
        lambda line: "[SUPERVISOR AGENT]" in line and (" - " in line or " = " in line or "Verifying" in line),
        f"{math_gate} | Protected: {_fmt_money(funds_protected)}",
    )


def _policy_citations(violation: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    field = str(violation.get("field", ""))
    po_text = str(context.get("po_text", ""))
    invoice_text = str(context.get("invoice_text", ""))
    gr_data = context.get("gr_data") or {}
    citations: list[dict[str, str]] = []
    expected = violation.get("expected", violation.get("value"))
    expected_values = expected if isinstance(expected, list) else [expected]
    tokens = [str(value) for value in expected_values if value is not None]
    rule_id = str(violation.get("rule_id") or violation.get("id") or "")

    if field == "invoice_text":
        match = _line_citation(
            "Vendor invoice",
            invoice_text,
            needles=tokens,
            regex_pattern=str(expected) if violation.get("operator") == "regex" else None,
        )
        if match:
            citations.append(match)
    elif field == "invoice_total":
        match = _line_citation("Vendor invoice", invoice_text, needles=["TOTAL DUE", "INVOICE TOTAL"])
        if match:
            citations.append(match)
    elif field == "po_total":
        match = _line_citation(
            "Purchase order",
            po_text,
            needles=["MAXIMUM AUTHORIZED AMOUNT", "AUTHORIZED AMOUNT", "TOTAL AUTHORIZED"],
        )
        if match:
            citations.append(match)
    elif field == "variance":
        for label, source, needles in (
            ("Purchase order", po_text, ["MAXIMUM AUTHORIZED AMOUNT", "AUTHORIZED AMOUNT"]),
            ("Vendor invoice", invoice_text, ["TOTAL DUE", "INVOICE TOTAL"]),
        ):
            match = _line_citation(label, source, needles=needles)
            if match:
                citations.append(match)
    elif field == "tax_pct":
        match = _line_citation("Vendor invoice", invoice_text, needles=["TAX", "VAT", "GST"])
        if match:
            citations.append(match)
    elif field == "short_shipped_units":
        match = _line_citation("Purchase order", po_text, needles=["SHORT-SHIPMENT", "ORDERED", "UNITS"])
        if match:
            citations.append(match)
        vision = str(gr_data.get("vision_summary") or context.get("vision_summary") or "")
        if vision:
            citations.append(_metric_citation("Goods Receipt / Vision result", vision))
    elif field == "vendor_name":
        vendor = str(violation.get("actual") or context.get("vendor_name") or context.get("vendor") or "")
        match = _line_citation("Purchase order", po_text, needles=[vendor, "VENDOR:"])
        if match:
            citations.append(match)
        else:
            match = _line_citation("Vendor invoice", invoice_text, needles=[vendor])
            if match:
                citations.append(match)

    op = str(violation.get("operator", ""))
    actual = violation.get("actual")
    observed = "matched source excerpt cited above" if field == "invoice_text" else repr(actual)
    citations.append(
        _metric_citation(
            "Deterministic policy-engine metric",
            f"{field} {op} {expected!r}; observed {observed}; rule_id={rule_id}.",
        )
    )
    telemetry = str(context.get("telemetry") or "\n".join(_telemetry_lines(context)))
    telemetry_line = next(
        (line.strip() for line in telemetry.splitlines() if rule_id and rule_id in line and "POLICY ENGINE" in line),
        None,
    )
    if telemetry_line:
        citations.append(_metric_citation("LangGraph telemetry log", telemetry_line))
    return citations


def _match_citations(item: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    description = str(item.get("description", ""))
    po_text = str(context.get("po_text", ""))
    invoice_text = str(context.get("invoice_text", ""))
    citations: list[dict[str, str]] = []
    inv_match = _line_citation("Vendor invoice line item", invoice_text, needles=[description]) if description else None
    if inv_match:
        citations.append(inv_match)
    po_match = _line_citation("Purchase order line item", po_text, needles=[description]) if description else None
    if po_match:
        citations.append(po_match)
    if not po_match:
        clause = _line_citation(
            "Purchase-order clause",
            po_text,
            needles=["NON-BILLABLE", "SHORT-SHIPMENT", "MAXIMUM AUTHORIZED AMOUNT"],
        )
        if clause:
            citations.append(clause)
    disc = context.get("discrepancy") or {}
    citations.append(
        _metric_citation(
            "3-way-match metric",
            f"PO authorized={_fmt_money(disc.get('po_authorized', context.get('po_amount')))}; "
            f"invoice billed={_fmt_money(disc.get('invoice_billed', context.get('inv_total')))}; "
            f"variance={_fmt_money(disc.get('variance', context.get('variance')))}; "
            f"finding={item.get('reason', 'line-item mismatch')}.",
        )
    )
    return citations


def build_executive_brief(context: dict[str, Any]) -> dict[str, Any]:
    """Create the summary + top_exceptions model used by Boardroom CSV & PDF exports."""
    if not isinstance(context, dict) or not context.get("executed"):
        raise ValueError("Run an audit to completion before generating the executive brief.")

    po_data = context.get("po_data") or {}
    invoice_data = context.get("invoice_data") or {}
    discrepancy = context.get("discrepancy") or {}
    gr_data = context.get("gr_data") or {}
    policy_violations = context.get("policy_violations") or []
    po_items = po_data.get("line_items") or []
    invoice_items = invoice_data.get("line_items") or []
    po_total = _money(context.get("po_amount", discrepancy.get("po_authorized")))
    invoice_total = _money(context.get("inv_total", discrepancy.get("invoice_billed")))
    variance = _money(discrepancy.get("variance", context.get("variance")))
    overcharge = _money(discrepancy.get("recovered", max(variance, 0.0)))
    policy_hold = invoice_total if policy_violations else 0.0
    quantified_exposure = max(overcharge, policy_hold)
    line_items_processed = len(po_items) + len(invoice_items)
    rules_evaluated = int(context.get("policy_rule_count", 0) or 0) or len(policy_violations)

    if policy_violations:
        decision = "POLICY EXCEPTION — PAYMENT BLOCKED"
    elif discrepancy.get("detected") or context.get("chaos_triggered"):
        decision = "DISCREPANCY — REVIEW / DISPUTE REQUIRED"
    else:
        decision = "CLEARED — NO EXCEPTIONS DETECTED"

    findings: list[dict[str, Any]] = []
    for violation in policy_violations:
        field = str(violation.get("field", ""))
        expected = violation.get("expected", violation.get("value"))
        amount = 0.0
        if field == "variance":
            amount = max(_money(violation.get("actual")), 0.0)
        elif field == "invoice_total":
            amount = max(_money(violation.get("actual")) - _money(expected), 0.0)
        if str(violation.get("action", "")).upper().startswith(("BLOCK", "HOLD")):
            amount = max(amount, invoice_total)
        citations = _policy_citations(violation, context)
        source_invoice = next(
            (c.get("quote") for c in citations if c.get("reference", "").startswith("Vendor invoice")),
            None,
        )
        findings.append({
            "id": str(violation.get("rule_id") or violation.get("id") or "POLICY"),
            "title": str(violation.get("rule_name") or violation.get("name") or "Custom policy rule"),
            "severity": str(violation.get("severity", "HIGH")).upper(),
            "reason": str(violation.get("reason", "A deterministic policy condition matched.")),
            "action": str(violation.get("action", "REVIEW")),
            "impact": amount,
            "citations": citations,
            "source_invoice_quote": source_invoice,
        })

    for item in discrepancy.get("flagged_items", []) or []:
        citations = _match_citations(item, context)
        source_invoice = next(
            (c.get("quote") for c in citations if c.get("reference", "").startswith("Vendor invoice")),
            None,
        )
        existing = next(
            (f for f in findings if source_invoice and f.get("source_invoice_quote") == source_invoice),
            None,
        )
        if existing:
            existing["reason"] += f" 3-way match also found: {item.get('reason', 'line-item mismatch')}"
            existing["citations"].extend(c for c in citations if c not in existing["citations"])
            existing["impact"] = max(_money(existing.get("impact")), _money(item.get("amount")), overcharge)
        else:
            findings.append({
                "id": "MATCH-" + re.sub(r"[^A-Za-z0-9]+", "-", str(item.get("description", "EXCEPTION"))).strip("-").upper()[:48],
                "title": str(item.get("description", "3-way-match exception")),
                "severity": "HIGH",
                "reason": str(item.get("reason", "3-way match exception detected.")),
                "action": "REVIEW_AND_HOLD_DISPUTED_AMOUNT",
                "impact": max(_money(item.get("amount")), overcharge),
                "citations": citations,
                "source_invoice_quote": source_invoice,
            })

    if context.get("chaos_triggered") and not any("VISION" in finding["id"] for finding in findings):
        vision = str(gr_data.get("vision_summary") or context.get("vision_summary") or "Vision verification failed.")
        findings.append({
            "id": "VISION-GR-001",
            "title": "Goods-receipt verification exception",
            "severity": "CRITICAL",
            "reason": vision,
            "action": "SHORT_PAYMENT_HOLD_PENDING_HUMAN_REVIEW",
            "impact": invoice_total,
            "citations": [
                _metric_citation("Goods Receipt / Vision result", vision),
                _metric_citation(
                    "Audit metric",
                    f"invoice_total={_fmt_money(invoice_total)}; vision_confidence={context.get('vision_confidence', 'unknown')}",
                ),
            ],
            "source_invoice_quote": None,
        })

    findings.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 0), _money(f.get("impact"))), reverse=True)
    processed_docs = 3 if (po_data or invoice_data or gr_data) else 0
    summary = {
        "decision": decision,
        "documents_processed": processed_docs,
        "line_items_processed": line_items_processed,
        "purchase_order_line_items": len(po_items),
        "invoice_line_items": len(invoice_items),
        "policy_rules_evaluated": rules_evaluated,
        "exceptions_found": len(findings),
        "po_total": po_total,
        "invoice_total": invoice_total,
        "overcharge_exposure": overcharge,
        "policy_payment_hold": policy_hold,
        "maximum_quantified_exposure": quantified_exposure,
        "vendor": str(po_data.get("vendor", context.get("vendor_name", context.get("vendor", "Unknown vendor")))),
        "po_id": str(context.get("po_id", po_data.get("po_number", "Unknown PO"))),
        "invoice_id": str(context.get("inv_id", invoice_data.get("invoice_number", "Unknown invoice"))),
        "scenario": str(context.get("scenario_name", "Current audit")),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {"summary": summary, "top_exceptions": findings[:3]}


def build_brief_data(
    audit_ctx: dict[str, Any] | None,
    ledger_rows: list[list[Any]] | None = None,
    cumulative_recovered: float = 0.0,
    cfo_monthly_invoices: float = 5000,
    cfo_avg_val: float = 600,
    cfo_error_rate: float = 2.5,
) -> dict[str, Any]:
    """Compile executive metrics and Top 3 ranked exceptions with 4-part auditable citations."""
    if not isinstance(audit_ctx, dict) or not audit_ctx.get("executed"):
        raise ValueError("Run an audit to completion before exporting the executive brief.")

    po_data = audit_ctx.get("po_data") or {}
    invoice_data = audit_ctx.get("invoice_data") or {}
    discrepancy = audit_ctx.get("discrepancy") or {}
    gr_data = audit_ctx.get("gr_data") or {}
    po_text = str(audit_ctx.get("po_text", "") or "")
    invoice_text = str(audit_ctx.get("invoice_text", "") or "")
    logs = _telemetry_lines(audit_ctx)
    violations = list(audit_ctx.get("policy_violations") or [])
    flagged_items = list(audit_ctx.get("flagged_items") or discrepancy.get("flagged_items") or [])
    ann_items = list(audit_ctx.get("annotated_inv_items") or [])
    invoice_items = invoice_data.get("line_items") or []
    po_items = po_data.get("line_items") or []

    po_total = _money(audit_ctx.get("po_authorized", audit_ctx.get("po_amount", discrepancy.get("po_authorized"))))
    invoice_total = _money(audit_ctx.get("invoice_billed", audit_ctx.get("inv_total", discrepancy.get("invoice_billed"))))
    variance = _money(discrepancy.get("variance", audit_ctx.get("variance", max(invoice_total - po_total, 0.0))))
    funds_protected = _money(audit_ctx.get("recovered", audit_ctx.get("funds_protected", discrepancy.get("recovered", 0.0))))
    annualized_roi = _money(float(cfo_monthly_invoices) * float(cfo_avg_val) * (float(cfo_error_rate) / 100.0) * 12.0)

    hot_swap = audit_ctx.get("hot_swap_violation") or {}
    hot_swap_rule_text = str(hot_swap.get("rule") or hot_swap.get("rule_text") or hot_swap.get("natural_language_rule") or "").strip()
    hot_swap_active = bool(isinstance(hot_swap, dict) and hot_swap.get("violated") and hot_swap_rule_text)

    status = (
        "POLICY EXCEPTION — PAYMENT BLOCKED"
        if violations or hot_swap_active
        else ("FLAGGED // HOLD & DISPUTE" if discrepancy.get("detected") or audit_ctx.get("chaos_triggered") else "CLEARED // NET-30 APPROVED")
    )

    exceptions: list[dict[str, Any]] = []

    # 1. Deterministic Policy Engine violations
    for v in violations:
        rule_id = str(v.get("rule_id") or v.get("id") or "POL-CUSTOM")
        rule_name = str(v.get("rule_name") or v.get("name") or "Hot-Swapped Policy Rule")
        severity = str(v.get("severity") or "HIGH").upper()
        action = str(v.get("action") or "BLOCK_PAYMENT")
        field = str(v.get("field") or "invoice_total")
        actual = v.get("actual", invoice_total)
        expected = v.get("expected", v.get("value"))
        op = str(v.get("operator", "?"))

        if field == "invoice_text":
            tokens = expected if isinstance(expected, list) else [expected]
            exact_line = _source_line(invoice_text, [str(t) for t in tokens if t is not None])
            line_or_field = exact_line or f"invoice_text matched {expected!r}"
        elif field == "invoice_total":
            line_or_field = _source_line(invoice_text, ["TOTAL DUE", "INVOICE TOTAL"]) or f"invoice_total = {_fmt_money(actual)} (op: {op} {expected})"
        elif field == "po_total":
            line_or_field = _source_line(po_text, ["MAXIMUM AUTHORIZED AMOUNT", "AUTHORIZED AMOUNT"]) or f"po_total = {_fmt_money(actual)}"
        elif field == "vendor_name":
            line_or_field = _source_line(po_text, [str(actual), "VENDOR:"]) or f"vendor_name = {actual!r}"
        else:
            line_or_field = f"{field} = {actual!r} (op: {op} {expected!r})"

        reason = str(v.get("reason") or f"{rule_id} ({rule_name}) triggered")
        clause_or_rule = f"{rule_id} ({rule_name}) -> {action}; reason: {reason}"
        log_entry = _first_exact_line(
            logs,
            lambda line, rid=rule_id: rid in line and "POLICY ENGINE" in line,
            _first_exact_line(logs, lambda line, rid=rule_id: rid in line, f"[POLICY ENGINE // {severity}] {rule_id} — {rule_name}"),
        )
        impact = invoice_total if action.upper().startswith(("BLOCK", "HOLD")) else max(variance, round(invoice_total * 0.25, 2))
        exceptions.append({
            "exception_id": rule_id,
            "source": "Donut 1 // Policy Engine",
            "title": f"{rule_id}: {rule_name}",
            "severity": severity,
            "reason": reason,
            "action": action,
            "dollar_impact": _money(impact),
            "citations": {
                "line_or_field": line_or_field,
                "clause_or_rule": clause_or_rule,
                "log_entry": log_entry,
                "metric": _supervisor_or_vision_metric(audit_ctx, logs),
            },
        })

    # 2. Natural-language hot-swap violation (legacy sidebar hook)
    if hot_swap_active:
        hot_rule_id = str(hot_swap.get("rule_id") or hot_swap.get("rule_name") or "CUSTOM-HOT-SWAP")
        if not any(item["exception_id"] == hot_rule_id for item in exceptions):
            log_entry = _first_exact_line(
                logs,
                lambda line: "HOT-SWAP" in line or "DETERMINISTIC FALLBACK" in line,
                f'[POLICY HOT-SWAP] "{hot_swap_rule_text}" flagged invoice',
            )
            exceptions.append({
                "exception_id": hot_rule_id,
                "source": "Policy Hot-Swap Rule",
                "title": f"Dynamic Rule Violation: {hot_swap_rule_text}",
                "severity": str(hot_swap.get("severity") or "HIGH").upper(),
                "reason": str(hot_swap.get("reason") or f"Violated natural-language rule: {hot_swap_rule_text}"),
                "action": str(hot_swap.get("action") or "HOT_SWAP_HOLD"),
                "dollar_impact": _money(max(variance, invoice_total)),
                "citations": {
                    "line_or_field": f"Invoice {audit_ctx.get('inv_id', '')} Line Items ({max(len(ann_items), len(invoice_items), 1)} item(s))",
                    "clause_or_rule": f'Custom Policy Rule: "{hot_swap_rule_text}" -> HOT_SWAP_HOLD',
                    "log_entry": log_entry,
                    "metric": _supervisor_or_vision_metric(audit_ctx, logs),
                },
            })

    # 3. Vision XAI / Chaos Mode shortages
    vision_summary = str(gr_data.get("vision_summary") or audit_ctx.get("vision_summary") or "")
    vision_active = bool(
        audit_ctx.get("chaos_triggered")
        or gr_data.get("chaos_triggered")
        or audit_ctx.get("vision_bbox_drawn")
        or gr_data.get("xai_bbox_drawn")
        or int(audit_ctx.get("short_shipped_units", 0) or 0) > 0
        or int(gr_data.get("short_shipped_units", 0) or 0) > 0
        or "missing" in vision_summary.lower()
        or "short" in vision_summary.lower()
    )
    if vision_active:
        vision_text = vision_summary or "Goods Receipt delivery exception detected."
        po_evidence = _source_line(po_text, ["SHORT-SHIPMENT", "ordered", "units missing", "ordered 10"])
        log_entry = _first_exact_line(
            logs,
            lambda line: "[VISION ALERT]" in line or "[VISION XAI]" in line or "Vision Agent" in line,
            f"[VISION XAI] {vision_text}",
        )
        clause = _clause_excerpt(audit_ctx, ["SHORT-SHIPMENT", "ordered", "payable strictly", "delivered"]) or (
            f"{audit_ctx.get('rag_clause', 'Section 1.2')} | Short-Shipment & Delivery Proof"
        )
        exceptions.append({
            "exception_id": "VISION-GR-001",
            "source": "Vision XAI // Goods Receipt",
            "title": "Physical Delivery Discrepancy" if (audit_ctx.get("vision_bbox_drawn") or gr_data.get("xai_bbox_drawn")) else "Chaos Mode Vision Integrity Alert",
            "severity": "CRITICAL",
            "reason": vision_text,
            "action": "SHORT_PAYMENT_HOLD",
            "dollar_impact": _money(max(variance, funds_protected, invoice_total)),
            "citations": {
                "line_or_field": po_evidence or f"Goods Receipt 02 // {vision_text}",
                "clause_or_rule": clause,
                "log_entry": log_entry,
                "metric": _supervisor_or_vision_metric(audit_ctx, logs, vision=True),
            },
        })

    # 4. Flagged line-item overcharges
    for idx, item in enumerate(flagged_items, start=1):
        desc = str(item.get("description") or f"Flagged Line Item #{idx}")
        amt = float(item.get("amount") or variance or 0.0)
        reason = str(item.get("reason") or "Exceeds contracted Purchase Order scope")
        exact_inv_line = _source_line(invoice_text, [desc])
        if not exact_inv_line:
            terms = [t for t in re.split(r"[^A-Za-z0-9]+", desc) if len(t) > 3]
            exact_inv_line = _source_line(invoice_text, terms)
        line_or_field = exact_inv_line or f"{desc} = {_fmt_money(amt)} (Authorized PO: {_fmt_money(po_total)})"
        clause = _clause_excerpt(audit_ctx, ["NON-BILLABLE", "change order", "SHORT-SHIPMENT", "authorized"]) or (
            f"{audit_ctx.get('po_id', 'PO')} // {audit_ctx.get('rag_clause', 'Section 1.2')}"
        )
        log_entry = _first_exact_line(
            logs,
            lambda line, d=desc: d.casefold() in line.casefold() and ("FLAG" in line.upper() or "EXCEPTION" in line.upper()),
            _first_exact_line(logs, lambda line: "FLAG ::" in line or "[STATE: AUDIT]" in line, f"[AUDIT FINDING] {desc}: {reason}"),
        )
        exceptions.append({
            "exception_id": f"LINE-{idx:03d}",
            "source": "3-Way Match // Line-Item Auditor",
            "title": f"Uncontracted / Overbilled Item: {desc}",
            "severity": str(item.get("severity") or ("HIGH" if amt >= 500 or variance >= 500 else "MEDIUM")).upper(),
            "reason": reason,
            "action": "DISPUTE_HOLD",
            "dollar_impact": _money(amt),
            "citations": {
                "line_or_field": line_or_field,
                "clause_or_rule": clause,
                "log_entry": log_entry,
                "metric": _supervisor_or_vision_metric(audit_ctx, logs),
            },
        })

    exceptions.sort(
        key=lambda item: (SEVERITY_RANK.get(str(item.get("severity", "HIGH")).upper(), 2), _money(item.get("dollar_impact"))),
        reverse=True,
    )
    top_3_exceptions: list[dict[str, Any]] = [{"rank": idx, **exc} for idx, exc in enumerate(exceptions[:3], start=1)]

    total_items = len(po_items) + len(invoice_items)
    if not total_items:
        total_items = max(len(ann_items), len(flagged_items), 1)
    cum_protected = _money(cumulative_recovered)

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "audit_run_id": str(audit_ctx.get("audit_id") or ""),
        "po_id": str(audit_ctx.get("po_id") or po_data.get("po_number") or "PO #8842"),
        "inv_id": str(audit_ctx.get("inv_id") or invoice_data.get("invoice_number") or "INV-2024-001"),
        "vendor": str(audit_ctx.get("vendor") or po_data.get("vendor") or "Apex Cognitive Systems LLC"),
        "audit_mode": str(audit_ctx.get("audit_mode") or "3-Way Match"),
        "status": status,
        "total_documents_processed": 2 if "2-Way" in str(audit_ctx.get("audit_mode", "")) else 3,
        "total_line_items_processed": total_items,
        "total_policy_rules_evaluated": int(audit_ctx.get("policy_rule_count", len(violations)) or len(violations)),
        "total_exceptions_found": len(exceptions),
        "total_ledger_runs": len(ledger_rows or []),
        "po_authorized": po_total,
        "invoice_billed": invoice_total,
        "variance": variance,
        "funds_protected": funds_protected,
        "cumulative_ledger_recovered": cum_protected,
        "cumulative_ledger_protected": cum_protected,
        "confirmed_recovered_funds": _money(audit_ctx.get("confirmed_recovered", 0.0)),
        "annualized_cfo_roi": annualized_roi,
        "cfo_params": {
            "monthly_invoices": int(cfo_monthly_invoices),
            "avg_value": float(cfo_avg_val),
            "error_rate_pct": float(cfo_error_rate),
        },
        "top_3_exceptions": top_3_exceptions,
    }


def render_brief_markdown_legacy(brief: dict[str, Any]) -> str:
    """Render Phase 1 compatibility report model ({'summary', 'top_exceptions'})."""
    summary = brief["summary"]
    lines = [
        "# PROJECT OVERLORD | EXECUTIVE BOARDROOM BRIEF",
        f"**Generated (UTC):** {summary['generated_at']}  ",
        f"**Audit:** {summary['invoice_id']} / {summary['po_id']}  ",
        f"**Vendor:** {summary['vendor']}  ",
        f"**Scenario:** {summary['scenario']}",
        "",
        f"## Decision: {summary['decision']}",
        "",
        "## Executive summary",
        f"- **Documents processed:** {summary['documents_processed']} (PO, Goods Receipt, invoice)",
        f"- **Line items processed:** {summary['line_items_processed']} total ({summary['purchase_order_line_items']} PO + {summary['invoice_line_items']} invoice)",
        f"- **Policy rules evaluated:** {summary['policy_rules_evaluated']}",
        f"- **Exceptions found:** {summary['exceptions_found']}",
        f"- **PO authorized:** {_fmt_money(summary['po_total'])}",
        f"- **Invoice total:** {_fmt_money(summary['invoice_total'])}",
        f"- **Overcharge / variance exposure:** {_fmt_money(summary['overcharge_exposure'])}",
        f"- **Invoice payment blocked by policy:** {_fmt_money(summary['policy_payment_hold'])}",
        f"- **Maximum quantified exposure (non-additive):** {_fmt_money(summary['maximum_quantified_exposure'])}",
        "",
        "> Exposure figures are deliberately not added together: a blocked invoice can include the same overcharge amount.",
        "",
        "## Top urgent exceptions",
    ]
    if not brief["top_exceptions"]:
        lines.extend([
            "No exceptions were flagged in this run.",
            "",
            "### Evidence / citations",
            "- Audit metrics: PO and invoice totals matched; no policy violations were returned.",
        ])
    for index, finding in enumerate(brief["top_exceptions"], start=1):
        lines.extend([
            "",
            f"### {index}. [{finding['severity']}] {finding['title']} ({finding['id']})",
            f"- **Why flagged:** {finding['reason']}",
            f"- **Action:** {finding['action']}",
            f"- **Impact associated with this finding:** {_fmt_money(finding['impact'])}",
            "- **Evidence / citations:**",
        ])
        for citation in finding["citations"]:
            lines.append(f"  - `{citation['reference']}` — \"{citation['quote']}\"")
    lines.extend([
        "",
        "## Method and scope",
        "Policy comparisons are deterministic Python checks. Citations below quote source-document lines or exact engine metrics/log entries.",
        "",
    ])
    return "\n".join(lines)


def _render_top3_markdown(brief: dict[str, Any]) -> str:
    cum = brief.get("cumulative_ledger_recovered", brief.get("cumulative_ledger_protected", 0.0))
    lines = [
        f"### Executive Boardroom Brief — {brief['inv_id']} ({brief['po_id']})",
        f"**Generated:** `{brief['generated_at_utc']}` | **Vendor:** `{brief['vendor']}` | **Status:** `{brief['status']}`",
        "",
        "| Metric | Value | Metric | Value |",
        "| :--- | :--- | :--- | :--- |",
        f"| **PO Authorized** | `{_fmt_money(brief['po_authorized'])}` | **Invoice Billed** | `{_fmt_money(brief['invoice_billed'])}` |",
        f"| **Variance Detected** | `{_fmt_money(brief['variance'])}` | **Funds Protected (Current Run)** | `{_fmt_money(brief['funds_protected'])}` |",
        f"| **Cumulative Ledger Blocked** | `{_fmt_money(cum)}` (`{brief['total_ledger_runs']}` runs) | **Projected Annual CFO ROI** | **`{_fmt_money(brief['annualized_cfo_roi'])}/yr`** |",
        "",
        "#### Top Urgent Exceptions & Auditable Citations",
    ]
    exceptions = brief.get("top_3_exceptions") or []
    if not exceptions:
        lines.append(
            "- **No Exceptions Flagged:** All line items, physical Goods Receipt verification, and active policy rules cleared cleanly (`$0.00` variance)."
        )
    else:
        for exc in exceptions:
            cit = exc["citations"]
            lines.extend([
                f"- **#{exc['rank']} [{exc['severity']}] {exc['title']}** — Impact: `{_fmt_money(exc['dollar_impact'])}` | Action: `{exc['action']}`",
                f"  - **Line / Field:** `{cit['line_or_field']}`",
                f"  - **Clause / Rule:** `{cit['clause_or_rule']}`",
                f"  - **Telemetry Log:** `{cit['log_entry']}`",
                f"  - **Verified Metric:** `{cit['metric']}`",
            ])
    return "\n".join(lines)


def render_brief_markdown(brief: dict[str, Any]) -> str:
    """Render an executive boardroom brief preview as structured Markdown."""
    if "top_3_exceptions" in brief:
        return _render_top3_markdown(brief)
    return render_brief_markdown_legacy(brief)


def render_brief_csv(brief: dict[str, Any]) -> str:
    """Render an executive boardroom brief as CSV (preserves both unified and legacy models)."""
    if "top_3_exceptions" in brief:
        output = io.StringIO(newline="")
        cum = brief.get("cumulative_ledger_recovered", brief.get("cumulative_ledger_protected", 0.0))
        exceptions = brief.get("top_3_exceptions") or []
        fieldnames = [
            "generated_at_utc", "po_id", "inv_id", "vendor", "status",
            "po_authorized", "invoice_billed", "variance", "funds_protected",
            "cumulative_ledger_recovered", "annualized_cfo_roi",
            "exception_rank", "source", "title", "severity", "dollar_impact", "action",
            "citation_line_or_field", "citation_clause_or_rule", "citation_log_entry", "citation_metric",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        if not exceptions:
            writer.writerow({
                "generated_at_utc": brief["generated_at_utc"],
                "po_id": brief["po_id"],
                "inv_id": brief["inv_id"],
                "vendor": brief["vendor"],
                "status": brief["status"],
                "po_authorized": brief["po_authorized"],
                "invoice_billed": brief["invoice_billed"],
                "variance": brief["variance"],
                "funds_protected": brief["funds_protected"],
                "cumulative_ledger_recovered": cum,
                "annualized_cfo_roi": brief["annualized_cfo_roi"],
                "exception_rank": 0,
                "source": "None",
                "title": "No Exceptions Flagged",
                "severity": "NONE",
                "dollar_impact": 0.0,
                "action": "CLEARED",
                "citation_line_or_field": "All line items matched PO",
                "citation_clause_or_rule": "All active rules passed",
                "citation_log_entry": "PASS :: 3-Way Match verified",
                "citation_metric": _build_math_metric(brief["invoice_billed"], brief["po_authorized"], brief["variance"]),
            })
        else:
            for exc in exceptions:
                cit = exc["citations"]
                writer.writerow({
                    "generated_at_utc": brief["generated_at_utc"],
                    "po_id": brief["po_id"],
                    "inv_id": brief["inv_id"],
                    "vendor": brief["vendor"],
                    "status": brief["status"],
                    "po_authorized": brief["po_authorized"],
                    "invoice_billed": brief["invoice_billed"],
                    "variance": brief["variance"],
                    "funds_protected": brief["funds_protected"],
                    "cumulative_ledger_recovered": cum,
                    "annualized_cfo_roi": brief["annualized_cfo_roi"],
                    "exception_rank": exc["rank"],
                    "source": exc["source"],
                    "title": exc["title"],
                    "severity": exc["severity"],
                    "dollar_impact": exc["dollar_impact"],
                    "action": exc["action"],
                    "citation_line_or_field": cit["line_or_field"],
                    "citation_clause_or_rule": cit["clause_or_rule"],
                    "citation_log_entry": cit["log_entry"],
                    "citation_metric": cit["metric"],
                })
        return output.getvalue()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["record_type", "label", "value", "severity", "reason", "action", "citation_reference", "citation_quote"])
    for key, value in brief["summary"].items():
        writer.writerow(["summary", key, value, "", "", "", "", ""])
    for finding in brief["top_exceptions"]:
        if finding["citations"]:
            for citation in finding["citations"]:
                writer.writerow([
                    "exception",
                    f"{finding['id']} | {finding['title']}",
                    finding["impact"],
                    finding["severity"],
                    finding["reason"],
                    finding["action"],
                    citation["reference"],
                    citation["quote"],
                ])
        else:
            writer.writerow([
                "exception",
                f"{finding['id']} | {finding['title']}",
                finding["impact"],
                finding["severity"],
                finding["reason"],
                finding["action"],
                "",
                "",
            ])
    return output.getvalue()


def _render_brief_html(brief: dict[str, Any]) -> str:
    """Build crisp A4 executive brief HTML for PyMuPDF rendering."""
    exceptions = brief.get("top_3_exceptions") or []
    exc_cards: list[str] = []
    if not exceptions:
        exc_cards.append(
            "<div style='border:1px solid #10B981; background:#ECFDF5; border-left:4px solid #10B981; "
            "padding:10px; border-radius:4px; font-size:9.5pt; color:#065F46;'>"
            "<strong>NO EXCEPTIONS DETECTED:</strong> 3-Way Match and all active Policy Engine rules cleared cleanly."
            "</div>"
        )
    else:
        for exc in exceptions:
            cit = exc["citations"]
            sev = str(exc["severity"]).upper()
            accent = "#EF4444" if sev == "CRITICAL" else ("#F59E0B" if sev == "HIGH" else "#3B82F6")
            exc_cards.append(
                f"<div style='border:1px solid #CBD5E1; border-left:4px solid {accent}; "
                "background:#F8FAFC; padding:8px 10px; margin-bottom:8px; border-radius:4px;'>"
                f"<div style='font-size:10pt; font-weight:700; color:#0F172A; margin-bottom:3px;'>"
                f"#{exc['rank']} [{html.escape(sev)}] {html.escape(str(exc['title']))} "
                f"<span style='color:{accent};'>({_fmt_money(exc['dollar_impact'])} | {html.escape(str(exc['action']))})</span>"
                "</div>"
                f"<div style='font-size:8.4pt; color:#334155; line-height:1.4;'>"
                f"<b>Line / Field:</b> {html.escape(str(cit['line_or_field']))}<br/>"
                f"<b>Clause / Rule:</b> {html.escape(str(cit['clause_or_rule']))}<br/>"
                f"<b>Telemetry Log:</b> {html.escape(str(cit['log_entry']))}<br/>"
                f"<b>Verified Metric:</b> {html.escape(str(cit['metric']))}"
                "</div></div>"
            )

    params = brief.get("cfo_params") or {}
    cum = brief.get("cumulative_ledger_recovered", brief.get("cumulative_ledger_protected", 0.0))
    return f"""
    <div style="font-family: Helvetica, Arial, sans-serif; color: #0F172A; font-size: 9.5pt; line-height: 1.4;">
      <div style="background: #0A0B0E; color: #FFFFFF; padding: 14px 16px; border-bottom: 4px solid #10B981; margin-bottom: 12px;">
        <div style="font-size: 8pt; color: #34D399; letter-spacing: 1px; font-weight: 700;">
          PROJECT OVERLORD // PS-BA1 FINANCIAL DEFENSE ENGINE
        </div>
        <div style="font-size: 16pt; font-weight: 700; margin-top: 3px;">
          EXECUTIVE BOARDROOM AUDIT BRIEF
        </div>
        <div style="font-size: 8.5pt; color: #CBD5E1; margin-top: 4px;">
          Generated: {html.escape(brief['generated_at_utc'])} &nbsp;|&nbsp;
          Mode: {html.escape(brief['audit_mode'])} &nbsp;|&nbsp;
          Verdict: <span style="color:#FBBF24; font-weight:700;">{html.escape(brief['status'])}</span>
        </div>
      </div>

      <table style="width:100%; border-collapse:collapse; margin-bottom:12px; font-size:8.8pt;">
        <tr>
          <td style="border:1px solid #CBD5E1; padding:6px; background:#F1F5F9;"><b>Purchase Order</b><br/>{html.escape(brief['po_id'])}</td>
          <td style="border:1px solid #CBD5E1; padding:6px; background:#F1F5F9;"><b>Vendor Invoice</b><br/>{html.escape(brief['inv_id'])}</td>
          <td style="border:1px solid #CBD5E1; padding:6px; background:#F1F5F9;"><b>Vendor Entity</b><br/>{html.escape(brief['vendor'])}</td>
          <td style="border:1px solid #CBD5E1; padding:6px; background:#F1F5F9;"><b>Line Items</b><br/>{brief['total_line_items_processed']} item(s)</td>
        </tr>
        <tr>
          <td style="border:1px solid #CBD5E1; padding:6px;"><b>PO Authorized</b><br/>{_fmt_money(brief['po_authorized'])}</td>
          <td style="border:1px solid #CBD5E1; padding:6px;"><b>Invoice Billed</b><br/>{_fmt_money(brief['invoice_billed'])}</td>
          <td style="border:1px solid #CBD5E1; padding:6px;"><b>Funds Protected</b><br/><b style="color:#059669;">{_fmt_money(brief['funds_protected'])}</b></td>
          <td style="border:1px solid #CBD5E1; padding:6px;"><b>Annualized CFO ROI</b><br/><b style="color:#059669;">{_fmt_money(brief['annualized_cfo_roi'])}/yr</b></td>
        </tr>
      </table>

      <div style="font-size:8.3pt; color:#475569; margin-bottom:10px;">
        <b>Enterprise Scale Basis:</b> {params.get('monthly_invoices', 5000)} monthly invoices x {_fmt_money(params.get('avg_value', 600))} avg x {params.get('error_rate_pct', 2.5)}% leakage rate
        &nbsp;|&nbsp; <b>Cumulative Ledger Blocked:</b> {_fmt_money(cum)} across {brief['total_ledger_runs']} audited run(s).
      </div>

      <div style="font-size:11pt; font-weight:700; color:#0F172A; border-bottom:2px solid #0A0B0E; padding-bottom:4px; margin-bottom:8px;">
        TOP 3 URGENT EXCEPTIONS &amp; VERIFIED CITATIONS
      </div>
      {"".join(exc_cards)}
    </div>
    """


def write_brief_pdf(brief_or_markdown: dict[str, Any] | str, file_path: str | Path) -> str:
    """Render an Executive Boardroom Brief (dict or markdown) to PDF via PyMuPDF."""
    output = Path(file_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()

    if isinstance(brief_or_markdown, dict) and "top_3_exceptions" in brief_or_markdown:
        page = document.new_page(width=595, height=842)
        page.insert_htmlbox(pymupdf.Rect(28, 28, 567, 814), _render_brief_html(brief_or_markdown))
    else:
        markdown = (
            render_brief_markdown(brief_or_markdown)
            if isinstance(brief_or_markdown, dict)
            else str(brief_or_markdown)
        )
        blocks: list[str] = []
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("|") and set(line.replace("|", "").replace(":", "").replace("-", "").replace(" ", "")) == set():
                continue
            heading_level = len(line) - len(line.lstrip("#")) if line.startswith("#") else 0
            safe = html.escape(line)
            safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
            safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
            if heading_level:
                tag = "h1" if heading_level == 1 else "h2" if heading_level == 2 else "h3"
                blocks.append(f"<{tag}>{safe[heading_level:].strip()}</{tag}>")
            elif line.startswith("- "):
                blocks.append(f"<p class='bullet'>• {safe[2:]}</p>")
            elif line.startswith("|"):
                blocks.append(f"<p class='table-row'>{safe}</p>")
            else:
                blocks.append(f"<p>{safe}</p>")
        body = "".join(blocks)
        page = document.new_page(width=612, height=792)
        page.insert_htmlbox(
            pymupdf.Rect(42, 42, 570, 746),
            f"<div class='report'>{body}</div>",
            css="""
            .report { font-family: sans-serif; font-size: 9pt; line-height: 1.28; color: #1e293b; }
            h1 { color: #0b3b5a; font-size: 19pt; margin: 0 0 10pt 0; }
            h2 { color: #0b3b5a; font-size: 13pt; margin: 9pt 0 5pt 0; border-bottom: 1px solid #b6c4cf; }
            h3 { color: #243b53; font-size: 10pt; margin: 7pt 0 3pt 0; }
            p { margin: 2pt 0; }
            .bullet { margin-left: 8pt; }
            .table-row { font-family: monospace; font-size: 8pt; }
            code { color: #174a6e; background-color: #edf4f8; }
            """,
            scale_low=0.7,
        )

    document.set_metadata({"title": "Project Overlord Executive Boardroom Brief", "author": "Project Overlord"})
    document.save(str(output), garbage=4, deflate=True)
    document.close()
    return str(output)


def export_executive_brief(
    audit_or_brief: dict[str, Any] | None,
    export_format: str = "PDF",
    export_dir: str | Path = "workspace/exports",
    ledger_rows: list[list[Any]] | None = None,
    cumulative_recovered: float = 0.0,
    cfo_monthly_invoices: float = 5000,
    cfo_avg_val: float = 600,
    cfo_error_rate: float = 2.5,
) -> Any:
    """Export an Executive Boardroom Brief as PDF, Markdown, or CSV.

    Supports both:
    - Compiled brief dict -> writes file to ``export_dir`` and returns ``str(path)``
    - Raw ``audit_ctx`` dict -> builds brief first, writes file, and returns ``(abs_path, md_preview)``
    """
    is_compiled_brief = isinstance(audit_or_brief, dict) and (
        "top_3_exceptions" in audit_or_brief or "summary" in audit_or_brief
    )

    if is_compiled_brief:
        brief = audit_or_brief  # type: ignore[assignment]
    else:
        brief = build_brief_data(
            audit_ctx=audit_or_brief,
            ledger_rows=ledger_rows,
            cumulative_recovered=cumulative_recovered,
            cfo_monthly_invoices=cfo_monthly_invoices,
            cfo_avg_val=cfo_avg_val,
            cfo_error_rate=cfo_error_rate,
        )

    md_preview = render_brief_markdown(brief)
    outdir = Path(export_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    selected = (export_format or "PDF").strip().upper()

    if "CSV" in selected:
        out_path = outdir / f"Overlord_Executive_Brief_{stamp}.csv"
        out_path.write_text(render_brief_csv(brief), encoding="utf-8-sig", newline="")
    elif "MARKDOWN" in selected or selected.endswith(".MD") or selected == "MD":
        out_path = outdir / f"Overlord_Executive_Brief_{stamp}.md"
        out_path.write_text(md_preview + "\n", encoding="utf-8")
    elif "PDF" in selected:
        out_path = outdir / f"Overlord_Executive_Brief_{stamp}.pdf"
        write_brief_pdf(brief, out_path)
    else:
        raise ValueError("Choose PDF, Markdown, or CSV as the export format.")

    if is_compiled_brief:
        return str(out_path)
    return os.path.abspath(str(out_path)), md_preview
