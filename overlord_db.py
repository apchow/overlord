"""SQLAlchemy persistence for Overlord audits, policy versions, and a hash-chained ledger.

Set DATABASE_URL to a managed PostgreSQL URL in production. Without it, the app
uses a local SQLite file under ``workspace/`` (mount a persistent Render disk or
use PostgreSQL if data must survive deploys/instance replacement).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    po_id: Mapped[str] = mapped_column(String(120), default="")
    invoice_id: Mapped[str] = mapped_column(String(120), default="")
    audit_mode: Mapped[str] = mapped_column(String(80), default="3-Way Match")
    scenario_name: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    po_authorized: Mapped[float] = mapped_column(Float, default=0.0)
    invoice_billed: Mapped[float] = mapped_column(Float, default=0.0)
    variance: Mapped[float] = mapped_column(Float, default=0.0)
    recovered: Mapped[float] = mapped_column(Float, default=0.0)
    raw_record: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditFeedback(Base):
    __tablename__ = "audit_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audit_runs.id", ondelete="RESTRICT"), index=True)
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    comment: Mapped[str] = mapped_column(Text, default="")


class PolicyViolationRow(Base):
    __tablename__ = "policy_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audit_runs.id", ondelete="RESTRICT"), index=True)
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    rule_name: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(240))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)


class PolicyRevision(Base):
    __tablename__ = "policy_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(80), default="ui-or-config")
    config: Mapped[dict[str, Any]] = mapped_column(JSON)


class ComplianceEvent(Base):
    __tablename__ = "compliance_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    audit_id: Mapped[str | None] = mapped_column(ForeignKey("audit_runs.id", ondelete="RESTRICT"), nullable=True, index=True)
    record: Mapped[dict[str, Any]] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)


class LedgerHead(Base):
    __tablename__ = "ledger_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    head_hash: Mapped[str] = mapped_column(String(64))
    event_count: Mapped[int] = mapped_column(Integer, default=0)


_workspace = Path(__file__).resolve().parent / "workspace"
_workspace.mkdir(parents=True, exist_ok=True)
_DEFAULT_URL = f"sqlite:///{(_workspace / 'overlord.sqlite3').as_posix()}"
_engine: Engine | None = None
_Session = None
_database_url = ""


def _normalize_url(value: str) -> str:
    url = value.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+" not in url.split(":", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def configure_database(database_url: str | None = None) -> Engine:
    """Configure/reconfigure the SQLAlchemy engine; primarily useful for tests."""
    global _engine, _Session, _database_url
    url = _normalize_url(database_url or os.environ.get("DATABASE_URL", _DEFAULT_URL))
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite:"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    _engine = create_engine(url, **kwargs)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    _database_url = url
    if url.startswith("sqlite:"):
        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    return _engine


def _get_engine() -> Engine:
    return _engine or configure_database()


def _get_session_factory():
    if _Session is None:
        configure_database()
    return _Session


def init_db() -> None:
    engine = _get_engine()
    Base.metadata.create_all(engine)
    # Small additive migration for databases created by the initial SQL backend.
    audit_columns = {column["name"] for column in inspect(engine).get_columns("audit_runs")}
    if "scenario_name" not in audit_columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE audit_runs ADD COLUMN scenario_name VARCHAR(160) NOT NULL DEFAULT ''")
    if _database_url.startswith("sqlite:"):
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS compliance_events_no_update "
                "BEFORE UPDATE ON compliance_events BEGIN SELECT RAISE(ABORT, 'compliance events are append-only'); END"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS compliance_events_no_delete "
                "BEFORE DELETE ON compliance_events BEGIN SELECT RAISE(ABORT, 'compliance events are append-only'); END"
            )
    Session = _get_session_factory()
    with Session.begin() as session:
        head = session.get(LedgerHead, 1)
        latest = session.scalar(select(ComplianceEvent).order_by(ComplianceEvent.id.desc()).limit(1))
        event_count = int(session.scalar(select(func.count()).select_from(ComplianceEvent)) or 0)
        if head is None:
            session.add(LedgerHead(
                id=1, head_hash=latest.entry_hash if latest else "0" * 64, event_count=event_count
            ))
        elif head.event_count == 0 and event_count:
            # Upgrade a DB initialized before the chain-head row existed.
            head.head_hash = latest.entry_hash
            head.event_count = event_count


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _append_compliance_event(session, event_type: str, audit_id: str | None,
                             record: dict[str, Any], timestamp: datetime) -> str:
    head = session.get(LedgerHead, 1, with_for_update=True)
    if head is None:
        head = LedgerHead(id=1, head_hash="0" * 64, event_count=0)
        session.add(head)
        session.flush()
    previous_hash = head.head_hash
    entry_hash = hashlib.sha256((previous_hash + _canonical_json(record)).encode("utf-8")).hexdigest()
    session.add(ComplianceEvent(
        created_at=timestamp, event_type=event_type, audit_id=audit_id, record=record,
        previous_hash=previous_hash, entry_hash=entry_hash,
    ))
    head.head_hash = entry_hash
    head.event_count += 1
    return entry_hash


def persist_audit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Persist an audit run and related exceptions plus one chained event."""
    init_db()
    entry = dict(record)
    audit_id = str(entry.get("audit_id") or uuid.uuid4()) if entry.get("event") == "OVERLORD_AUDIT" else entry.get("audit_id")
    if audit_id:
        entry["audit_id"] = audit_id
    timestamp = _as_datetime(entry.get("timestamp"))
    Session = _get_session_factory()
    with Session.begin() as session:
        if entry.get("event") == "OVERLORD_AUDIT":
            session.add(AuditRun(
                id=audit_id,
                created_at=timestamp,
                po_id=str(entry.get("po_id", "")),
                invoice_id=str(entry.get("invoice_id", "")),
                audit_mode=str(entry.get("audit_mode", "3-Way Match")),
                scenario_name=str(entry.get("scenario_name", "")),
                status=str(entry.get("status", "UNKNOWN")),
                po_authorized=float(entry.get("po_authorized", 0.0) or 0.0),
                invoice_billed=float(entry.get("invoice_billed", 0.0) or 0.0),
                variance=float(entry.get("variance", 0.0) or 0.0),
                recovered=float(entry.get("recovered", 0.0) or 0.0),
                raw_record=entry,
            ))
            for violation in entry.get("policy_violations", []):
                session.add(PolicyViolationRow(
                    audit_id=audit_id,
                    rule_id=str(violation.get("rule_id") or violation.get("id") or ""),
                    rule_name=str(violation.get("rule_name") or violation.get("name") or ""),
                    severity=str(violation.get("severity", "")),
                    reason=str(violation.get("reason", "")),
                    action=str(violation.get("action", "")),
                    detail=violation,
                ))
        _append_compliance_event(
            session, str(entry.get("event", "OVERLORD_EVENT")), audit_id, entry, timestamp
        )
    return entry


