"""Deterministic, hot-reloadable policy engine for Project Overlord.

Policy documents are JSON or YAML objects with a top-level ``rules`` list
(legacy bare JSON/YAML lists of rules are also accepted and normalized). The
engine deliberately performs no LLM calls; each comparison is local and
repeatable. Updates are validated before an atomic replace of the active file.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # JSON remains usable if an installation has not installed extras.
    yaml = None  # type: ignore[assignment]

POLICY_FILE = Path(os.environ.get("OVERLORD_POLICIES_FILE", Path(__file__).with_name("policies.json")))

AUDIT_CONTEXT_FIELDS: tuple[str, ...] = (
    "po_total",
    "invoice_total",
    "variance",
    "tax_pct",
    "short_shipped_units",
    "invoice_text",
    "vendor_name",
)
SUPPORTED_FIELDS = set(AUDIT_CONTEXT_FIELDS)
SUPPORTED_OPERATORS = {">", ">=", "<", "<=", "==", "!=", "contains_any", "regex"}

_FORMATTED_NUM_RE = re.compile(
    r"^\s*[-+]?\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?\s*$"
)

DEFAULT_POLICIES: dict[str, Any] = {
    "version": 1,
    "rules": [
        {
            "rule_id": "POL-001",
            "rule_name": "No Unauthorized Setup/Onboarding Fees",
            "field": "invoice_text",
            "operator": "contains_any",
            "value": [
                "setup fee",
                "onboarding fee",
                "onboarding retainer",
                "misc surcharge",
                "weekend surcharge",
                "administrative fee",
            ],
            "severity": "CRITICAL",
            "reason": "Invoice contains a prohibited ancillary fee without a countersigned change order.",
            "action": "BLOCK_PAYMENT",
            "active": True,
        },
        {
            "rule_id": "POL-002",
            "rule_name": "Max Invoice Cap Without CFO Sign-off",
            "field": "invoice_total",
            "operator": ">",
            "value": 5000,
            "severity": "HIGH",
            "reason": "Invoice total exceeds the $5,000 automatic-approval cap.",
            "action": "FLAG_CFO_REVIEW",
            "active": True,
        },
    ],
}


class PolicyValidationError(ValueError):
    """Raised when a policy document is malformed or unsafe to evaluate."""


def _to_float(value: Any) -> float | None:
    """Coerce int, float, or formatted currency/percent string to a finite float."""
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


def _resolve_policy_path(path: str | Path | None = None) -> Path:
    if path is not None and str(path).strip():
        return Path(path)
    env_override = os.environ.get("OVERLORD_POLICIES_FILE", "").strip()
    if env_override:
        return Path(env_override)
    return Path(POLICY_FILE)


def next_policy_id(rules: list[dict[str, Any]]) -> str:
    """Return the next sequential POL-NNN identifier based on existing rules."""
    max_num = 0
    for rule in rules:
        match = re.search(r"(\d+)$", str(rule.get("rule_id") or rule.get("id") or ""))
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"POL-{max(max_num + 1, len(rules) + 1):03d}"


def _decode_document(text: str, filename: str | None = None) -> tuple[Any, str]:
    source = (text or "").strip()
    if not source:
        raise PolicyValidationError("Policy config is empty.")
    use_yaml = bool(filename and Path(filename).suffix.lower() in {".yaml", ".yml"})
    if not use_yaml:
        try:
            return json.loads(source), "JSON"
        except json.JSONDecodeError as json_exc:
            if yaml is None:
                raise PolicyValidationError(
                    f"Invalid JSON ({json_exc}). Install pyyaml to parse YAML configs."
                ) from None
    if yaml is None:
        raise PolicyValidationError("YAML support is unavailable; install pyyaml.")
    try:
        return yaml.safe_load(source), "YAML"
    except Exception as exc:
        raise PolicyValidationError(f"Invalid JSON/YAML: {exc}") from exc


def validate_policy_config(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        data = {"version": 1, "rules": data}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise PolicyValidationError("Config must be an object with a 'rules' list (or a list of rules).")

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(data["rules"], 1):
        if not isinstance(raw, dict):
            raise PolicyValidationError(f"Rule {index} must be an object.")
        rule = dict(raw)
        rule_id = str(rule.get("rule_id", rule.get("id", f"POL-{index:03d}"))).strip()
        name = str(rule.get("rule_name", rule.get("name", ""))).strip()
        field = str(rule.get("field", rule.get("target_field", ""))).strip()
        op = str(rule.get("operator", "")).strip()
        if not rule_id or rule_id in seen:
            raise PolicyValidationError(f"Rule {index} has a missing or duplicate rule_id.")
        if not name:
            raise PolicyValidationError(f"Rule {rule_id}: rule_name is required.")
        if field not in SUPPORTED_FIELDS:
            raise PolicyValidationError(f"Rule {rule_id}: unsupported field '{field}'.")
        if op not in SUPPORTED_OPERATORS:
            raise PolicyValidationError(f"Rule {rule_id}: unsupported operator '{op}'.")
        if "value" not in rule and "threshold" not in rule and "keywords" not in rule:
            raise PolicyValidationError(f"Rule {rule_id}: value/threshold/keywords is required.")
        value = rule.get("value", rule.get("threshold", rule.get("keywords")))

        if op in {">", ">=", "<", "<=", "==", "!="}:
            if field in {"invoice_text", "vendor_name"}:
                if op not in {"==", "!="}:
                    raise PolicyValidationError(
                        f"Rule {rule_id}: text fields support only == or != among comparison operators."
                    )
                if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                    raise PolicyValidationError(f"Rule {rule_id}: text equality requires a string value.")
                value = str(value)
            else:
                parsed_num = _to_float(value)
                if parsed_num is None:
                    raise PolicyValidationError(f"Rule {rule_id}: numeric operator requires a finite number.")
                value = int(parsed_num) if parsed_num.is_integer() else parsed_num
        elif op == "contains_any":
            if isinstance(value, str):
                value = [word.strip() for word in value.split(",") if word.strip()]
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in value)
            ):
                raise PolicyValidationError(
                    f"Rule {rule_id}: contains_any requires a non-empty list or comma-separated string."
                )
            value = [str(x).strip() for x in value if str(x).strip()]
            if not value:
                raise PolicyValidationError(f"Rule {rule_id}: contains_any cannot be empty.")
        else:
            if not isinstance(value, str) or not value:
                raise PolicyValidationError(f"Rule {rule_id}: regex requires a non-empty pattern string.")
            try:
                re.compile(value, re.IGNORECASE)
            except re.error as exc:
                raise PolicyValidationError(f"Rule {rule_id}: invalid regex: {exc}") from exc

        severity = str(rule.get("severity", "MEDIUM")).strip().upper()
        action = str(rule.get("action", "REVIEW")).strip()
        if not action:
            raise PolicyValidationError(f"Rule {rule_id}: action is required.")

        active_flag = bool(rule.get("active", True))
        rule.update({
            "rule_id": rule_id,
            "rule_name": name,
            "field": field,
            "operator": op,
            "value": value,
            "severity": severity,
            "action": action,
            "reason": str(rule.get("reason", "")).strip(),
            "active": active_flag,
        })
        rule.pop("id", None)
        rule.pop("name", None)
        rule.pop("target_field", None)
        rule.pop("threshold", None)
        rule.pop("keywords", None)
        seen.add(rule_id)
        validated.append(rule)
    return {"version": data.get("version", 1), "rules": validated}


def parse_policy_config(text: str, filename: str | None = None) -> dict[str, Any]:
    """Parse and validate pasted or uploaded JSON/YAML without changing disk."""
    decoded, _ = _decode_document(text, filename)
    return validate_policy_config(decoded)


def parse_policy_text(raw_text: str) -> tuple[list[dict[str, Any]], str]:
    """Parse raw JSON/YAML policy text and return (rules_list, status_message)."""
    try:
        decoded, source_format = _decode_document(raw_text)
        validated = validate_policy_config(decoded)
        rules = validated["rules"]
        return rules, f"Parsed {len(rules)} policy rule(s) from {source_format}."
    except PolicyValidationError as exc:
        return [], str(exc)
    except Exception as exc:
        return [], f"Failed to parse policy text as JSON or YAML: {exc}"


def load_policies(path: str | Path | None = None) -> dict[str, Any]:
    """Read the current policy config on every call so edits are visible without restart."""
    target = _resolve_policy_path(path)
    try:
        return parse_policy_config(target.read_text(encoding="utf-8"), str(target))
    except FileNotFoundError:
        try:
            from overlord_db import latest_policy_config

            stored = latest_policy_config()
            return validate_policy_config(stored) if stored else {"version": 1, "rules": []}
        except Exception:
            return {"version": 1, "rules": []}


def save_policies(
    config: dict[str, Any] | list[dict[str, Any]],
    path: str | Path | None = None,
    source: str = "ui-or-config",
) -> dict[str, Any]:
    """Validate and atomically persist the active policies file."""
    target = _resolve_policy_path(path)
    valid = validate_policy_config(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    ext = target.suffix.lower()
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if ext in {".yaml", ".yml"}:
                if yaml is None:
                    raise PolicyValidationError("PyYAML is required to save YAML policy files.")
                handle.write(yaml.safe_dump(valid, sort_keys=False, allow_unicode=True))
            else:
                json.dump(valid, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    if path is None or target.resolve() == _resolve_policy_path(None).resolve():
        from overlord_db import persist_policy_revision

        persist_policy_revision(valid, source=source)
    return valid


def add_policy_rule(
    rule: dict[str, Any],
    path: str | Path | None = None,
    source: str = "ui-quick-builder",
) -> dict[str, Any]:
    config = load_policies(path)
    next_rule = dict(rule)
    if not str(next_rule.get("rule_id") or next_rule.get("id") or "").strip():
        next_rule["rule_id"] = next_policy_id(config["rules"])
    config["rules"].append(next_rule)
    return save_policies(config, path, source=source)


def evaluate_policies(
    context: dict[str, Any],
    config: dict[str, Any] | list[dict[str, Any]] | None = None,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic violation records for every active matching rule."""
    if not isinstance(context, dict):
        return []
    active = validate_policy_config(config) if config is not None else load_policies(path)
    violations: list[dict[str, Any]] = []
    for rule in active["rules"]:
        if not rule.get("active", True):
            continue
        actual = context.get(rule["field"])
        expected = rule["value"]
        op = rule["operator"]
        matched = False
        if actual is not None:
            if op in {">", ">=", "<", "<=", "==", "!="}:
                if rule["field"] in {"invoice_text", "vendor_name"} and op in {"==", "!="}:
                    equal = str(actual).strip().casefold() == str(expected).strip().casefold()
                    matched = equal if op == "==" else not equal
                else:
                    lhs = _to_float(actual)
                    rhs = _to_float(expected)
                    if lhs is not None and rhs is not None:
                        matched = {
                            ">": lhs > rhs,
                            ">=": lhs >= rhs,
                            "<": lhs < rhs,
                            "<=": lhs <= rhs,
                            "==": lhs == rhs,
                            "!=": lhs != rhs,
                        }[op]
            elif op == "contains_any":
                haystack = str(actual).casefold()
                matched = any(str(token).strip() and str(token).strip().casefold() in haystack for token in expected)
            elif op == "regex":
                matched = re.search(expected, str(actual), re.IGNORECASE) is not None
        if matched:
            rendered_value = f"{actual}" if isinstance(actual, str) else str(actual)
            reason = rule["reason"] or (
                f"{rule['field']} {op} {expected!r} matched (actual: {rendered_value!r})."
            )
            violations.append({
                "rule_id": rule["rule_id"],
                "id": rule["rule_id"],
                "rule_name": rule["rule_name"],
                "name": rule["rule_name"],
                "severity": rule["severity"],
                "reason": reason,
                "action": rule["action"],
                "field": rule["field"],
                "operator": op,
                "expected": expected,
                "value": expected,
                "actual": actual,
            })
    return violations
