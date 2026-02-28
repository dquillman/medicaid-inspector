import io as _io
import csv as _csv
import json as _json
import tarfile as _tarfile
import html as _html
from datetime import datetime as _dt
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from data.duckdb_client import query_async, provider_aggregate_sql, get_parquet_path
from data.nppes_client import get_provider, search_providers
from services.risk_scorer import score_provider
from core.store import get_prescanned
from core.review_store import get_review_queue

router = APIRouter(prefix="/api/providers", tags=["providers"])


# ── CPT code descriptions (NLM only covers HCPCS Level II, not CPT codes) ─────
_CPT_DESCRIPTIONS: dict[str, str] = {
    # Office visits — new patient
    "99201": "Office visit, new patient, minimal",
    "99202": "Office visit, new patient, low complexity",
    "99203": "Office visit, new patient, low-moderate complexity",
    "99204": "Office visit, new patient, moderate complexity",
    "99205": "Office visit, new patient, high complexity",
    # Office visits — established patient
    "99211": "Office visit, established patient, minimal",
    "99212": "Office visit, established patient, low complexity",
    "99213": "Office visit, established patient, moderate complexity",
    "99214": "Office visit, established patient, moderate-high complexity",
    "99215": "Office visit, established patient, high complexity",
    # Preventive care — new patient
    "99381": "Preventive visit, new patient, infant",
    "99382": "Preventive visit, new patient, 1–4 years",
    "99383": "Preventive visit, new patient, 5–11 years",
    "99384": "Preventive visit, new patient, 12–17 years",
    "99385": "Preventive visit, new patient, 18–39 years",
    "99386": "Preventive visit, new patient, 40–64 years",
    "99387": "Preventive visit, new patient, 65+ years",
    # Preventive care — established patient
    "99391": "Preventive visit, established patient, infant",
    "99392": "Preventive visit, established patient, 1–4 years",
    "99393": "Preventive visit, established patient, 5–11 years",
    "99394": "Preventive visit, established patient, 12–17 years",
    "99395": "Preventive visit, established patient, 18–39 years",
    "99396": "Preventive visit, established patient, 40–64 years",
    "99397": "Preventive visit, established patient, 65+ years",
    # Mental health / psychiatry
    "90791": "Psychiatric diagnostic evaluation",
    "90792": "Psychiatric diagnostic evaluation with medical services",
    "90832": "Psychotherapy, 30 minutes",
    "90833": "Psychotherapy add-on to E&M, 30 minutes",
    "90834": "Psychotherapy, 45 minutes",
    "90836": "Psychotherapy add-on to E&M, 45 minutes",
    "90837": "Psychotherapy, 60 minutes",
    "90838": "Psychotherapy add-on to E&M, 60 minutes",
    "90839": "Psychotherapy for crisis, first 60 minutes",
    "90840": "Psychotherapy for crisis, additional 30 minutes",
    "90845": "Psychoanalysis",
    "90846": "Family psychotherapy, without patient",
    "90847": "Family psychotherapy, with patient",
    "90849": "Multiple family group psychotherapy",
    "90853": "Group psychotherapy",
    "90863": "Pharmacologic management",
    "90870": "Electroconvulsive therapy",
    # Hospital care
    "99221": "Initial hospital care, low complexity",
    "99222": "Initial hospital care, moderate complexity",
    "99223": "Initial hospital care, high complexity",
    "99231": "Subsequent hospital care, stable",
    "99232": "Subsequent hospital care, responding inadequately",
    "99233": "Subsequent hospital care, unstable",
    "99238": "Hospital discharge, 30 minutes or less",
    "99239": "Hospital discharge, more than 30 minutes",
    # Emergency department
    "99281": "Emergency dept visit, minor",
    "99282": "Emergency dept visit, low complexity",
    "99283": "Emergency dept visit, moderate complexity",
    "99284": "Emergency dept visit, moderate-high complexity",
    "99285": "Emergency dept visit, high complexity",
    # Nursing facility
    "99304": "Nursing facility care, initial, low complexity",
    "99305": "Nursing facility care, initial, moderate complexity",
    "99306": "Nursing facility care, initial, high complexity",
    "99307": "Subsequent nursing facility care, stable",
    "99308": "Subsequent nursing facility care, inadequate response",
    "99309": "Subsequent nursing facility care, significant change",
    "99310": "Subsequent nursing facility care, unstable",
    # Home health
    "99341": "Home visit, new patient, low complexity",
    "99342": "Home visit, new patient, moderate complexity",
    "99344": "Home visit, new patient, high complexity",
    "99347": "Home visit, established patient, self-limited",
    "99348": "Home visit, established patient, low complexity",
    "99349": "Home visit, established patient, moderate complexity",
    "99350": "Home visit, established patient, high complexity",
    # Lab
    "80047": "Basic metabolic panel",
    "80048": "Basic metabolic panel with calcium",
    "80053": "Comprehensive metabolic panel",
    "80061": "Lipid panel",
    "82947": "Glucose",
    "83036": "Hemoglobin A1c",
    "84443": "Thyroid stimulating hormone (TSH)",
    "85025": "Complete blood count with differential",
    "85027": "Complete blood count, automated",
    "86703": "HIV-1/HIV-2 antibody",
    "86706": "Hepatitis B surface antibody",
    "86803": "Hepatitis C antibody",
    "87491": "Chlamydia, amplified probe",
    "87591": "Gonorrhea, amplified probe",
    # Radiology
    "70553": "MRI brain, without and with contrast",
    "71046": "Chest X-ray, 2 views",
    "71250": "CT thorax, without contrast",
    "73721": "MRI knee, without contrast",
    "74177": "CT abdomen and pelvis, with contrast",
    # Therapy
    "97110": "Therapeutic exercises",
    "97112": "Neuromuscular reeducation",
    "97116": "Gait training",
    "97150": "Therapeutic procedure, group",
    "97530": "Therapeutic activities",
    "97535": "Self-care/home management training",
    # Injections / immunizations
    "90460": "Immunization administration, first component",
    "90471": "Immunization administration",
    "90472": "Immunization administration, additional injection",
    "96372": "Therapeutic injection, subcutaneous/intramuscular",
    # Screenings & counseling
    "96127": "Brief emotional/behavioral assessment",
    "99406": "Smoking cessation counseling, 3–10 minutes",
    "99407": "Smoking cessation counseling, 10+ minutes",
    "99408": "Alcohol/substance abuse screening, 15–30 minutes",
    # Chronic/transitional care
    "99490": "Chronic care management, 20 minutes",
    "99495": "Transitional care management, 14-day follow-up",
    "99496": "Transitional care management, 7-day follow-up",
}


