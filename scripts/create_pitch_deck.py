from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Project_Overlord_Pitch_Deck.pptx"

BG = "090C12"
PANEL = "131A25"
PANEL_2 = "182231"
BORDER = "2A3546"
WHITE = "F4F7FB"
MUTED = "9BA9BC"
GREEN = "28D7A0"
RED = "FF5A66"
AMBER = "F5B94F"
BLUE = "7EAFFF"
FONT = "Aptos"
MONO = "Aptos Mono"


def rgb(hex_value: str) -> RGBColor:
    return RGBColor.from_string(hex_value)


def textbox(slide, x, y, w, h, text, size=16, color=WHITE, bold=False, font=FONT,
            align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, margin=0.04, italic=False):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(margin)
    frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    for i, line in enumerate(text.split("\n")):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.alignment = align
        p.space_after = Pt(5)
        run = p.add_run()
        run.text = line
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = rgb(color)
    return shape


def rect(slide, x, y, w, h, fill=PANEL, line=BORDER, radius=True, transparency=0):
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.fill.transparency = transparency
    shape.line.color.rgb = rgb(line)
    shape.line.width = Pt(1)
    return shape


def line(slide, x1, y1, x2, y2, color=GREEN, width=2, dash=None):
    shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(width)
    if dash:
        shape.line.dash_style = dash
    return shape


def pill(slide, x, y, w, label, color=GREEN, fill=PANEL_2):
    rect(slide, x, y, w, 0.34, fill=fill, line=color, radius=True)
    textbox(slide, x + 0.04, y + 0.025, w - 0.08, 0.24, label, size=9, color=color, bold=True,
            font=MONO, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0.0)


def base_slide(prs, index, section):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(BG)
    # Quiet technical grid, intentionally low-contrast.
    for gx in range(1, 14):
        line(slide, gx, 0, gx, 7.3, color="111824", width=0.35)
    for gy in (1, 2, 3, 4, 5, 6, 7):
        line(slide, 0, gy, 13.333, gy, color="111824", width=0.35)
    textbox(slide, 0.55, 0.22, 4.8, 0.25, f"PROJECT OVERLORD  /  {section.upper()}",
            size=9, color=GREEN, bold=True, font=MONO, margin=0)
    line(slide, 0.55, 7.12, 12.78, 7.12, color=BORDER, width=0.8)
    textbox(slide, 0.6, 7.19, 5.0, 0.18, "PS-BA1  •  FINANCIAL DEFENSE ENGINE", size=8, color=MUTED, font=MONO, margin=0)
    textbox(slide, 11.75, 7.18, 1.0, 0.2, f"{index:02d} / 07", size=8, color=MUTED, font=MONO,
            align=PP_ALIGN.RIGHT, margin=0)
    return slide


def title(slide, headline, subline=None):
    textbox(slide, 0.62, 0.72, 12.0, 0.65, headline, size=29, color=WHITE, bold=True, margin=0)
    if subline:
        textbox(slide, 0.65, 1.38, 11.8, 0.42, subline, size=13, color=MUTED, margin=0)


