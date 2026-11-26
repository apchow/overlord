"""Project Overlord MCP server (stdio transport).

Exposes safe, typed tools for MCP-compatible clients. The server reuses the
same SQL database and deterministic policy engine as the Gradio application.
Run: ``python mcp_server.py``. Keep it on stdio; do not expose it publicly
without authentication and authorization.
"""
from __future__ import annotations

import json
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import overlord_db
from improvement_agent import analyze_feedback
from policy_engine import add_policy_rule, evaluate_policies, load_policies, parse_policy_config, save_policies

load_dotenv()

mcp = FastMCP(
    "Project Overlord Financial Defense",
    instructions=(
        "Use these tools to inspect Overlord audit history, evaluate deterministic policies, "
        "manage policy revisions, and verify the hash-chained compliance ledger. "
        "Policy creation changes the active financial controls and should only be performed with user approval."
    ),
)


@mcp.tool()
def get_storage_status() -> dict[str, Any]:
    """Return DB engine and record counts, plus compliance-chain verification status."""
    return {"database": overlord_db.database_health(), "ledger_integrity": overlord_db.verify_compliance_ledger()}


@mcp.tool()
def list_active_policies() -> dict[str, Any]:
    """Read the active, hot-reloaded deterministic policy config."""
    return load_policies()


@mcp.tool()
def evaluate_policy_context(context_json: str) -> list[dict[str, Any]]:
    """Evaluate active rules against JSON context fields; performs no LLM calls."""
    try:
        context = json.loads(context_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"context_json must be valid JSON: {exc}") from exc
    if not isinstance(context, dict):
        raise ValueError("context_json must encode a JSON object.")
    return evaluate_policies(context)


@mcp.tool()
def add_or_replace_policy_config(config_json: str) -> dict[str, Any]:
    """Validate and atomically activate a complete JSON policy config; creates a DB revision."""
    config = parse_policy_config(config_json, "mcp-config.json")
    saved = save_policies(config, source="mcp")
    return {"active_config": saved, "database_status": overlord_db.database_health()}


@mcp.tool()
def create_policy_rule(rule_json: str) -> dict[str, Any]:
    """Validate, add, and activate one JSON rule, preserving the other active rules."""
    try:
        rule = json.loads(rule_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"rule_json must be valid JSON: {exc}") from exc
    if not isinstance(rule, dict):
        raise ValueError("rule_json must encode a JSON object.")
    active = add_policy_rule(rule)
    return {"active_config": active, "database_status": overlord_db.database_health()}


@mcp.tool()
def get_recent_audits(limit: int = 10) -> list[dict[str, Any]]:
    """Return the latest persisted audit summaries (maximum 100)."""
    return overlord_db.list_audits(limit)


@mcp.tool()
def get_audit_details(audit_id: str) -> dict[str, Any]:
    """Fetch the complete persisted audit record, including triggered policy details."""
    record = overlord_db.get_audit(audit_id)
    if record is None:
        raise ValueError(f"No audit record found for audit_id {audit_id!r}.")
    return record


@mcp.tool()
def list_policy_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return historical policy revisions with hashes and their source."""
    return overlord_db.list_policy_revisions(limit)


@mcp.tool()
def submit_audit_feedback(audit_id: str, rule_id: str, verdict: str, comment: str = "") -> dict[str, Any]:
    """Record a human label for a persisted audit; does not change policies."""
    return overlord_db.record_audit_feedback(audit_id, rule_id, verdict, comment)


@mcp.tool()
def analyze_continuous_improvement() -> dict[str, Any]:
    """Analyze repeated human feedback and return a draft policy config requiring approval."""
    return analyze_feedback()


@mcp.tool()
def verify_compliance_ledger() -> dict[str, Any]:
    """Recompute each SHA-256 link in the database compliance chain."""
    return overlord_db.verify_compliance_ledger()


if __name__ == "__main__":
    mcp.run(transport="stdio")