_NUMERIC_SORT_FIELDS = {
    "total_paid", "total_claims", "total_beneficiaries",
    "distinct_hcpcs", "active_months", "revenue_per_beneficiary",
    "claims_per_beneficiary", "risk_score", "flag_count",
}
_STRING_SORT_FIELDS = {"npi", "state", "city", "provider_name"}
_VALID_SORT_FIELDS = _NUMERIC_SORT_FIELDS | _STRING_SORT_FIELDS


_SIGNAL_META: dict[str, dict] = {
    "billing_concentration": {
        "name": "Billing Concentration",
        "explanation": "Legitimate providers bill across many procedure codes reflecting their patient mix. Concentrating more than 80% of billing under a single HCPCS code suggests upcoding (billing for more expensive services than provided) or fabricated claims for a narrow set of high-reimbursement codes.",
        "evidence_files": ["hcpcs_breakdown.csv"],
        "citation": "OIG: Billing for Services Not Rendered — OEI-07-18-00260",
    },
    "revenue_per_bene_outlier": {
        "name": "Revenue Per Beneficiary Outlier",
        "explanation": "Generating significantly more revenue per patient than peers billing the same primary procedure code suggests upcoding, billing for medically unnecessary services, or inflated service volumes.",
        "evidence_files": ["hcpcs_breakdown.csv", "monthly_timeline.csv"],
        "citation": "42 CFR § 447.15; OIG Work Plan: Medicaid Payments for Services",
    },
    "claims_per_bene_anomaly": {
        "name": "Claims Per Beneficiary Anomaly",
        "explanation": "Filing an unusually high number of claims per patient compared to peers suggests unbundling (splitting services that should be billed together), medically unnecessary repeated treatments, or billing for services not provided.",
        "evidence_files": ["monthly_timeline.csv"],
        "citation": "CMS Medicaid Integrity Program; OIG: Improper Payments in Medicaid",
    },
    "billing_ramp_rate": {
        "name": "Billing Ramp Rate",
        "explanation": "A rapid, sustained billing increase exceeding 400% growth within 12 months and crossing an absolute threshold of $50,000 is a hallmark of emerging fraud schemes. Legitimate practice growth does not typically show such extreme acceleration.",
        "evidence_files": ["monthly_timeline.csv"],
        "citation": "OIG: Medicaid Fraud Control Unit Annual Report; CMS Program Integrity Manual § 4.6",
    },
    "bust_out_pattern": {
        "name": "Bust-Out Billing Pattern",
        "explanation": "A provider that rapidly ramps billing to maximum intensity then abruptly ceases operations is a classic indicator of deliberate Medicaid fraud. The perpetrators typically collect reimbursements for several months then disappear.",
        "evidence_files": ["monthly_timeline.csv"],
        "citation": "OIG Special Fraud Alert: Bust-Out Schemes; CMS Medicaid Integrity Institute",
    },
    "ghost_billing": {
        "name": "Ghost Billing",
        "explanation": "Submitting claims with zero or near-zero unique beneficiaries means services were supposedly rendered but no real patients can be identified. This strongly indicates claims were fabricated entirely.",
        "evidence_files": ["monthly_timeline.csv"],
        "citation": "OIG: Phantom Billing — OEI-01-20-00100; 42 USC § 1320a-7b(a)",
    },
    "total_spend_outlier": {
        "name": "Total Spend Outlier",
        "explanation": "Total Medicaid billing more than 3 standard deviations above the mean for all providers warrants scrutiny. In combination with other signals, extreme total spend amplifies the concern that billing volume is inflated through fraudulent means.",
        "evidence_files": ["provider_summary.json", "monthly_timeline.csv"],
        "citation": "CMS Fraud Prevention System; OIG Risk Algorithm Guidance 2023",
    },
    "billing_consistency": {
        "name": "Suspiciously Consistent Billing",
        "explanation": "Real healthcare billing naturally varies month to month based on patient flow, holidays, and illness patterns. A provider billing almost exactly the same amount every month (coefficient of variation below 0.15 over 12+ months) exhibits mechanical regularity inconsistent with organic patient care — suggesting automated or scripted claim generation.",
        "evidence_files": ["monthly_timeline.csv"],
        "citation": "CMS Medicaid Integrity Program Audit Guidelines; OIG: Automated Billing Schemes",
    },
}