def add_cover(prs):
    slide = base_slide(prs, 1, "The problem")
    pill(slide, 0.7, 0.9, 2.25, "3-WAY MATCH  /  PS-BA1", color=GREEN)
    textbox(slide, 0.7, 1.55, 6.2, 1.55, "Stop invoice leakage\nbefore it becomes a payment.", size=34, bold=True, margin=0)
    textbox(slide, 0.72, 3.45, 5.65, 0.95,
            "Accounts Payable decisions are spread across purchase orders, delivery evidence, and vendor invoices. Overlord reconciles those records and shows its evidence before money moves.",
            size=16, color=MUTED, margin=0)
    rect(slide, 0.72, 5.0, 5.55, 0.82, fill="11251F", line=GREEN)
    textbox(slide, 0.95, 5.18, 5.1, 0.42,
            "MATCH THE DOCUMENTS.  EXPLAIN THE EXCEPTION.  HOLD THE PAYMENT.", size=12, color=GREEN, bold=True, font=MONO, valign=MSO_ANCHOR.MIDDLE)

    # Three evidence documents converge on one deterministic decision.
    cards = [(7.25, 1.25, "01", "PURCHASE ORDER", "$500.00", BLUE),
             (9.45, 2.65, "02", "GOODS RECEIPT", "8 / 10 verified", AMBER),
             (7.25, 4.05, "03", "VENDOR INVOICE", "$600.00", RED)]
    for x, y, num, name, val, accent in cards:
        rect(slide, x, y, 2.35, 1.05, fill=PANEL, line=accent)
        pill(slide, x + 0.14, y + 0.12, 0.55, num, color=accent)
        textbox(slide, x + 0.82, y + 0.13, 1.36, 0.22, name, size=8, color=MUTED, bold=True, font=MONO, margin=0)
        textbox(slide, x + 0.17, y + 0.52, 2.02, 0.32, val, size=17, color=accent, bold=True, font=MONO, margin=0)
    line(slide, 9.57, 2.26, 10.52, 2.62, color=GREEN, width=2)
    line(slide, 9.57, 4.38, 10.52, 3.68, color=GREEN, width=2)
    rect(slide, 10.62, 2.83, 2.0, 0.9, fill="241419", line=RED)
    textbox(slide, 10.78, 3.04, 1.7, 0.38, "AUDIT  →  HOLD", size=13, color=RED, bold=True, font=MONO, align=PP_ALIGN.CENTER)
    textbox(slide, 7.0, 5.75, 5.8, 0.42, "The decision carries its source citations into the boardroom.", size=12, color=MUTED, align=PP_ALIGN.CENTER)


def add_architecture(prs):
    slide = base_slide(prs, 2, "The engine")
    title(slide, "Five workflow nodes. One verified outcome.", "LangGraph orchestrates the run; Python owns arithmetic and policy decisions.")
    names = [
        ("01", "PO Parser", "Authorized spend\n+ clauses", BLUE),
        ("02", "Vision Agent", "Goods receipt\nevidence", AMBER),
        ("03", "Invoice Parser", "Line items\n+ totals", BLUE),
        ("04", "Auditor", "3-way match\n+ policies", RED),
        ("05", "Supervisor", "Independent\nverification", GREEN),
    ]
    x0, card_w, gap, y = 0.62, 2.28, 0.25, 2.45
    for index, (number, name, detail, accent) in enumerate(names):
        x = x0 + index * (card_w + gap)
        rect(slide, x, y, card_w, 1.62, fill=PANEL, line=accent)
        pill(slide, x + 0.16, y + 0.15, 0.52, number, color=accent)
        textbox(slide, x + 0.16, y + 0.62, card_w - 0.3, 0.3, name, size=15, color=WHITE, bold=True, margin=0)
        textbox(slide, x + 0.16, y + 1.02, card_w - 0.3, 0.45, detail, size=11, color=MUTED, font=MONO, margin=0)
        if index < 4:
            line(slide, x + card_w + 0.03, y + 0.82, x + card_w + gap - 0.04, y + 0.82, GREEN, width=2)
    rect(slide, 0.75, 4.6, 5.75, 1.1, fill="11251F", line=GREEN)
    textbox(slide, 1.0, 4.84, 5.25, 0.57,
            "Deterministic core: totals, thresholds, keyword/regex rules, variance, and supervisor checks.",
            size=14, color=GREEN, bold=True, margin=0)
    rect(slide, 6.78, 4.6, 5.75, 1.1, fill=PANEL, line=BORDER)
    textbox(slide, 7.03, 4.82, 5.25, 0.66,
            "Gemini is an optional assist for document/vision summaries. If unavailable, the audit still runs with deterministic fallbacks.",
            size=13, color=WHITE, margin=0)
    textbox(slide, 0.9, 6.12, 11.5, 0.38,
            "Outputs: red/green XAI findings  •  dispute draft  •  human-approved payment action  •  compliance record",
            size=11, color=MUTED, font=MONO, align=PP_ALIGN.CENTER)


