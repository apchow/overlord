# Project Overlord — Build Overview

## Product goal

Overlord is a finance-control cockpit for invoice-to-PO-to-goods-receipt reconciliation. The interface is designed to help a finance operator move from source evidence to a defensible action quickly: inspect the documents, understand the hold or clearance, ask a grounded question, and inspect the audit trail.

It is deliberately **not** an autonomous payment or fund-transfer system. The dashboard's core promise is evidence-to-action control: it does not move funds or silently authorize a payment.

## Positioning and moat strategy

**Category position:** from spend visibility to provable financial action. The product surface tells the story as **Detect → Prove → Control → Learn**.

**Why this is stronger than a dashboard-only pitch:** charts and risk scores are easy to reproduce. The product is built around a governed evidence-to-outcome chain: source document and clause, deterministic calculation, control result, human-reviewed next step, and audit record. Over time, permitted integrations and reviewer-confirmed outcomes could improve workflow context and calibration. That is a moat to build—not a claim of proprietary scale or predictive accuracy before real deployment data exists.

## What the build includes

### 1. Mission Control dashboard

- Dark, high-contrast finance console with a fixed-width control rail and responsive main workspace.
- Sidebar controls for scenario, audit mode, LLM engine, tax validation, Chaos Mode, and pipeline execution.
- PO, goods-receipt, and invoice work areas with XAI/document views and editable or uploadable source documents.
- CFO Boardroom with a clearly labeled ROI scenario, citation-backed executive exports, and governed reviewer feedback.
- Responsive layout rules collapse the desktop shell and agent strip on narrower screens.

### 2. Smooth audit execution

The audit is a streamed LangGraph run. The Execute button disables immediately while a run is in progress; telemetry is emitted as nodes complete; the UI returns to an enabled state after success or safe recovery. The five-node run path is shown in the audit workspace:

1. **PO Parser** — extracts the order, authorized amount, and relevant clauses.
2. **Vision Agent** — inspects goods-receipt evidence and may draw an XAI bounding box for a shortage.
3. **Invoice Parser** — extracts vendor invoice facts and totals.
4. **Auditor** — performs deterministic reconciliation and policy evaluation.
5. **Supervisor** — validates the outcome and audit response.

Model assistance can help with extraction and explanation. **Policy comparisons, monetary calculations, and holds remain deterministic code paths.** Vision inputs are never sent to local Ollama.

### 3. Grounded Ask panel

The XAI Copilot receives the current audit context, PO and invoice text, vision result, and deterministic policy findings. It should explain the run using that context and fall back to a local deterministic answer when the selected model is unavailable. The evidence surface remains the source of truth; chat does not override an audit result.

### 4. Evidence, policy, and audit controls

- JSON and YAML policies can be uploaded, edited, validated, hot-swapped, and re-audited without a code change.
- Default rules include prohibited ancillary fees and an invoice cap over $5,000.
- Malformed policy input returns a safe UI error and leaves unrelated audit outputs untouched.
- The database/compliance layer records audit events and policy revisions; the UI exposes ledger history and chain validation.
- Reviewer feedback can inform a draft policy change, but a human must approve activation.

### 5. Marketing logic embedded in the product

The main dashboard opens with the product's category contrast: **from spend visibility to provable financial action**. It explains the operating sequence directly in the UI—detect, prove, control, learn—and frames the difference as an insight-only alert versus an evidence-backed decision, governed action, and audit receipt. The claim is about the product workflow, not an unsupported competitor benchmark.

The CFO Boardroom uses a transparent ROI scenario calculator. Its output is an assumption-based annualized scenario, not confirmed savings. The executive brief separates current protected exposure, cumulative ledger-tracked protected amount, and confirmed cash recovery (which remains zero unless the source context explicitly provides a confirmed-recovery value).

### 6. Executive Boardroom Brief

The report API builds a citation-first brief from a completed audit, ledger rows, and CFO inputs. PDF, Markdown, and structured CSV are supported. The report includes run/invoice/vendor details, audit mode and status, processed counts, PO/invoice/variance values, ledger-tracked protection and separately reported confirmed recoveries (zero unless explicitly present in the audit context), annualized CFO ROI assumptions, and up to three urgent exceptions ranked by severity then dollar impact.

Each reported exception carries four evidence slots:

- source line or field;
- clause or deterministic policy rule;
- matching telemetry entry;
- Supervisor calculation or Vision confidence/evidence.

Export is guarded until the current audit is complete.

## Runtime / build framework

### Application composition

- **UI:** Gradio Blocks (`app.py`) with inline CSS and Python callbacks.
- **Workflow:** LangGraph state graph with five stages.
- **Policy engine:** local deterministic JSON/YAML parser and evaluator (`policy_engine.py`).
- **Persistence:** SQL-backed audit/policy history with local ledger compatibility (`overlord_db.py`).
- **Reports:** `executive_brief.py`; PyMuPDF renders PDF via `Page.insert_htmlbox`.
- **LLM routing:** Gemini first in Auto mode; stdlib-only Ollama `/api/chat` fallback for text; Local Only and Offline Deterministic options. Ollama connection timeout is capped at 1.5 seconds and the default overall fallback budget is under one second.
- **MCP:** optional server entry point (`mcp_server.py`) exposes governed tools for compatible clients.

### Local run

```bash
cd /home/user/overlord
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

The Gradio application binds to `0.0.0.0` and uses `PORT` or `GRADIO_SERVER_PORT`, defaulting to 7860. Configure credentials and database settings through environment variables; do not commit secrets. Ollama is optional. A cloud deployment without a local Ollama service should use Auto mode (the fallback fails fast) or Offline Deterministic mode.

### Test and quality checks

```bash
python -m py_compile app.py executive_brief.py policy_engine.py
python -m pytest -v
```

Tests cover core audit behavior, policy JSON/YAML parsing, Scenario C custom-policy holds, report citations and exports, and unreachable-Ollama fallback timing. Use an isolated test database/policy file when running tests against a shared environment.

## Operator walkthrough

1. Choose a scenario or upload/edit PO and invoice content; add the goods-receipt image if needed.
2. Select the audit mode and LLM engine. The engine setting affects assistive text calls, not deterministic policy math.
3. Click **Execute 3-Way Match** and follow the node telemetry and evidence panels.
4. Use the Ask panel for a citation-oriented explanation; check the actual source view and policy result before acting.
5. Review or hot-swap a policy only through the validated policy UI; reset restores the two defaults and re-runs the audit.
6. Inspect the compliance ledger, then generate the Boardroom Brief after a completed run.
7. In the CFO Boardroom, inspect ROI assumptions separately from protected exposure and confirmed recovery; do not present a scenario estimate as realized savings.

## Guardrails and honest scope

- ROI is a scenario estimate based on CFO-entered volume, average value, and error rate; it is not a promise of savings.
- A flagged invoice, protected amount, confirmed recovery, and estimated exposure are distinct quantities and must not be added together without a defined accounting rule.
- Production readiness still requires organization-specific authentication/authorization, tenant isolation, secret management, data retention rules, database backup/migrations, observability, and security review.
