# Project Overlord — Pitch Prep & Judge Q&A

## 20-second positioning
**Project Overlord turns spend visibility into provable financial action.** It reconciles a Purchase Order, Goods Receipt, and Vendor Invoice; applies live-editable deterministic controls; and carries each exception from source evidence to a governed decision and audit receipt. Unlike an alert-only dashboard, it is built to show the proof and the control path—not just surface a risk score.

## 4-minute live pitch script

### 0:00–0:25 | The hook
“Finance does not need another dashboard that paints a risk score red. It needs proof that connects the source document to a safe decision and a traceable action. Project Overlord turns the PO, delivery evidence, and invoice into one evidence-backed financial control.”

### 0:25–0:55 | Mission Control and the moat
“Notice the product promise at the top: detect, prove, control, learn. The moat we are building is the evidence-to-outcome chain: source line, contract/policy condition, deterministic calculation, approved action, and ledger receipt. Over time, a governed history of decisions and reviewer-confirmed outcomes can improve calibration and trust—without claiming that a dashboard or model score alone is defensible. The five-node run is PO Parser, Vision Agent, Invoice Parser, Auditor, and Supervisor. Gemini assists extraction; policy decisions and math stay deterministic.”

### 0:55–1:25 | Seeded proof: Scenario A
“Scenario A authorizes $500. The invoice is $600 because it adds a $100 setup fee. I run the audit. Watch the line item and variance appear, and the supervisor verify the arithmetic. We can see the source evidence and the payment hold—not just a model’s opinion.”

### 1:25–2:20 | Donut 1: live policy hot-swap
“Now I’ll switch to Scenario C, which is a clean $1,200 match. In the Quick Rule Builder I add a new rule: `vendor_name contains_any CloudScale Security`, Critical severity, block payment. I click **Add Rule & Re-Run Audit**. No code edit or redeploy. The rule is validated and evaluated deterministically; the previously clean match now shows a red **POLICY EXCEPTION (PAYMENT BLOCKED)** card. The supervisor confirms the policy hold.”

### 2:20–3:10 | Donut 2: executive brief with citations
“From this exact run I select PDF and generate the **Executive Boardroom Brief**. It includes the three source documents, parsed line-item count, PO and invoice values, payment-hold exposure, and the top urgent exception. The report cites the vendor line in the PO, the exact rule ID, and the LangGraph policy log. A judge can check each claim against the original evidence. Markdown and CSV are also available.”

### 3:10–3:35 | Trust and improvement loop
“Reviewers can label findings as confirmed, false positive, or needs review. Our improvement agent looks for repeated labels across independent audits and drafts policy suggestions. It does not rewrite application code or silently change payment rules; a person reviews the draft and explicitly hot-swaps it.”

### 3:35–4:00 | Close
“Project Overlord moves finance from spend visibility to provable financial action: detect the exception, prove it from source evidence, govern the decision, and preserve the outcome. That closed loop is the product; the dashboard is only its control surface. The $100 is our seeded demo variance, and the CFO projection is a scenario—not historical savings.”

## Demo runbook

### Before presenting
- Start from the repository root with dependencies installed: `python app.py`.
- Check the storage card says the DB is healthy and the ledger chain is verified.
- Keep `OVERLORD_LIVE_LLM=0` for a deterministic, network-independent stage run, or use a configured Gemini key if demonstrating optional vision/model assistance.
- Confirm the file `policies.json` has the two shipped rules. Do not use a real vendor document or credentials in the public demo.
- Keep the **CFO Boardroom** tab ready.

### Donut 1 steps
1. Select **Scenario C: Clean 3-Way Match ($0.00 Variance)** and run once to establish the clean baseline.
2. In the always-visible policy panel, open **Quick Rule Builder**.
3. Enter Rule Name: `Block CloudScale vendor`; Target Field: `vendor_name`; Operator: `contains_any`; Threshold / Keywords: `CloudScale Security`; Severity: `CRITICAL`; Action: `BLOCK_PAYMENT_AND_ESCALATE`.
4. Click **Add Rule & Re-Run Audit**. Point to the red override, rule ID, source, telemetry, and payment-blocked wording.
5. If you need a clean state for the next judge, click **Reset to Default Policies**.