def add_scenarios(prs):
    slide = base_slide(prs, 3, "Proof in the demo")
    title(slide, "Three scenarios. Three different audit outcomes.", "Use these known fixtures to demonstrate discrepancy detection, vision evidence, and a clean pass.")
    data = [
        (0.7, "A  /  UNAUTHORIZED FEE", "PO  $500", "Invoice  $600", "Setup fee  $100", RED,
         "Flags the unapproved line item and calculates the $100 variance."),
        (4.88, "B  /  SHORT SHIPMENT", "Ordered  10", "Delivered  8", "Missing units  2", AMBER,
         "Vision/XAI highlights missing inventory; invoice includes $2,000 for undelivered units."),
        (9.06, "C  /  CLEAN MATCH", "PO  $1,200", "Invoice  $1,200", "Variance  $0", GREEN,
         "Passes by default. A judge-added policy can still override it to a red hold."),
    ]
    for x, label, metric1, metric2, metric3, accent, description in data:
        rect(slide, x, 2.1, 3.58, 3.85, fill=PANEL, line=accent)
        textbox(slide, x + 0.22, 2.34, 3.1, 0.3, label, size=11, color=accent, bold=True, font=MONO, margin=0)
        textbox(slide, x + 0.22, 3.0, 3.1, 0.95, f"{metric1}\n{metric2}\n{metric3}", size=18, color=WHITE, bold=True, font=MONO, margin=0)
        line(slide, x + 0.22, 4.18, x + 3.34, 4.18, color=BORDER, width=1)
        textbox(slide, x + 0.22, 4.42, 3.12, 1.0, description, size=12, color=MUTED, margin=0)
    textbox(slide, 0.9, 6.22, 11.5, 0.4,
            "Judge-facing proof: exact amount, source document, line item, vision summary, or policy rule—never an unexplained red badge.",
            size=12, color=WHITE, align=PP_ALIGN.CENTER)


def add_policy_donut(prs):
    slide = base_slide(prs, 4, "Challenge 1  /  policy hot-swap")
    title(slide, "Change the rule live. Re-audit immediately.", "Zero code edits. No redeploy. The policy engine is deterministic and hot-reloads the active JSON/YAML config.")
    steps = [
        (0.72, "01  DEFINE", "Quick Rule Builder\nor JSON / YAML"),
        (3.84, "02  VALIDATE", "Field + operator\n+ value + severity"),
        (6.96, "03  EVALUATE", "Python comparisons\nno LLM math"),
        (10.08, "04  OVERRIDE", "Red exception\n+ payment hold"),
    ]
    for x, label, desc in steps:
        rect(slide, x, 2.15, 2.55, 1.45, fill=PANEL, line=AMBER if x == 10.08 else BORDER)
        textbox(slide, x + 0.16, 2.42, 2.22, 0.27, label, size=11, color=AMBER if x == 10.08 else GREEN, bold=True, font=MONO, margin=0)
        textbox(slide, x + 0.16, 2.9, 2.22, 0.52, desc, size=12, color=WHITE, margin=0)
    for x in (3.35, 6.47, 9.59):
        line(slide, x, 2.86, x + 0.35, 2.86, GREEN, width=2)
    rect(slide, 0.85, 4.18, 5.35, 1.7, fill="111820", line=BORDER)
    textbox(slide, 1.08, 4.38, 4.9, 0.22, "EXAMPLE  /  JUDGE ADDS A LIVE RULE", size=9, color=MUTED, bold=True, font=MONO, margin=0)
    textbox(slide, 1.08, 4.8, 4.85, 0.76,
            'vendor_name  contains_any  "CloudScale Security"\nseverity: CRITICAL   action: BLOCK_PAYMENT',
            size=13, color=GREEN, font=MONO, margin=0)
    rect(slide, 6.56, 4.18, 5.9, 1.7, fill="241419", line=RED)
    textbox(slide, 6.84, 4.42, 5.35, 0.32, "SCENARIO C  /  WAS CLEAN  →  NOW BLOCKED", size=12, color=RED, bold=True, font=MONO, margin=0)
    textbox(slide, 6.84, 4.95, 5.25, 0.62,
            "Supervisor verifies the match, but policy has a hard visual override. The alert cites the new rule ID, reason, severity, and action.",
            size=12, color=WHITE, margin=0)
    textbox(slide, 1.0, 6.22, 11.2, 0.35,
            "Supported: >  ≥  <  ≤  ==  !=  contains_any  regex   |   Targets: totals, variance, tax %, short-shipped units, invoice text, vendor",
            size=10, color=MUTED, font=MONO, align=PP_ALIGN.CENTER)


