"""
The full referral narrative as a formatted PDF, for the "attach a document"
step of the DOJ / OIG / MFCU intakes.

It lays out the SAME text the one referral generator writes
(routes/providers.py provider_oig_tip) — it never rewords it — so the PDF, the
copy-paste box and the saved filed_text cannot drift apart. The plain text has
a regular shape this reads:
  - a header block before the first blank line
  - ALL-CAPS lines at column 0 are section headings
  - "  ** ... **" blocks are call-outs (KEY FINDING, FEDERAL EXCLUSION)
  - "  - " lines are indicators; deeper-indented lines under them are detail
  - "  Label: value" lines in SUBJECT OF COMPLAINT are a fact table
"""
import datetime
import re

from fpdf import FPDF

NAVY = (22, 38, 66)
INK = (33, 37, 41)
MUTED = (100, 108, 118)
RULE = (205, 211, 219)
KEY_FILL = (255, 246, 222)
KEY_EDGE = (214, 158, 46)

_DEST_TITLE = {
    "doj": "DOJ Criminal Tip Rewards Pilot Program",
    "oig": "HHS-OIG Hotline",
    "mfcu": "State Medicaid Fraud Control Unit",
}

# Core PDF fonts are Latin-1 only; map the few other characters the generator uses.
_ASCII = str.maketrans({
    "—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "•": "-", "…": "...", "≥": ">=", "≤": "<=", " ": " ", "→": "->",
})


def _clean(s: str) -> str:
    return s.translate(_ASCII).encode("latin-1", "replace").decode("latin-1")


_KEEP = {"npi": "NPI", "nppes": "NPPES", "oig": "OIG", "doj": "DOJ", "mfcu": "MFCU",
         "leie": "LEIE", "medicaid": "Medicaid", "medicare": "Medicare", "cms": "CMS"}
_SMALL = {"of", "the", "and", "to", "in", "for", "on", "a", "an", "this", "by"}


def _nice(label: str, title: bool = False) -> str:
    """'SUBJECT OF COMPLAINT' -> 'Subject of Complaint'; keeps acronyms."""
    out = []
    for i, w in enumerate(label.strip().split()):
        core = w.strip("(),").lower()
        if core in _KEEP:
            out.append(w.lower().replace(core, _KEEP[core]))
        elif i and (core in _SMALL or not title):
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


_HEADING = re.compile(r"^[A-Z][A-Z0-9 /&()'.,-]{3,}(\(\d+\))?$")