def _build_report_html(provider: dict, review_item: dict | None, hcpcs_descriptions: dict[str, str]) -> str:
    npi          = provider.get("npi", "")
    nppes        = provider.get("nppes") or {}
    addr         = nppes.get("address") or {}
    tax          = nppes.get("taxonomy") or {}
    auth         = nppes.get("authorized_official") or {}
    name         = nppes.get("name") or provider.get("provider_name") or f"NPI {npi}"
    entity_type  = "Organization" if nppes.get("entity_type") == "NPI-2" else "Individual Provider"
    risk_score   = provider.get("risk_score") or 0
    signals      = provider.get("signal_results") or []
    flagged      = [s for s in signals if s.get("flagged")]

    if risk_score >= 50:   risk_label, risk_color = "HIGH RISK — Recommend Immediate Investigation", "#7c2d12"
    elif risk_score >= 40: risk_label, risk_color = "ELEVATED RISK — Recommend Review", "#9a3412"
    elif risk_score >= 10: risk_label, risk_color = "FLAGGED FOR REVIEW", "#854d0e"
    else:                  risk_label, risk_color = "LOW RISK", "#166534"

    def fmt(v: float) -> str:
        if v >= 1e9: return f"${v/1e9:.2f}B"
        if v >= 1e6: return f"${v/1e6:.2f}M"
        if v >= 1e3: return f"${v/1e3:.0f}K"
        return f"${v:.2f}"

    def esc(s) -> str:
        return _html.escape(str(s or ""))

    # HCPCS table
    hcpcs_list = provider.get("hcpcs") or []
    total_hcpcs_paid = sum(h.get("total_paid", 0) for h in hcpcs_list) or 1
    hcpcs_rows = ""
    for h in hcpcs_list[:25]:
        code = h.get("hcpcs_code", "")
        paid = h.get("total_paid", 0)
        pct  = paid / total_hcpcs_paid * 100
        desc = hcpcs_descriptions.get(code, "")
        hcpcs_rows += (
            f"<tr><td><strong>{esc(code)}</strong></td>"
            f"<td>{esc(desc) if desc else '<em style=\"color:#9ca3af\">—</em>'}</td>"
            f"<td style='text-align:right'>{fmt(paid)}</td>"
            f"<td style='text-align:right'>{h.get('total_claims',0):,}</td>"
            f"<td style='text-align:right'>{pct:.1f}%</td></tr>\n"
        )

    # Timeline table
    timeline = provider.get("timeline") or []
    timeline_rows = ""
    for t in timeline:
        timeline_rows += (
            f"<tr><td>{esc(t.get('month',''))}</td>"
            f"<td style='text-align:right'>{fmt(t.get('total_paid',0))}</td>"
            f"<td style='text-align:right'>{t.get('total_claims',0):,}</td>"
            f"<td style='text-align:right'>{t.get('total_unique_beneficiaries',0):,}</td></tr>\n"
        )

    # Signal cards
    signal_cards = ""
    for s in signals:
        key     = s.get("signal", "")
        meta    = _SIGNAL_META.get(key, {})
        is_flag = s.get("flagged", False)
        reason  = s.get("reason", "")
        border  = "#ef4444" if is_flag else "#d1d5db"
        bg      = "#fff5f5" if is_flag else "#f9fafb"
        badge   = ('<span style="background:#fee2e2;color:#7c2d12;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold">TRIGGERED</span>'
                   if is_flag else
                   '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:12px">CLEAR</span>')
        files_html = ", ".join(f"<code>{f}</code>" for f in meta.get("evidence_files", []))
        evidence   = (f'<div style="background:#eff6ff;border-left:3px solid #3b82f6;padding:8px 12px;margin-top:10px;font-size:13px">'
                      f'<strong>Supporting files:</strong> {files_html}</div>') if files_html else ""
        citation   = (f'<p style="color:#9ca3af;font-size:12px;font-style:italic;margin-top:8px">Reference: {esc(meta["citation"])}</p>'
                      if meta.get("citation") else "")
        finding    = (f'<p style="color:#b91c1c;margin:10px 0 0;font-size:13px"><strong>Finding:</strong> {esc(reason)}</p>'
                      if reason and is_flag else "")
        expl       = (f'<p style="color:#374151;margin:10px 0 0;font-size:13px">{esc(meta.get("explanation",""))}</p>'
                      if meta.get("explanation") else "")
        signal_cards += (
            f'<div style="border:1px solid {border};border-radius:8px;padding:16px;margin:12px 0;background:{bg}">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<span style="font-weight:bold;font-size:15px">{esc(meta.get("name", key))}</span>'
            f'<div style="display:flex;align-items:center;gap:8px">{badge}'
            f'<span style="font-size:13px;color:#6b7280">Score: {s.get("score",0):.2f} · Weight: {s.get("weight",0)}</span></div></div>'
            f'{finding}{expl}{evidence}{citation}</div>\n'
        )

    # Review section
    review_html = ""
    if review_item:
        status = review_item.get("status", "pending")
        notes  = review_item.get("notes", "")
        added  = review_item.get("added_at", 0)
        colors = {"pending":("#fef9c3","#854d0e"),"reviewed":("#dbeafe","#1e40af"),
                  "confirmed_fraud":("#fee2e2","#7c2d12"),"dismissed":("#f3f4f6","#374151")}
        rbg, rfg = colors.get(status, ("#f3f4f6","#374151"))
        added_str = _dt.fromtimestamp(added).strftime("%Y-%m-%d %H:%M") if added else "—"
        review_html = (
            f'<h2>Review Queue Status</h2>'
            f'<p><span style="background:{rbg};color:{rfg};padding:4px 12px;border-radius:4px;font-weight:bold">'
            f'{esc(status.replace("_"," ").title())}</span></p>'
            + (f'<p style="margin-top:8px"><strong>Notes:</strong> {esc(notes)}</p>' if notes else "")
            + f'<p style="color:#9ca3af;font-size:12px">Added to queue: {added_str}</p>'
        )

    tp   = provider.get("total_paid") or 0
    tc   = provider.get("total_claims") or 0
    tb   = provider.get("total_beneficiaries") or 0
    am   = provider.get("active_months") or 0
    rpb  = provider.get("revenue_per_beneficiary") or 0
    cpb  = provider.get("claims_per_beneficiary") or 0
    fm   = esc(provider.get("first_month") or "—")
    lm   = esc(provider.get("last_month") or "—")
    gen  = _dt.now().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Fraud Investigation Report — NPI {esc(npi)}</title>