def add_boardroom_donut(prs):
    slide = base_slide(prs, 5, "Challenge 2  /  executive brief")
    title(slide, "One click turns the audit into decision-ready evidence.", "PDF, Markdown, or CSV—generated from the current run, with citations that judges can check.")
    rect(slide, 0.7, 2.0, 4.2, 3.8, fill=PANEL, line=GREEN)
    pill(slide, 0.98, 2.25, 1.45, "EXECUTIVE SUMMARY", color=GREEN)
    textbox(slide, 0.98, 2.88, 3.7, 2.15,
            "3 source documents\n3 parsed line items\n$100 overcharge exposure\n$600 invoice on policy hold\n1 urgent exception",
            size=17, color=WHITE, bold=True, font=MONO, margin=0)
    textbox(slide, 0.98, 5.22, 3.65, 0.35, "Exposure is separated; overlapping amounts are not double-counted.", size=10, color=MUTED, margin=0)
    rect(slide, 5.25, 2.0, 7.35, 3.8, fill=PANEL, line=BORDER)
    textbox(slide, 5.58, 2.31, 6.5, 0.32, "TOP EXCEPTION  /  POL-FEE-001  /  HIGH", size=12, color=RED, bold=True, font=MONO, margin=0)
    textbox(slide, 5.58, 2.9, 6.5, 0.45, "Prohibited ancillary fees — payment blocked", size=18, color=WHITE, bold=True, margin=0)
    line(slide, 5.58, 3.55, 12.15, 3.55, color=BORDER, width=1)
    textbox(slide, 5.58, 3.82, 6.55, 1.55,
            'SOURCE  /  Vendor invoice, line 6\n"02. Setup Fee (Post-Deployment Configuration) .... $100.00"\n\nMETRIC  /  invoice_total $600 > PO authorized $500; variance $100',
            size=12, color=GREEN, font=MONO, margin=0)
    pill(slide, 0.95, 6.14, 1.15, "PDF", GREEN)
    pill(slide, 2.28, 6.14, 1.55, "MARKDOWN", BLUE)
    pill(slide, 3.98, 6.14, 1.1, "CSV", AMBER)
    textbox(slide, 5.45, 6.13, 6.75, 0.4,
            "Citations: exact source lines  •  policy IDs  •  metrics  •  LangGraph telemetry",
            size=10, color=MUTED, font=MONO, valign=MSO_ANCHOR.MIDDLE)