def _blocks(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Split the narrative into header lines and (heading, lines) sections."""
    lines = text.replace("\r\n", "\n").split("\n")
    header: list[str] = []
    i = 0
    while i < len(lines) and lines[i].strip():
        header.append(lines[i].strip())
        i += 1
    sections: list[tuple[str, list[str]]] = []
    for ln in lines[i:]:
        if ln and not ln.startswith(" ") and _HEADING.match(ln.strip()):
            sections.append((ln.strip(), []))
        elif sections:
            sections[-1][1].append(ln.rstrip())
        elif ln.strip():
            header.append(ln.strip())
    return header, sections


class _Doc(FPDF):
    def __init__(self, footer_left: str):
        super().__init__(format="letter", unit="mm")
        self.footer_left = footer_left
        self.set_margins(20, 18, 20)
        self.set_auto_page_break(True, 20)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*RULE)
        self.line(20, self.get_y() - 2, self.w - 20, self.get_y() - 2)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _clean(self.footer_left), align="L")
        self.set_x(20)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")


def _para(pdf: _Doc, text: str, size=9.5, style="", color=INK, indent=0.0, gap=1.2):
    pdf.set_x(pdf.l_margin + indent)
    pdf.set_font("Helvetica", style, size)
    pdf.set_text_color(*color)
    pdf.multi_cell(pdf.epw - indent, size * 0.47, _clean(text), align="L")
    pdf.ln(gap)


def _join(lines: list[str]) -> list[str]:
    """Re-flow hard-wrapped lines into paragraphs (blank line = break)."""
    out, cur = [], []
    for ln in lines:
        if ln.strip():
            # "Corroborating witness: ..." after a wrapped line starts its own paragraph.
            if cur and re.match(r"^[A-Z][A-Za-z ]{2,30}:", ln.strip()):
                out.append(" ".join(cur)); cur = []
            cur.append(ln.strip())
        elif cur:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _callout(pdf: _Doc, lines: list[str]):
    body = " ".join(l.strip() for l in lines).strip()
    body = body.removeprefix("**").removesuffix("**").strip()
    title, _, rest = body.partition(":")
    # Keep "Amount ..." and "Legal basis" on their own lines.
    parts = re.split(r"\s+(?=Amount |Legal basis:)", rest.strip())
    pdf.ln(1)
    x, y0, w = pdf.l_margin, pdf.get_y(), pdf.epw
    # Measure first, then draw the box behind the text.
    n = 0
    for j, p in enumerate([title.strip().upper()] + parts):
        pdf.set_font("Helvetica", "B" if j == 0 else "", 9 if j == 0 else 9.5)
        n += len(pdf.multi_cell(w - 8, 4.6, _clean(p), dry_run=True, output="LINES"))
    h = n * 4.6 + 4
    if y0 + h > pdf.page_break_trigger:
        pdf.add_page(); y0 = pdf.get_y()
    pdf.set_fill_color(*KEY_FILL)
    pdf.set_draw_color(*KEY_EDGE)
    pdf.rect(x, y0, w, h, style="F")
    pdf.set_line_width(1.2)
    pdf.line(x, y0, x, y0 + h)
    pdf.set_line_width(0.2)
    pdf.set_xy(x, y0 + 1.5)
    _callout_text(pdf, title, parts, w)
    pdf.set_y(y0 + h + 3)


def _callout_text(pdf, title, parts, w):
    pdf.set_x(pdf.l_margin + 4)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(w - 8, 4.6, _clean(title.strip().upper()))
    for j, p in enumerate(parts):
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "B" if j and p.startswith("Amount") else "", 9.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(w - 8, 4.6, _clean(p), align="L")


def _fact_table(pdf: _Doc, rows: list[tuple[str, str]]):
    label_w = 52
    pdf.set_draw_color(*RULE)
    for k, v in rows:
        y = pdf.get_y()
        pdf.set_xy(pdf.l_margin, y + 0.8)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(label_w - 2, 4.3, _clean(k))
        y1 = pdf.get_y()
        pdf.set_xy(pdf.l_margin + label_w, y + 0.8)
        pdf.set_font("Helvetica", "B" if k.lower() in ("provider name", "npi") else "", 9.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(pdf.epw - label_w, 4.3, _clean(v))
        y2 = max(y1, pdf.get_y()) + 0.8
        pdf.line(pdf.l_margin, y2, pdf.w - pdf.r_margin, y2)
        pdf.set_y(y2)
    pdf.ln(2)


def _section(pdf: _Doc, heading: str, lines: list[str]):
    if pdf.get_y() > pdf.page_break_trigger - 25:
        pdf.add_page()
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 6, _clean(_nice(heading, title=True)),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.4)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 30, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(2.5)

    i = 0
    facts: list[tuple[str, str]] = []
    plain: list[str] = []

    def flush():
        nonlocal facts, plain
        if facts:
            _fact_table(pdf, facts); facts = []
        for p in _join(plain):
            _para(pdf, p)
        plain = []

    fact_section = heading.startswith("SUBJECT")
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("**"):
            flush()
            block = [s]
            while not block[-1].endswith("**") or len(block[-1]) <= 2 and len(block) == 1:
                i += 1
                if i >= len(lines):
                    break
                block.append(lines[i].strip())
            _callout(pdf, block)
        elif s.startswith("- ") and ln.startswith("  -"):
            flush()
            name, _, rest = s[2:].partition(":")
            details = []
            while i + 1 < len(lines) and lines[i + 1].startswith("      "):
                i += 1
                details.append(lines[i].strip())
            _bullet(pdf, name, rest.strip(), details)
        elif fact_section and ":" in s and not s.endswith(":"):
            k, _, v = s.partition(":")
            facts.append((k.strip(), v.strip()))
        elif re.match(r"^[A-Z][A-Z /&-]{6,}(\([a-z ]+\))?:", s):
            flush()
            k, _, v = s.partition(":")
            sub = []
            while i + 1 < len(lines) and lines[i + 1].startswith("    ") and lines[i + 1].strip():
                i += 1
                sub.append(lines[i].strip())
            _label_line(pdf, k, v.strip(), sub)
        else:
            plain.append(ln)
        i += 1
    flush()


def _bullet(pdf: _Doc, name: str, finding: str, details: list[str]):
    if pdf.get_y() > pdf.page_break_trigger - 18:  # never strand a name at the page foot
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_fill_color(*NAVY)
    pdf.rect(pdf.l_margin + 1, y + 1.6, 1.4, 1.4, style="F")
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(*INK)
    pdf.multi_cell(pdf.epw - 5, 4.5, _clean(name.strip()))
    if finding:
        _para(pdf, finding, size=9.5, indent=5, gap=0.3)
    for d in details:
        _para(pdf, d, size=8, color=MUTED, indent=5, gap=0.3)
    pdf.ln(1.8)


def _label_line(pdf: _Doc, label: str, value: str, sub: list[str]):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(pdf.epw, 4.3, _clean(_nice(label)))
    _para(pdf, value, size=10, style="B", gap=0.3)
    for s in sub:
        _para(pdf, s, size=8, color=MUTED, gap=0.3)
    pdf.ln(1.2)


def narrative_pdf(text: str, *, npi: str, provider_name: str = "",
                  destination: str = "doj", contact: dict | None = None) -> bytes:
    header, sections = _blocks(text)
    today = datetime.date.today().isoformat()
    program = _DEST_TITLE.get(destination, "Referral")
    pdf = _Doc(f"{program}  |  NPI {npi}  |  Prepared {today} from public CMS/HHS data")
    pdf.set_title(_clean(f"Suspected Medicaid provider fraud - {provider_name or npi}"))
    pdf.set_author(_clean((contact or {}).get("name") or "Medicaid Inspector"))
    pdf.alias_nb_pages()
    pdf.add_page()

    # Title band
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, 34, style="F")
    pdf.set_xy(20, 9)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(190, 203, 222)
    pdf.cell(0, 4, _clean(program.upper()), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, "Report of Suspected Medicaid Provider Fraud", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(220, 228, 240)
    pdf.cell(0, 5, _clean(f"{provider_name or 'Provider'}  |  NPI {npi}  |  {today}"))
    pdf.set_y(42)

    # Header lines other than the program title (portal, prior filings)
    for h in header[1:]:
        _para(pdf, h, size=8.5, color=MUTED, gap=0.6)
    if contact and any(contact.values()):
        bits = [contact.get(k) for k in ("name", "email", "phone") if contact.get(k)]
        _para(pdf, "Submitted by: " + "  |  ".join(bits), size=8.5, color=MUTED, gap=0.6)
    pdf.ln(2)

    for heading, lines in sections:
        _section(pdf, heading, lines)
    return bytes(pdf.output())
