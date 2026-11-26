"""External policy engine for Project Overlord (ZeroTouch AP Auditor)."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

POLICY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policies.json")

AUDIT_CONTEXT_FIELDS: tuple[str, ...] = (
    "po_total",
    "invoice_total",
    "variance",
    "tax_pct",
    "short_shipped_units",
    "invoice_text",
    "vendor_name",
)

SUPPORTED_OPERATORS: tuple[str, ...] = (">", ">=", "<", "!=", "contains_any")

_FORMATTED_NUM_RE = re.compile(
    r"^\s*[-+]?\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?\s*$"
)


def _to_float(value: Any) -> float | None:
    """Coerce int, float, or numeric string (including currency/percent formatting) to finite float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            num = float(text)
            return num if math.isfinite(num) else None
        except ValueError:
            pass
        if _FORMATTED_NUM_RE.fullmatch(text):
            cleaned = text.replace("$", "").replace("%", "").replace(",", "").strip()
            try:
                num = float(cleaned)
                return num if math.isfinite(num) else None
            except ValueError:
                return None
    return None


def load_policies(path: str = POLICY_FILE) -> list[dict[str, Any]]:
    """Load policy rules from a JSON or YAML file, returning an empty list if missing or empty."""
    if not path or not os.path.isfile(path):
        return []

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []

    if not raw.strip():
        return []

    ext = os.path.splitext(path)[1].lower()
    data: Any = None
    try:
        if ext in (".yaml", ".yml"):
            if yaml is None:
                return []
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    return [dict(item) for item in data if isinstance(item, dict)]


def save_policies(policies: list[dict[str, Any]], path: str = POLICY_FILE) -> None:
    """Persist policy rules to disk as JSON (default) or YAML when targeting .yaml/.yml."""
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    ext = os.path.splitext(abs_path)[1].lower()
    if ext in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("PyYAML is required to save YAML policy files.")
        content = yaml.safe_dump(policies, sort_keys=False, allow_unicode=True)
    else:
        content = json.dumps(policies, indent=2, ensure_ascii=False) + "\n"

    Path(abs_path).write_text(content, encoding="utf-8")


def parse_policy_text(raw_text: str) -> tuple[list[dict[str, Any]], str]:
    """Parse raw policy text as a JSON list first, falling back to YAML if PyYAML is installed."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return [], "Policy text is empty. Provide a JSON or YAML list of policy rule objects."

    stripped = raw_text.strip()
    source_format = "JSON"
    parsed: Any = None

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as json_exc:
        if yaml is None:
            return (
                [],
                f"Failed to parse policy text as JSON ({json_exc}). "
                "PyYAML is not installed for YAML parsing.",
            )
        try:
            parsed = yaml.safe_load(stripped)
            source_format = "YAML"
        except Exception as yaml_exc:
            return [], f"Failed to parse policy text as JSON or YAML: {yaml_exc}"

    if not isinstance(parsed, list):
        return (
            [],
            f"Invalid policy format: expected a list of rule objects, got {type(parsed).__name__}.",
        )

    if not all(isinstance(item, dict) for item in parsed):
        return [], "Invalid policy format: every policy entry must be a JSON/YAML object."

    rules = [dict(item) for item in parsed]
    return rules, f"Parsed {len(rules)} policy rule(s) from {source_format}."


def _evaluate_rule(
    rule_id: str,
    rule_name: str,
    field: str,
    op: str,
    actual: Any,
    threshold: Any,
) -> tuple[bool, str]:
    """Evaluate a single policy condition against an actual audit_context value."""
    if op in (">", ">=", "<"):
        actual_num = _to_float(actual)
        threshold_num = _to_float(threshold)
        if actual_num is None or threshold_num is None:
            return False, ""
        matched = (
            (actual_num > threshold_num)
            if op == ">"
            else (actual_num >= threshold_num)
            if op == ">="
            else (actual_num < threshold_num)
        )
        if not matched:
            return False, ""
        return True, f"{rule_id} ({rule_name}): {field} ({actual}) {op} {threshold}"

    if op == "!=":
        actual_num = _to_float(actual)
        threshold_num = _to_float(threshold)
        if actual_num is not None and threshold_num is not None:
            if actual_num != threshold_num:
                return True, f"{rule_id} ({rule_name}): {field} ({actual}) != {threshold}"
            return False, ""
        if threshold is None:
            return False, ""
        if str(actual).strip().casefold() != str(threshold).strip().casefold():
            return True, f"{rule_id} ({rule_name}): {field} ({actual!r}) != {threshold!r}"
        return False, ""

    if op == "contains_any":
        haystack = str(actual).lower()
        if isinstance(threshold, (list, tuple, set)):
            candidates = list(threshold)
        elif threshold is None:
            candidates = []
        else:
            candidates = [threshold]

        matched_terms = [
            str(term).strip()
            for term in candidates
            if str(term).strip() and str(term).strip().lower() in haystack
        ]
        if not matched_terms:
            return False, ""
        terms_str = ", ".join(matched_terms)
        return True, f"{rule_id} ({rule_name}): {field} matched prohibited term(s): {terms_str}"

    return False, ""


def evaluate_policies(
    audit_context: dict[str, Any],
    policies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate active policy rules against audit_context and return triggered violations."""
    if not isinstance(audit_context, dict) or not isinstance(policies, list):
        return []

    violations: list[dict[str, Any]] = []
    for idx, rule in enumerate(policies, start=1):
        if not isinstance(rule, dict):
            continue
        if not rule.get("active", True):
            continue

        field = str(rule.get("field") or "").strip()
        op = str(rule.get("operator") or "").strip()
        if not field or op not in SUPPORTED_OPERATORS:
            continue

        if field not in audit_context or audit_context[field] is None:
            continue

        actual = audit_context[field]
        threshold = rule.get("value")
        rule_id = str(rule.get("id") or f"POL-{idx:03d}")
        rule_name = str(rule.get("name") or f"{field} {op} {threshold}")

        triggered, reason = _evaluate_rule(
            rule_id=rule_id,
            rule_name=rule_name,
            field=field,
            op=op,
            actual=actual,
            threshold=threshold,
        )
        if triggered:
            violations.append(
                {
                    "id": rule_id,
                    "name": rule_name,
                    "field": field,
                    "operator": op,
                    "value": threshold,
                    "actual": actual,
                    "severity": str(rule.get("severity") or "HIGH"),
                    "action": str(rule.get("action") or "FLAG_REVIEW"),
                    "reason": reason,
                }
            )

    return violations