def add_governance(prs):
    slide = base_slide(prs, 6, "Trust  /  governed improvement")
    title(slide, "The system improves—with a human in the approval loop.", "Audits are durable, explanations are inspectable, and financial controls do not self-edit silently.")
    # Left side: feedback learning loop.
    loop = [(0.82, 2.1, "AUDIT", "Persist the run"), (3.0, 2.1, "REVIEW", "Confirm / false positive"),
            (5.18, 2.1, "LEARN", "Analyze repeated labels"), (7.36, 2.1, "DRAFT", "Suggest policy tuning")]
    for x, y, label, desc in loop:
        rect(slide, x, y, 1.9, 1.15, fill=PANEL, line=BLUE if label == "REVIEW" else GREEN)
        textbox(slide, x + 0.14, y + 0.17, 1.62, 0.22, label, size=10, color=GREEN, bold=True, font=MONO, margin=0)
        textbox(slide, x + 0.14, y + 0.52, 1.62, 0.42, desc, size=10, color=WHITE, margin=0)
    line(slide, 2.76, 2.68, 2.94, 2.68, GREEN)
    line(slide, 4.94, 2.68, 5.12, 2.68, GREEN)
    line(slide, 7.12, 2.68, 7.30, 2.68, GREEN)
    rect(slide, 9.7, 2.05, 2.68, 1.28, fill="241D12", line=AMBER)
    textbox(slide, 9.91, 2.28, 2.25, 0.25, "HUMAN APPROVAL", size=10, color=AMBER, bold=True, font=MONO, margin=0)
    textbox(slide, 9.91, 2.7, 2.22, 0.44, "Hot-swap + re-audit", size=12, color=WHITE, margin=0)
    line(slide, 9.28, 2.68, 9.62, 2.68, AMBER)
    rect(slide, 0.82, 3.88, 5.55, 1.53, fill=PANEL, line=BORDER)
    textbox(slide, 1.08, 4.12, 5.0, 1.05,
            "SQLAlchemy  /  SQLite local, PostgreSQL via DATABASE_URL\nAudit runs + violations + policy revisions\nSHA-256 chained compliance events + JSONL mirror",
            size=12, color=WHITE, font=MONO, margin=0)
    rect(slide, 6.7, 3.88, 5.68, 1.53, fill=PANEL, line=BORDER)
    textbox(slide, 6.96, 4.12, 5.18, 1.05,
            "MCP stdio server  /  11 tools\nPolicy evaluation, audit lookup, feedback, ledger verification\nNo public unauthenticated MCP endpoint",
            size=12, color=WHITE, font=MONO, margin=0)
    textbox(slide, 1.0, 5.95, 11.4, 0.48,
            "The learning agent drafts policy changes only after repeated, independent human labels. It never writes application source code or activates a rule by itself.",
            size=12, color=AMBER, bold=True, align=PP_ALIGN.CENTER)


def add_close(prs):
    slide = base_slide(prs, 7, "The ask")
    pill(slide, 0.72, 1.0, 1.8, "AP CONTROL PLANE", color=GREEN)
    textbox(slide, 0.72, 1.7, 8.2, 1.3, "From matching documents\nto defending the decision.", size=34, color=WHITE, bold=True, margin=0)
    textbox(slide, 0.78, 3.42, 7.5, 0.92,
            "Overlord makes exceptions visible, rules changeable, and every boardroom decision traceable to source evidence.",
            size=17, color=MUTED, margin=0)
    rect(slide, 0.78, 5.0, 7.7, 0.92, fill="11251F", line=GREEN)
    textbox(slide, 1.04, 5.23, 7.2, 0.35,
            "DETECT  →  EXPLAIN  →  HOLD  →  REVIEW  →  LEARN", size=14, color=GREEN, bold=True, font=MONO,
            align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    rect(slide, 9.28, 1.55, 3.08, 3.95, fill=PANEL, line=GREEN)
    textbox(slide, 9.58, 1.95, 2.45, 0.28, "DEMO PROOF", size=10, color=MUTED, bold=True, font=MONO, align=PP_ALIGN.CENTER)
    textbox(slide, 9.58, 2.5, 2.45, 1.55, "$100", size=44, color=GREEN, bold=True, font=MONO, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    textbox(slide, 9.58, 4.0, 2.45, 0.88, "unauthorized setup-fee variance in the seeded Scenario A", size=12, color=WHITE, align=PP_ALIGN.CENTER)
    textbox(slide, 0.82, 6.32, 11.5, 0.34,
            "ROI calculator outputs are scenario projections—not audited historical savings.",
            size=10, color=MUTED, font=MONO, align=PP_ALIGN.CENTER)


def build_deck() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Project Overlord | PS-BA1 Financial Defense Engine"
    prs.core_properties.subject = "Competition pitch deck; includes both weighted Donut challenges"
    prs.core_properties.author = "Project Overlord"
    for builder in (add_cover, add_architecture, add_scenarios, add_policy_donut,
                    add_boardroom_donut, add_governance, add_close):
        builder(prs)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build_deck())
