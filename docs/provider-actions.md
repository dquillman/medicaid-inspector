# Provider page — action buttons

What each button on the provider detail page does, and why it exists.
Six buttons, deliberately: this list was cut from eight on 2026-07-25 (see
"Removed" at the bottom) because two of them no longer earned their place.

The one distinction to keep straight:

> **OIG Hotline Tip is what you SUBMIT. Referral Packet is what you KEEP.**

OIG and state MFCU intake are online forms whose main field is a free-text
allegation box, so the copy-paste **narrative** is the submission. The packet is
the evidence record — useful as an attachment or your own case file, but it is
not the thing that gets filed. (An older version of the on-board workflow panel
called the packet "your submission document." That was wrong and cost real time
during the first live filing.)

---

## 1. Investigate → `/providers/{npi}/investigate`

Full investigation narrative: every fired signal with its proof box (claims per
beneficiary, peer mean, z-score), the regulatory statutes behind each, and
recommended next actions.

**Why:** the "read the evidence" step. This is where you decide whether a lead is
real before spending time on it.

## 2. Trace Ownership → `/providers/{npi}/ownership`

Ownership network — shared addresses, co-located providers, common authorized
officials, sibling NPIs under one operator.

**Why:** how you find rings. On the first live case it surfaced that the
authorized official controlled five sibling NPIs totalling ~$79.6M — context
that exists nowhere else in the app. A single NPI can look modest while the
cluster behind it does not.

## 3. Refer to MFCU → `/providers/{npi}/referral`

State referral flow. Auto-detects the provider's state, names that state's
Medicaid Fraud Control Unit (19 states have verified filing URLs; the rest get a
lookup link flagged "verify before filing"), and pre-fills the referral.

**Why:** MFCU is the **state** channel and is separate from federal OIG. States
prosecute Medicaid fraud directly. Some cases belong there instead of — or in
addition to — OIG. If filing both, file OIG first, then MFCU.

## 4. Referral Packet (PDF)

Renders the full evidence document (executive summary, all signals with
methodology and citations, billing timeline, exclusion checks, network findings)
and opens the print dialog → **Save as PDF**.

**Why:** the durable **evidence record**. Attach it where attachments are
accepted (OIG's "Helpful documents" step takes pdf/doc/xls/images — **not**
`.html`), email it to a state MFCU, or keep it as your case file.

Implementation note: it prints from a hidden iframe, not a pop-up window — a
pop-up is blocked whenever the user has pop-ups disabled, and a `window.open()`
after an `await` loses the user-gesture context and is blocked outright.

## 5. OIG Hotline Tip  ← primary action

Generates the referral narrative **plus a filing guide derived for this specific
provider** (which option to choose on each screen of the OIG wizard: allegation
type from the fired signals, program type and subject category from the
taxonomy, date from the last billed month, business-vs-individual from the NPPES
entity type). Auto-saves to the case as an append-only note.

**Why:** this is **the submission** — the text pasted into tips.oig.hhs.gov. It
is styled as the primary (amber) button because it is the output the whole app
exists to produce. Paste starting at `SUBJECT OF COMPLAINT`; everything above
the COPY line is guidance for you, not for OIG.

## 6. Add to Watchlist

Adds the provider to the watchlist with an alert threshold.

**Why:** for providers not worth working now but worth knowing about if their
risk climbs. Monitoring, not investigation.

---

## Removed 2026-07-25 (and why)

- **Referral Packet (HTML)** — superseded by the PDF button, which opens the
  same document. `.html` is not an accepted attachment at OIG or any MFCU, so
  the raw file had no remaining use.
- **Export Fraud Package** (`.tar.gz` archive) — nothing in the referral
  workflow consumed it.

## Layout note

All six live in one `flex flex-wrap justify-end` row. They previously rendered
as three buttons in a flex div followed by loose siblings inside a
`flex-col items-end` parent, so each extra button took its own right-aligned
line and they stair-stepped down the page. Keep new actions inside that row.