<style>
body{{font-family:Arial,sans-serif;max-width:960px;margin:0 auto;padding:40px 24px;color:#111;background:#fff;line-height:1.5}}
h1{{color:#7c2d12;border-bottom:3px solid #7c2d12;padding-bottom:10px;margin-top:0}}
h2{{color:#1f2937;margin-top:36px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}}
th{{background:#f3f4f6;text-align:left;padding:8px 12px;font-weight:600;border-bottom:2px solid #d1d5db}}
td{{padding:8px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top}}
tr:hover td{{background:#f9fafb}}
code{{background:#f3f4f6;padding:2px 6px;border-radius:4px;font-size:12px}}
.grid{{display:grid;gap:16px;margin:16px 0}}
.kpi{{border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;text-align:center}}
.kpi .val{{font-size:22px;font-weight:bold}}
.kpi .lbl{{font-size:11px;color:#9ca3af;text-transform:uppercase;margin-top:4px}}
.banner{{background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;padding:20px;margin:20px 0;display:flex;justify-content:space-between;align-items:center}}
.file-list{{list-style:none;padding:0}}
.file-list li{{padding:8px 0;border-bottom:1px solid #f3f4f6;display:flex;gap:16px;align-items:flex-start}}
.file-list li code{{min-width:240px;display:inline-block}}
.file-list li span{{color:#6b7280;font-size:13px}}
.confidential{{background:#1f2937;color:#fff;text-align:center;padding:8px;font-size:11px;letter-spacing:2px;border-radius:4px;margin-bottom:24px}}
@media print{{body{{padding:20px}}}}
</style>
</head>
<body>
<div class="confidential">CONFIDENTIAL — MEDICAID FRAUD INVESTIGATION REPORT — FOR OFFICIAL USE ONLY</div>
<h1>Fraud Investigation Report</h1>
<p style="color:#6b7280;font-size:13px">Generated: {gen} &nbsp;|&nbsp; Medicaid Inspector &nbsp;|&nbsp; NPI: <strong>{esc(npi)}</strong></p>

<h2>Provider Identity</h2>
<table>
<tr><th style="width:200px">Field</th><th>Value</th></tr>
<tr><td>NPI</td><td><strong>{esc(npi)}</strong></td></tr>
<tr><td>Name</td><td><strong>{esc(name)}</strong></td></tr>
<tr><td>Entity Type</td><td>{esc(entity_type)}</td></tr>
<tr><td>Address</td><td>{esc(addr.get('line1',''))} {esc(addr.get('line2',''))}, {esc(addr.get('city',''))}, {esc(addr.get('state',''))} {esc(addr.get('zip',''))}</td></tr>
<tr><td>Specialty</td><td>{esc(tax.get('description','—'))}</td></tr>
<tr><td>License</td><td>{esc(tax.get('license','—'))}</td></tr>
{"<tr><td>Authorized Official</td><td>" + esc(auth.get('name','')) + " — " + esc(auth.get('title','')) + "</td></tr>" if auth.get('name') else ""}
<tr><td>NPPES Status</td><td>{esc(nppes.get('status','—'))}</td></tr>
<tr><td>Last Updated (NPPES)</td><td>{esc(nppes.get('last_updated','—'))}</td></tr>
</table>

<h2>Risk Assessment</h2>
<div class="banner">
<div>
<p style="margin:0;font-size:14px;color:#6b7280">COMPOSITE RISK SCORE</p>
<div style="font-size:48px;font-weight:bold;color:{risk_color}">{risk_score:.0f}<span style="font-size:20px;color:#9ca3af">/100</span></div>
<p style="margin:8px 0 0;font-weight:bold;color:{risk_color}">{esc(risk_label)}</p>
</div>
<div style="text-align:right">
<p style="margin:0;font-size:14px"><strong>{len(flagged)}</strong> of {len(signals)} fraud signals triggered</p>
<p style="color:#6b7280;font-size:13px;margin-top:4px">Billing period: {fm} – {lm}</p>
</div>
</div>

<h2>Financial Overview</h2>
<div class="grid" style="grid-template-columns:repeat(4,1fr)">
<div class="kpi"><div class="val">{fmt(tp)}</div><div class="lbl">Total Paid</div></div>
<div class="kpi"><div class="val">{tc:,}</div><div class="lbl">Total Claims</div></div>
<div class="kpi"><div class="val">{tb:,}</div><div class="lbl">Beneficiaries</div></div>
<div class="kpi"><div class="val">{am}</div><div class="lbl">Active Months</div></div>
</div>
<div class="grid" style="grid-template-columns:repeat(2,1fr)">
<div class="kpi"><div class="val">{fmt(rpb)}</div><div class="lbl">Revenue / Beneficiary</div></div>
<div class="kpi"><div class="val">{cpb:.1f}</div><div class="lbl">Claims / Beneficiary</div></div>
</div>

<h2>Fraud Signal Analysis</h2>
<p style="color:#6b7280;font-size:13px">Eight signals scored 0–1 and weighted. Composite score = weighted sum capped at 100. Signals marked TRIGGERED indicate anomalous behavior requiring investigation.</p>
{signal_cards}

<h2>Top Billing Codes (HCPCS)</h2>
<table>
<tr><th>Code</th><th>Description</th><th style="text-align:right">Amount Billed</th><th style="text-align:right">Claims</th><th style="text-align:right">% of Total</th></tr>
{hcpcs_rows}
</table>

<h2>Monthly Billing Timeline</h2>
<table>
<tr><th>Month</th><th style="text-align:right">Amount Paid</th><th style="text-align:right">Claims</th><th style="text-align:right">Beneficiaries</th></tr>
{timeline_rows}
</table>

{review_html}

<h2>Evidence Files in This Package</h2>
<ul class="file-list">
<li><code>fraud_investigation_report.html</code><span>This report — open in any web browser or print to PDF</span></li>
<li><code>provider_summary.json</code><span>Provider identity, financial aggregates, and risk score</span></li>
<li><code>fraud_signals.json</code><span>Machine-readable signal results with scores, weights, and reasons</span></li>
<li><code>nppes_profile.json</code><span>Full NPPES provider registration data (name, address, taxonomy, authorized official)</span></li>
<li><code>hcpcs_breakdown.csv</code><span>Procedure code billing breakdown with plain-English descriptions — import into Excel</span></li>
<li><code>monthly_timeline.csv</code><span>Month-by-month billing history — useful for visualizing ramp and bust-out patterns</span></li>
<li><code>review_status.json</code><span>Current investigation status and analyst notes from the review queue</span></li>
</ul>

<h2>Methodology</h2>
<p style="font-size:13px;color:#374151">This report was generated by the Medicaid Inspector fraud detection system. Risk scores are computed using eight signals derived from CMS Medicaid claims data (2018–2024, 220M+ rows). Each signal is scored 0–1 and multiplied by its weight; the composite is capped at 100. Thresholds are based on OIG enforcement guidance, CMS Program Integrity Manual criteria, and statistical peer comparison (z-scores vs. providers billing the same primary HCPCS code). This report is a screening tool — findings must be verified by a qualified investigator before any enforcement action.</p>
<p style="font-size:12px;color:#9ca3af">Data: CMS Medicaid Provider Utilization and Payment Data (Public Use File) | NPPES: National Plan and Provider Enumeration System | HCPCS descriptions: NLM Clinical Tables Service</p>
</body>
</html>"""


def _get_state(p: dict) -> str:
    return (p.get("state") or p.get("nppes", {}).get("address", {}).get("state") or "").upper()

def _get_city(p: dict) -> str:
    return (p.get("city") or p.get("nppes", {}).get("address", {}).get("city") or "")


@router.get("/facets")
async def get_provider_facets():
    """Return unique filterable values from the prescan cache for building filter dropdowns."""
    prescanned = get_prescanned()
    if not prescanned:
        return {"states": [], "cities": [], "flag_counts": [0], "active_months": []}

    states      = sorted(s for s in set(_get_state(p) for p in prescanned) if s)
    cities      = sorted(c for c in set(_get_city(p) for p in prescanned) if c)
    flag_counts = sorted(set(len(p.get("flags") or []) for p in prescanned))
    months      = sorted(set(int(p.get("active_months") or 0) for p in prescanned))

    return {"states": states, "cities": cities, "flag_counts": flag_counts, "active_months": months}


@router.get("")
async def list_providers(
    search: str = Query("", description="NPI or name substring"),
    # single-value legacy param kept for compatibility
    state: str = Query("", description="single state code (legacy)"),
    min_risk: float = Query(0.0),
    max_risk: float = Query(100.0),
    # multi-value comma-separated filters
    states: str = Query("", description="comma-separated state codes"),
    cities: str = Query("", description="comma-separated city names"),
    flag_counts: str = Query("", description="comma-separated flag counts"),
    min_paid: float = Query(0.0),
    max_paid: float = Query(0.0, description="0 = no upper limit"),
    min_claims: int = Query(0),
    max_claims: int = Query(0, description="0 = no upper limit"),
    min_months: int = Query(0),
    max_months: int = Query(0, description="0 = no upper limit"),
    sort_by: str = Query("total_paid"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    prescanned = get_prescanned()

    # Serve from prescan cache when available — avoids remote Parquet queries
    if prescanned:
        pool = list(prescanned)

        if search:
            q = search.lower()
            pool = [
                p for p in pool
                if q in p.get("npi", "").lower()
                or q in (p.get("provider_name") or "").lower()
                or q in (p.get("nppes", {}).get("name") or "").lower()
            ]

        # State filter — multi-value takes precedence over legacy single
        state_set = {s.strip().upper() for s in states.split(",") if s.strip()}
        if not state_set and state:
            state_set = {state.upper()}
        if state_set:
            pool = [p for p in pool if _get_state(p) in state_set]

        # City filter
        city_set = {c.strip().lower() for c in cities.split(",") if c.strip()}
        if city_set:
            pool = [p for p in pool if _get_city(p).lower() in city_set]

        # Flag count filter
        fc_set: set[int] = set()
        for fc in flag_counts.split(","):
            fc = fc.strip()
            if fc.endswith("+"):
                # "3+" means 3 or more
                try:
                    min_fc = int(fc[:-1])
                    fc_set.update(range(min_fc, 100))
                except ValueError:
                    pass
            elif fc.isdigit():
                fc_set.add(int(fc))
        if fc_set:
            pool = [p for p in pool if len(p.get("flags") or []) in fc_set]

        # Numeric range filters
        if min_risk > 0:
            pool = [p for p in pool if (p.get("risk_score") or 0) >= min_risk]
        if max_risk < 100.0:
            pool = [p for p in pool if (p.get("risk_score") or 0) <= max_risk]
        if min_paid > 0:
            pool = [p for p in pool if (p.get("total_paid") or 0) >= min_paid]
        if max_paid > 0:
            pool = [p for p in pool if (p.get("total_paid") or 0) <= max_paid]
        if min_claims > 0:
            pool = [p for p in pool if (p.get("total_claims") or 0) >= min_claims]
        if max_claims > 0:
            pool = [p for p in pool if (p.get("total_claims") or 0) <= max_claims]
        if min_months > 0:
            pool = [p for p in pool if (p.get("active_months") or 0) >= min_months]
        if max_months > 0:
            pool = [p for p in pool if (p.get("active_months") or 0) <= max_months]

        # Sort
        field = sort_by if sort_by in _VALID_SORT_FIELDS else "total_paid"
        reverse = sort_dir.lower() != "asc"
        if field == "flag_count":
            pool.sort(key=lambda p: len(p.get("flags") or []), reverse=reverse)
        elif field in _NUMERIC_SORT_FIELDS:
            pool.sort(key=lambda p: (p.get(field) or 0), reverse=reverse)
        else:
            pool.sort(key=lambda p: (p.get(field) or "").lower(), reverse=reverse)

        total = len(pool)
        offset = (page - 1) * limit
        page_slice = pool[offset: offset + limit]

        # For providers on this page that are missing NPPES data, fetch it now
        # (same approach as the detail endpoint — live fetch, then cache the result)
        missing = [p for p in page_slice if not p.get("nppes")]
        if missing:
            import asyncio as _asyncio
            from core.store import append_prescanned as _append
            fetched = await _asyncio.gather(*[get_provider(p["npi"]) for p in missing])
            to_cache = []
            for p, nppes_data in zip(missing, fetched):
                if not nppes_data:
                    continue
                addr = nppes_data.get("address", {})
                updated = dict(p)
                updated["nppes"] = nppes_data
                updated["state"] = addr.get("state", "")
                updated["city"] = addr.get("city", "")
                updated["provider_name"] = nppes_data.get("name", "")
                # Update the slice in-place so this response includes the names
                for i, s in enumerate(page_slice):
                    if s["npi"] == p["npi"]:
                        page_slice[i] = updated
                        break
                to_cache.append(updated)
            if to_cache:
                _append(to_cache)

        # Attach review status / notes from review queue
        review_by_npi = {item["npi"]: item for item in get_review_queue()}
        enriched_slice = []
        for p in page_slice:
            rev = review_by_npi.get(p["npi"])
            entry = dict(p)
            if rev:
                entry["review_status"] = rev.get("status")
                entry["review_notes"]  = rev.get("notes", "")
            enriched_slice.append(entry)

        return {"providers": enriched_slice, "page": page, "limit": limit, "total": total}

    # Fallback: query remote Parquet (no cache available yet)
    offset = (page - 1) * limit
    conditions = []
    if search and search.isdigit():
        conditions.append(f"BILLING_PROVIDER_NPI_NUM = '{search}'")

    sql = provider_aggregate_sql(
        where=" AND ".join(conditions) if conditions else "",
        limit=limit,
        offset=offset,
    )
    rows = await query_async(sql)

    scored = []
    for row in rows:
        risk_data = await score_provider(row["npi"], row)
        if risk_data["risk_score"] >= min_risk:
            scored.append({**row, **risk_data})

    return {"providers": scored, "page": page, "limit": limit, "total": len(scored)}


@router.get("/search")
async def search_by_name(q: str = Query(..., min_length=2)):
    """Search NPPES by organization/provider name."""
    return await search_providers(q)


@router.get("/{npi}")
async def get_provider_detail(npi: str):
    """Full provider profile: NPPES identity + spending summary + risk score."""
    import asyncio

    # Check prescan cache first — avoids re-querying remote Parquet
    cached = next((p for p in get_prescanned() if p["npi"] == npi), None)

    if cached:
        # Use cached NPPES if already enriched, else fetch now
        if cached.get("nppes"):
            nppes_data = cached["nppes"]
        else:
            nppes_data = await get_provider(npi)

        spending_keys = [
            "npi", "total_paid", "total_claims", "total_beneficiaries",
            "distinct_hcpcs", "active_months", "first_month", "last_month",
            "revenue_per_beneficiary", "claims_per_beneficiary",
        ]
        spending = {k: cached.get(k) for k in spending_keys}

        return {
            **cached,
            "nppes": nppes_data,
            "spending": spending,
        }

    # Fallback: provider not in cache yet — query Parquet + NPPES in parallel
    nppes_task = get_provider(npi)
    agg_sql = provider_aggregate_sql(
        where=f"BILLING_PROVIDER_NPI_NUM = '{npi}'",
        limit=1,
    )
    agg_task = query_async(agg_sql)
    nppes_data, agg_rows = await asyncio.gather(nppes_task, agg_task)

    if not agg_rows:
        raise HTTPException(404, f"NPI {npi} not found in Medicaid dataset")

    agg = agg_rows[0]
    risk_data = await score_provider(npi, agg)

    return {
        "npi": npi,
        "nppes": nppes_data,
        "spending": agg,
        **risk_data,
    }


@router.get("/{npi}/export")
async def export_provider_package(npi: str):
    """Generate a .tar.gz fraud evidence package containing an HTML report + CSV/JSON data files."""
    import httpx as _httpx
    from core.review_store import get_review_queue

    cached = next((p for p in get_prescanned() if p["npi"] == npi), None)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not found in scan cache — run a scan first")

    nppes_data = cached.get("nppes") or await get_provider(npi)

    review_items = get_review_queue()
    review_item  = next((r for r in review_items if r.get("npi") == npi), None)

    # Fetch HCPCS descriptions from NLM
    hcpcs_list = cached.get("hcpcs") or []
    codes = [h.get("hcpcs_code", "") for h in hcpcs_list if h.get("hcpcs_code")][:20]
    hcpcs_descriptions: dict[str, str] = {}
    try:
        async with _httpx.AsyncClient(timeout=5) as client:
            for code in codes:
                try:
                    url = f"https://clinicaltables.nlm.nih.gov/api/hcpcs/v3/search?terms={code}&maxList=10"
                    r   = await client.get(url)
                    d   = r.json()
                    desc = ""
                    if d[3]:
                        for item in d[3]:
                            if len(item) >= 2 and str(item[0]).upper() == code.upper():
                                desc = item[1]
                                break
                    if desc:
                        hcpcs_descriptions[code] = desc
                except Exception:
                    pass
    except Exception:
        pass

    provider = {**cached, "nppes": nppes_data}
    report_html = _build_report_html(provider, review_item, hcpcs_descriptions)

    buf    = _io.BytesIO()
    prefix = f"provider_{npi}"

    with _tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add_text(fname: str, content: str) -> None:
            data = content.encode("utf-8")
            info = _tarfile.TarInfo(name=f"{prefix}/{fname}")
            info.size = len(data)
            tar.addfile(info, _io.BytesIO(data))

        # HTML report
        add_text("fraud_investigation_report.html", report_html)

        # provider_summary.json
        summary = {
            "npi":                    npi,
            "name":                   nppes_data.get("name") or cached.get("provider_name") or "",
            "entity_type":            nppes_data.get("entity_type") or "",
            "address":                nppes_data.get("address") or {},
            "specialty":              (nppes_data.get("taxonomy") or {}).get("description") or "",
            "risk_score":             cached.get("risk_score"),
            "flag_count":             len(cached.get("flags") or []),
            "total_paid":             cached.get("total_paid"),
            "total_claims":           cached.get("total_claims"),
            "total_beneficiaries":    cached.get("total_beneficiaries"),
            "active_months":          cached.get("active_months"),
            "first_month":            cached.get("first_month"),
            "last_month":             cached.get("last_month"),
            "revenue_per_beneficiary": cached.get("revenue_per_beneficiary"),
            "claims_per_beneficiary": cached.get("claims_per_beneficiary"),
            "generated_at":           _dt.now().isoformat(),
        }
        add_text("provider_summary.json", _json.dumps(summary, indent=2, default=str))

        # fraud_signals.json
        signals_doc = {
            "npi":             npi,
            "risk_score":      cached.get("risk_score"),
            "signals":         cached.get("signal_results") or [],
            "flagged_signals": [s for s in (cached.get("signal_results") or []) if s.get("flagged")],
        }
        add_text("fraud_signals.json", _json.dumps(signals_doc, indent=2, default=str))

        # nppes_profile.json
        add_text("nppes_profile.json", _json.dumps(nppes_data, indent=2, default=str))

        # hcpcs_breakdown.csv
        csv_buf = _io.StringIO()
        w = _csv.writer(csv_buf)
        w.writerow(["hcpcs_code", "description", "total_paid", "total_claims", "pct_of_total"])
        total_hcpcs_paid = sum(h.get("total_paid", 0) for h in hcpcs_list) or 1
        for h in hcpcs_list:
            code = h.get("hcpcs_code", "")
            paid = h.get("total_paid", 0)
            w.writerow([code, hcpcs_descriptions.get(code, ""), round(paid, 2),
                        h.get("total_claims", 0), round(paid / total_hcpcs_paid * 100, 1)])
        add_text("hcpcs_breakdown.csv", csv_buf.getvalue())

        # monthly_timeline.csv
        tl_buf = _io.StringIO()
        w = _csv.writer(tl_buf)
        w.writerow(["month", "total_paid", "total_claims", "total_unique_beneficiaries"])
        for t in (cached.get("timeline") or []):
            w.writerow([t.get("month"), round(t.get("total_paid", 0), 2),
                        t.get("total_claims", 0), t.get("total_unique_beneficiaries", 0)])
        add_text("monthly_timeline.csv", tl_buf.getvalue())

        # review_status.json
        review_doc = review_item or {"npi": npi, "status": "not_in_queue", "notes": ""}
        add_text("review_status.json", _json.dumps(review_doc, indent=2, default=str))

    buf.seek(0)
    filename = f"provider_{npi}_fraud_package.tar.gz"
    return StreamingResponse(
        buf,
        media_type="application/x-tar",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{npi}/oig")
async def get_oig_status(npi: str):
    """Check if a provider NPI appears on the OIG LEIE exclusion list."""
    from core.oig_store import is_excluded, get_oig_stats
    excluded, record = is_excluded(npi)
    return {"npi": npi, "excluded": excluded, "record": record, **get_oig_stats()}


@router.get("/{npi}/cluster")
async def get_address_cluster(npi: str):
    """Return other providers at the same billing address (same-address clustering)."""
    cached = next((p for p in get_prescanned() if p["npi"] == npi), None)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not in scan cache")

    addr   = (cached.get("nppes") or {}).get("address") or {}
    zip5   = (addr.get("zip") or "").strip()[:5]
    line1  = (addr.get("line1") or "").strip().upper()

    if not zip5 or not line1:
        return {"npi": npi, "address": addr, "cluster": [], "cluster_count": 0}

    cluster = []
    for p in get_prescanned():
        if p["npi"] == npi:
            continue
        p_addr  = (p.get("nppes") or {}).get("address") or {}
        p_zip5  = (p_addr.get("zip") or "").strip()[:5]
        p_line1 = (p_addr.get("line1") or "").strip().upper()
        if p_zip5 == zip5 and p_line1 == line1:
            cluster.append({
                "npi":           p["npi"],
                "provider_name": p.get("provider_name") or (p.get("nppes") or {}).get("name") or "",
                "risk_score":    p.get("risk_score", 0),
                "total_paid":    p.get("total_paid", 0),
                "flag_count":    len(p.get("flags") or []),
                "specialty":     (p.get("nppes") or {}).get("taxonomy", {}).get("description") or "",
            })

    cluster.sort(key=lambda x: x["risk_score"], reverse=True)
    return {"npi": npi, "address": addr, "cluster": cluster, "cluster_count": len(cluster)}


@router.get("/{npi}/peers")
async def get_provider_peers(npi: str):
    """Return peer-group comparison stats (providers with same top HCPCS code)."""
    import statistics as _stats

    cached = next((p for p in get_prescanned() if p["npi"] == npi), None)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not in scan cache")

    # Determine this provider's top HCPCS code
    top_code = cached.get("top_hcpcs") or ""
    if not top_code:
        hcpcs = cached.get("hcpcs") or []
        if hcpcs:
            top_code = hcpcs[0].get("hcpcs_code", "")

    if not top_code:
        return {"npi": npi, "top_hcpcs": None, "peer_count": 0, "stats": None}

    # Gather peer values (exclude this provider)
    rpb_vals:  list[float] = []
    cpb_vals:  list[float] = []
    paid_vals: list[float] = []

    for p in get_prescanned():
        if p["npi"] == npi:
            continue
        p_code = p.get("top_hcpcs") or ""
        if not p_code:
            hl = p.get("hcpcs") or []
            if hl:
                p_code = hl[0].get("hcpcs_code", "")
        if p_code != top_code:
            continue
        rpb   = float(p.get("revenue_per_beneficiary") or 0)
        cpb   = float(p.get("claims_per_beneficiary") or 0)
        spend = float(p.get("total_paid") or 0)
        if rpb   > 0: rpb_vals.append(rpb)
        if cpb   > 0: cpb_vals.append(cpb)
        if spend > 0: paid_vals.append(spend)

    def calc_stats(vals: list[float]) -> dict | None:
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        return {
            "mean":   round(_stats.mean(s), 2),
            "median": round(_stats.median(s), 2),
            "p75":    round(s[max(0, int(n * 0.75) - 1)], 2),
            "p90":    round(s[max(0, int(n * 0.90) - 1)], 2),
            "p95":    round(s[max(0, int(n * 0.95) - 1)], 2) if n >= 20 else None,
            "count":  n,
        }

    def pct_rank(value: float, vals: list[float]) -> float | None:
        if not vals or value == 0:
            return None
        return round(sum(1 for v in vals if v < value) / len(vals) * 100, 1)

    this_rpb  = float(cached.get("revenue_per_beneficiary") or 0)
    this_cpb  = float(cached.get("claims_per_beneficiary") or 0)
    this_paid = float(cached.get("total_paid") or 0)

    return {
        "npi":        npi,
        "top_hcpcs":  top_code,
        "peer_count": len(rpb_vals),
        "this_provider": {
            "revenue_per_beneficiary": this_rpb,
            "claims_per_beneficiary":  this_cpb,
            "total_paid":              this_paid,
        },
        "rpb_stats":  calc_stats(rpb_vals),
        "cpb_stats":  calc_stats(cpb_vals),
        "paid_stats": calc_stats(paid_vals),
        "percentiles": {
            "revenue_per_beneficiary": pct_rank(this_rpb,  rpb_vals),
            "claims_per_beneficiary":  pct_rank(this_cpb,  cpb_vals),
            "total_paid":              pct_rank(this_paid, paid_vals),
        },
    }


@router.get("/{npi}/timeline")
async def get_timeline(npi: str):
    """Monthly billing timeline — served from prescan cache when available."""
    cached = next((p for p in get_prescanned() if p["npi"] == npi), None)
    if cached and cached.get("timeline"):
        return {"npi": npi, "timeline": cached["timeline"]}

    # Fallback: query Parquet (provider not yet scanned)
    sql = f"""
    SELECT
        CLAIM_FROM_MONTH                    AS month,
        SUM(TOTAL_PAID)                     AS total_paid,
        SUM(TOTAL_CLAIMS)                   AS total_claims,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)     AS total_unique_beneficiaries
    FROM read_parquet('{get_parquet_path()}')
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    GROUP BY CLAIM_FROM_MONTH
    ORDER BY CLAIM_FROM_MONTH ASC
    """
    rows = await query_async(sql)
    return {"npi": npi, "timeline": rows}


async def _fetch_hcpcs_descriptions(codes: list[str]) -> dict[str, str]:
    """Return descriptions for a list of HCPCS/CPT codes.

    Strategy:
      1. Numeric codes (CPT / HCPCS Level I) — look up in built-in dictionary.
      2. Alphanumeric codes (HCPCS Level II, e.g. S5125) — query NLM API.
    """
    import httpx as _httpx
    import asyncio as _asyncio

    results: dict[str, str] = {}
    nlm_codes: list[str] = []

    for code in codes:
        if code.isdigit():
            # CPT code — use local dictionary
            desc = _CPT_DESCRIPTIONS.get(code, "")
            if desc:
                results[code] = desc
            # If not in dict, skip NLM (it doesn't have CPT codes)
        else:
            # HCPCS Level II — queue for NLM lookup
            nlm_codes.append(code)

    if not nlm_codes:
        return results

    async def fetch_one(client: _httpx.AsyncClient, code: str) -> tuple[str, str]:
        try:
            url = (
                f"https://clinicaltables.nlm.nih.gov/api/hcpcs/v3/search"
                f"?terms={code}&maxList=10"
            )
            r = await client.get(url)
            d = r.json()
            # d[3] = [[code, description], ...] — find exact code match
            if d[3]:
                for item in d[3]:
                    if len(item) >= 2 and str(item[0]).upper() == code.upper():
                        return code, item[1]
            return code, ""
        except Exception:
            return code, ""

    async with _httpx.AsyncClient(timeout=8) as client:
        pairs = await _asyncio.gather(*[fetch_one(client, c) for c in nlm_codes])

    for code, desc in pairs:
        if desc:
            results[code] = desc

    return results


@router.get("/{npi}/hcpcs")
async def get_hcpcs(npi: str):
    """HCPCS breakdown with descriptions — served from prescan cache when available."""
    cached = next((p for p in get_prescanned() if p["npi"] == npi), None)
    if cached and cached.get("hcpcs"):
        rows = cached["hcpcs"]
    else:
        # Fallback: query Parquet (provider not yet scanned)
        sql = f"""
        SELECT
            HCPCS_CODE          AS hcpcs_code,
            SUM(TOTAL_PAID)     AS total_paid,
            SUM(TOTAL_CLAIMS)   AS total_claims,
            SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_beneficiaries
        FROM read_parquet('{get_parquet_path()}')
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
        GROUP BY HCPCS_CODE
        ORDER BY total_paid DESC
        LIMIT 20
        """
        rows = await query_async(sql)

    # Fetch descriptions for all unique codes in one concurrent batch
    codes = list({r.get("hcpcs_code", "") for r in rows if r.get("hcpcs_code")})
    descriptions = await _fetch_hcpcs_descriptions(codes)

    # Attach description to each row
    enriched = [{**r, "description": descriptions.get(r.get("hcpcs_code", ""), "")} for r in rows]
    return {"npi": npi, "hcpcs": enriched}
