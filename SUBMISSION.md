# Hackathon Submission Copy (Devpost / Portal)

**Project Name:** Project Overlord — Financial Defense Engine  
**Track:** PS-BA1 · Three-Way Invoice, Purchase Order & Goods-Receipt Reconciliation

**Description:**
Project Overlord helps Accounts Payable teams reconcile Purchase Orders, Goods Receipts, and vendor invoices before approving payment. Its five-node LangGraph workflow parses documents, inspects delivery evidence via Gemini Vision (with PIL XAI bounding boxes and Chaos Mode resilience), compares totals and line items, evaluates deterministic business policies, and independently verifies the audit outcome before settlement.

Two live competition controls are built directly into the Mission Control cockpit:
1. **Zero-Code Policy Hot-Swap & Re-Audit (`policy_engine.py` / `policies.json`):** Add or edit JSON/YAML rules through the UI form, code editor, file upload, or MCP server and immediately re-run audits without code edits — forcing a red **POLICY EXCEPTION — PAYMENT BLOCKED** hold even on previously clean matches.
2. **One-Click Executive Boardroom Brief (`executive_brief.py`):** Export citation-backed **PDF, Markdown, or CSV** boardroom reports detailing processed counts, overcharge/hold exposure, CFO ROI scenario projections, and the Top 3 urgent exceptions anchored with exact source lines, policy rules, telemetry logs, and Supervisor/Vision math gates.

Backed by SQLAlchemy persistence (`overlord_db.py`, SQLite or PostgreSQL via `DATABASE_URL`) + SHA-256 hash-chained compliance events + append-only JSONL receipts, an 11-tool FastMCP stdio server (`mcp_server.py`), local Ollama fallback routing (Qwen 5B / OLMoE), and a human-governed Continuous Improvement Agent (`improvement_agent.py`), Project Overlord moves Accounts Payable from spend visibility to provable financial action.