def persist_policy_revision(config: dict[str, Any], source: str = "ui-or-config") -> dict[str, Any]:
    init_db()
    normalized = json.loads(_canonical_json(config))
    digest = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
    Session = _get_session_factory()
    with Session.begin() as session:
        row = PolicyRevision(created_at=datetime.now(timezone.utc), sha256=digest, source=source, config=normalized)
        session.add(row)
        session.flush()
        revision_record = {
            "event": "POLICY_REVISION", "revision_id": row.id, "sha256": digest,
            "source": source, "timestamp": row.created_at.isoformat(),
        }
        _append_compliance_event(session, "POLICY_REVISION", None, revision_record, row.created_at)
        result = {"revision_id": row.id, "sha256": digest, "created_at": row.created_at.isoformat(), "source": source}
    return result


def latest_policy_config() -> dict[str, Any] | None:
    init_db()
    Session = _get_session_factory()
    with Session() as session:
        row = session.scalar(select(PolicyRevision).order_by(PolicyRevision.id.desc()).limit(1))
        return row.config if row else None


def list_policy_revisions(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    Session = _get_session_factory()
    with Session() as session:
        rows = session.scalars(select(PolicyRevision).order_by(PolicyRevision.id.desc()).limit(max(1, min(limit, 100)))).all()
        return [{"revision_id": row.id, "created_at": row.created_at.isoformat(), "sha256": row.sha256, "source": row.source, "config": row.config} for row in rows]


def record_audit_feedback(audit_id: str, rule_id: str, verdict: str, comment: str = "") -> dict[str, Any]:
    """Store reviewer feedback and append a matching hash-chained compliance event."""
    allowed = {"confirmed", "false_positive", "needs_review"}
    normalized_verdict = verdict.strip().lower()
    if normalized_verdict not in allowed:
        raise ValueError(f"verdict must be one of: {', '.join(sorted(allowed))}")
    init_db()
    Session = _get_session_factory()
    with Session.begin() as session:
        if session.get(AuditRun, audit_id) is None:
            raise ValueError(f"Audit {audit_id!r} does not exist in the database.")
        created = datetime.now(timezone.utc)
        feedback = AuditFeedback(
            created_at=created, audit_id=audit_id, rule_id=rule_id[:120],
            verdict=normalized_verdict, comment=comment[:1000],
        )
        session.add(feedback)
        session.flush()
        payload = {
            "event": "HUMAN_AUDIT_FEEDBACK", "feedback_id": feedback.id,
            "audit_id": audit_id, "rule_id": rule_id[:120],
            "verdict": normalized_verdict, "comment": comment[:1000],
            "timestamp": created.isoformat(),
        }
        _append_compliance_event(session, "HUMAN_AUDIT_FEEDBACK", audit_id, payload, created)
        result = payload
    return result


def list_audit_feedback(limit: int = 200) -> list[dict[str, Any]]:
    init_db()
    Session = _get_session_factory()
    with Session() as session:
        rows = session.scalars(select(AuditFeedback).order_by(AuditFeedback.id.desc()).limit(max(1, min(limit, 1000)))).all()
        return [{"feedback_id": row.id, "audit_id": row.audit_id, "rule_id": row.rule_id,
                 "verdict": row.verdict, "comment": row.comment, "created_at": row.created_at.isoformat()}
                for row in rows]


def list_audits(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    Session = _get_session_factory()
    with Session() as session:
        rows = session.scalars(select(AuditRun).order_by(AuditRun.created_at.desc()).limit(max(1, min(limit, 100)))).all()
        return [{"audit_id": row.id, "created_at": row.created_at.isoformat(), "po_id": row.po_id,
                 "invoice_id": row.invoice_id, "audit_mode": row.audit_mode, "status": row.status,
                 "po_authorized": row.po_authorized, "invoice_billed": row.invoice_billed,
                 "variance": row.variance, "recovered": row.recovered,
                 "policy_violations": row.raw_record.get("policy_violations", [])} for row in rows]


def get_audit(audit_id: str) -> dict[str, Any] | None:
    init_db()
    Session = _get_session_factory()
    with Session() as session:
        row = session.get(AuditRun, audit_id)
        return row.raw_record if row else None


def verify_compliance_ledger() -> dict[str, Any]:
    """Validate every DB ledger link and event payload hash from genesis onward."""
    init_db()
    Session = _get_session_factory()
    expected_previous = "0" * 64
    checked = 0
    with Session() as session:
        rows = session.scalars(select(ComplianceEvent).order_by(ComplianceEvent.id.asc())).all()
        for row in rows:
            if row.previous_hash != expected_previous:
                return {"valid": False, "events_checked": checked, "failed_event_id": row.id, "reason": "previous_hash_mismatch"}
            calculated = hashlib.sha256((expected_previous + _canonical_json(row.record)).encode("utf-8")).hexdigest()
            if calculated != row.entry_hash:
                return {"valid": False, "events_checked": checked, "failed_event_id": row.id, "reason": "entry_hash_mismatch"}
            expected_previous = row.entry_hash
            checked += 1
        head = session.get(LedgerHead, 1)
        if head and (head.head_hash != expected_previous or head.event_count != checked):
            return {"valid": False, "events_checked": checked, "reason": "ledger_head_mismatch"}
    return {"valid": True, "events_checked": checked, "head_hash": expected_previous}


def database_health() -> dict[str, Any]:
    init_db()
    Session = _get_session_factory()
    with Session() as session:
        session.execute(select(1))
        audit_count = int(session.scalar(select(func.count()).select_from(AuditRun)) or 0)
        policy_count = int(session.scalar(select(func.count()).select_from(PolicyRevision)) or 0)
        event_count = int(session.scalar(select(func.count()).select_from(ComplianceEvent)) or 0)
    dialect = _get_engine().dialect.name
    safe_url = make_url(_database_url).render_as_string(hide_password=True)
    return {"ok": True, "dialect": dialect, "url": safe_url, "audit_count": audit_count,
            "policy_revision_count": policy_count, "ledger_event_count": event_count}


def ensure_policy_baseline(config: dict[str, Any]) -> None:
    """Record the shipped policy set once when bringing up a fresh database."""
    if not latest_policy_config():
        persist_policy_revision(config, source="bootstrap")