### Donut 2 steps
1. Use the completed Scenario C custom-rule audit (before resetting) or Scenario A.
2. Open **CFO Boardroom → One-Click Executive Boardroom Brief**.
3. Select **PDF** and click **Generate Executive Brief**. Show the citations, then mention Markdown and CSV exports.

### Optional proof: Scenario B
Select the short-shipment scenario and run it. Explain the 10 ordered vs 8 delivered evidence and point to the XAI bounding box / missing-inventory signal. Avoid claiming vision can guarantee factual correctness: it is a verification aid, and the supervisor/ledger remain visible.

## Technical explanation in plain English

- **Five agents/nodes:** They are five stages in one stateful workflow, not five independent LLMs. Parsers and the supervisor are substantially deterministic; Gemini is optional assistance.
- **Policy engine:** Reads active JSON/YAML rules, validates supported fields/operators, atomically saves UI edits, and reloads the config at each evaluation. It never asks an LLM to do financial math.
- **Executive report:** Builds a report model from the completed run, ranks exceptions by severity and impact, and includes source-line, clause, metric, or telemetry citations. PDF uses PyMuPDF; Markdown and CSV use standard Python libraries.
- **Database:** SQLAlchemy models run against SQLite locally or PostgreSQL via `DATABASE_URL`. SQL compliance events are hash-chained; a JSONL copy remains for human inspection. A hash chain is tamper-evident, not a substitute for independently administered immutable/WORM retention.
- **MCP:** The app provides an MCP stdio server with 11 tools for policy, audit, feedback, storage, and ledger operations. MCP write tools should only be enabled for trusted clients.
- **Improvement agent:** It is a governed policy-learning loop based on reviewer labels. It may draft a severity change after repeated independent confirmed findings; it cannot edit source code or activate a rule without human approval.

## Likely judge questions

### “What stops another team copying the dashboard?”
“The dashboard itself is not the moat. The moat we are building is a governed evidence-to-outcome graph: what the contract and source documents said, which deterministic control fired, what a human approved, and what the eventual outcome was. Integrations and reviewer-confirmed history can make that chain more useful over time. We do not claim a proprietary data advantage until we have earned it through real deployments.”

### “Is this just an LLM reading invoices?”
“No. The 3-way arithmetic and custom policy rules are deterministic Python. Gemini is optional for document and vision assistance. The supervisor node verifies the arithmetic, and the report cites the underlying text or metrics.”

### “Can a judge really add a rule live?”
“Yes. The form or JSON/YAML editor validates and saves the config atomically. Every audit reloads the file. The new rule is evaluated without code changes or redeployment, and a violation forces the red payment-blocked UI state.”

### “How do you know the report is grounded?”
“Each exception carries citations generated from parsed source text with line numbers, or from exact engine metrics and telemetry. The brief distinguishes invoice hold amount from overcharge exposure so overlapping amounts are not added twice.”

### “Does the system learn on its own?”
“It learns from explicit reviewer feedback across independent audits and drafts a proposed policy adjustment. We intentionally require a human to approve and re-run it; automatic self-modifying code or silent changes to payment controls would be unsafe.”

### “Is the deployed database persistent?”
“The code supports PostgreSQL through `DATABASE_URL`. SQLite is the local fallback. For durable Render storage we must configure a managed PostgreSQL instance or a persistent disk; an ephemeral container filesystem is not a long-term database.”

### “What does MCP add?”
“It standardizes access to Overlord capabilities for MCP-compatible clients—policy inspection/evaluation, audit lookup, feedback submission, and chain verification. The current chatbot is not silently delegating payment approval to an external MCP server.”

### “Are the ROI numbers guaranteed?”
“No. The CFO Boardroom calculator is a scenario projection based on the selected monthly invoice volume, average value, and error-rate assumptions. We show the assumptions and do not present that estimate as realized savings.”

## Recovery lines
- **Gemini/network unavailable:** “The deterministic audit and policy engine still run; live model assistance is optional.”
- **Invalid policy config:** “The config is rejected before replacement. The current valid policy set remains active; I can correct it in the editor.”
- **No repeated learning evidence:** “The agent intentionally asks for multiple independent reviewer labels before proposing a control change.”
- **No database credentials on stage:** “This run uses local SQLite. The same SQLAlchemy layer supports managed PostgreSQL once the deployment environment provides `DATABASE_URL`.”
- **Time is short:** Show Scenario A, demonstrate the Scenario C custom rule, generate the cited PDF, and close. Those are the two weighted challenge features.
