"""
Referral Packet endpoint — generates a comprehensive HTML fraud investigation
referral packet suitable for printing or PDF conversion.
"""
import html as _html
import logging
from datetime import datetime as _dt

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse

from core.store import get_prescanned, get_provider_by_npi
from core.risk_utils import classify_risk
from routes.auth import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["referral"], dependencies=[Depends(require_user)])


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _fmt(v: float) -> str:
    if v >= 1e9: return f"${v / 1e9:.2f}B"
    if v >= 1e6: return f"${v / 1e6:.2f}M"
    if v >= 1e3: return f"${v / 1e3:.0f}K"
    return f"${v:.2f}"


@router.get("/{npi}/referral-packet", response_class=HTMLResponse)
async def generate_referral_packet(npi: str):
    """Generate a comprehensive HTML fraud investigation referral packet for a provider."""
    from core.review_store import get_review_item
    from core.oig_store import is_excluded as oig_is_excluded
    from data.nppes_client import get_provider
    from services.hcpcs_lookup import fetch_hcpcs_descriptions

    # ── Fetch provider from scan cache ───────────────────────────────────────
    cached = get_provider_by_npi(npi)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not found in scan cache — run a scan first")

    # ── NPPES data ───────────────────────────────────────────────────────────
    nppes = cached.get("nppes") or {}
    if not nppes:
        try:
            nppes = await get_provider(npi)
        except Exception:
            logger.warning("Failed to fetch NPPES data for NPI %s in referral packet", npi)

    addr = nppes.get("address") or {}
    tax = nppes.get("taxonomy") or {}
    auth_official = nppes.get("authorized_official") or {}
    name = nppes.get("name") or cached.get("provider_name") or f"NPI {npi}"
    entity_type = "Organization" if nppes.get("entity_type") == "NPI-2" else "Individual Provider"

    # ── Risk & signals ───────────────────────────────────────────────────────
    risk_score = cached.get("risk_score") or 0
    signals = cached.get("signal_results") or []
    flagged = [s for s in signals if s.get("flagged")]

    risk_label, risk_color = classify_risk(risk_score)

    # ── Billing stats ────────────────────────────────────────────────────────
    tp = cached.get("total_paid") or 0
    tc = cached.get("total_claims") or 0
    tb = cached.get("total_beneficiaries") or 0
    am = cached.get("active_months") or 0
    rpb = cached.get("revenue_per_beneficiary") or 0
    cpb = cached.get("claims_per_beneficiary") or 0
    fm = _esc(cached.get("first_month") or "—")
    lm = _esc(cached.get("last_month") or "—")
    avg_per_claim = tp / tc if tc else 0

    # ── HCPCS data ───────────────────────────────────────────────────────────
    hcpcs_list = cached.get("hcpcs") or []
    codes = [h.get("hcpcs_code", "") for h in hcpcs_list if h.get("hcpcs_code")][:15]
    hcpcs_descriptions = await fetch_hcpcs_descriptions(codes)

    total_hcpcs_paid = sum(h.get("total_paid", 0) for h in hcpcs_list) or 1
    hcpcs_rows = ""
    for h in hcpcs_list[:15]:
        code = h.get("hcpcs_code", "")
        paid = h.get("total_paid", 0)
        pct = paid / total_hcpcs_paid * 100
        desc = hcpcs_descriptions.get(code, "")
        hcpcs_rows += (
            f"<tr><td><strong>{_esc(code)}</strong></td>"
            f"<td>{_esc(desc) if desc else '<em style=color:#9ca3af>—</em>'}</td>"
            f"<td style='text-align:right'>{_fmt(paid)}</td>"
            f"<td style='text-align:right'>{h.get('total_claims', 0):,}</td>"
            f"<td style='text-align:right'>{pct:.1f}%</td></tr>\n"
        )

    # ── OIG exclusion ────────────────────────────────────────────────────────
    oig_excluded = False
    oig_html = ""
    try:
        excluded, rec = oig_is_excluded(npi)
        oig_excluded = excluded
        if oig_excluded and rec:
            oig_html = (
                '<div style="background:#fef2f2;border:2px solid #dc2626;border-radius:8px;padding:16px;margin:16px 0">'
                '<p style="color:#991b1b;font-weight:bold;font-size:16px;margin:0">OIG EXCLUSION LIST — PROVIDER IS EXCLUDED FROM FEDERAL HEALTHCARE PROGRAMS</p>'
                f'<p style="color:#7c2d12;font-size:13px;margin:8px 0 0">Type: {_esc(rec.get("excl_type", "—"))} | '
                f'Date: {_esc(rec.get("excl_date", "—"))} | Specialty: {_esc(rec.get("specialty", "—"))}</p>'
                '</div>'
            )
        else:
            oig_html = (
                '<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:12px 16px;margin:16px 0">'
                '<p style="color:#166534;font-weight:bold;margin:0">OIG Exclusion Check: CLEAR — Not found on OIG exclusion list</p>'
                '</div>'
            )
    except Exception:
        logger.warning("OIG exclusion check failed for NPI %s", npi, exc_info=True)
        oig_html = (
            '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;margin:16px 0">'
            '<p style="color:#6b7280;margin:0">OIG exclusion check unavailable</p>'
            '</div>'
        )

    # ── Review queue ─────────────────────────────────────────────────────────
    review_item = get_review_item(npi)
    review_html = ""
    if review_item:
        status = review_item.get("status", "pending")
        notes = review_item.get("notes", "")
        assigned = review_item.get("assigned_to", "")
        added = review_item.get("added_at", 0)
        priority = review_item.get("priority", "medium")
        colors = {
            "pending": ("#fef9c3", "#854d0e"),
            "assigned": ("#dbeafe", "#1e40af"),
            "investigating": ("#e0e7ff", "#3730a3"),
            "confirmed_fraud": ("#fee2e2", "#7c2d12"),
            "referred": ("#fce7f3", "#9d174d"),
            "dismissed": ("#f3f4f6", "#374151"),
        }
        rbg, rfg = colors.get(status, ("#f3f4f6", "#374151"))
        pri_colors = {
            "critical": ("#fee2e2", "#991b1b"),
            "high": ("#ffedd5", "#9a3412"),
            "medium": ("#fef9c3", "#854d0e"),
            "low": ("#f0fdf4", "#166534"),
        }
        pbg, pfg = pri_colors.get(priority, ("#f3f4f6", "#374151"))
        added_str = _dt.fromtimestamp(added).strftime("%Y-%m-%d %H:%M") if added else "—"
        review_html = (
            '<h2>Case Management Status</h2>'
            '<table>'
            f'<tr><td style="width:180px"><strong>Status</strong></td>'
            f'<td><span style="background:{rbg};color:{rfg};padding:4px 12px;border-radius:4px;font-weight:bold">'
            f'{_esc(status.replace("_", " ").title())}</span></td></tr>'
            f'<tr><td><strong>Priority</strong></td>'
            f'<td><span style="background:{pbg};color:{pfg};padding:4px 12px;border-radius:4px;font-weight:bold">'
            f'{_esc(priority.upper())}</span></td></tr>'
            + (f'<tr><td><strong>Assigned To</strong></td><td>{_esc(assigned)}</td></tr>' if assigned else "")
            + (f'<tr><td><strong>Analyst Notes</strong></td><td>{_esc(notes)}</td></tr>' if notes else "")
            + f'<tr><td><strong>Added to Queue</strong></td><td>{added_str}</td></tr>'
            '</table>'
        )

        # Audit trail
        trail = review_item.get("audit_trail") or []
        if trail:
            review_html += '<h3 style="margin-top:20px">Case Activity Timeline</h3><table>'
            review_html += '<tr><th>Date</th><th>Action</th><th>Detail</th></tr>'
            for entry in trail[-20:]:
                ts = entry.get("timestamp", 0)
                ts_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
                action = _esc(entry.get("action", "").replace("_", " ").title())
                note = _esc(entry.get("note", ""))
                prev = _esc(entry.get("previous_status", ""))
                new = _esc(entry.get("new_status", ""))
                detail = f"{prev} &rarr; {new}" if prev and new else note
                review_html += f'<tr><td>{ts_str}</td><td>{action}</td><td>{detail}</td></tr>'
            review_html += '</table>'
    else:
        review_html = (
            '<h2>Case Management Status</h2>'
            '<p style="color:#6b7280">This provider has not been added to the review queue.</p>'
        )

    # ── Signal evidence cards ────────────────────────────────────────────────
    signal_cards = ""
    for s in signals:
        key = s.get("signal", "")
        is_flag = s.get("flagged", False)
        reason = s.get("reason", "")
        score = s.get("score", 0)
        weight = s.get("weight", 0)
        border = "#ef4444" if is_flag else "#d1d5db"
        bg = "#fff5f5" if is_flag else "#f9fafb"
        badge = (
            '<span style="background:#fee2e2;color:#7c2d12;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold">TRIGGERED</span>'
            if is_flag else
            '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:12px">CLEAR</span>'
        )
        finding = (
            f'<p style="color:#b91c1c;margin:10px 0 0;font-size:13px"><strong>Finding:</strong> {_esc(reason)}</p>'
            if reason and is_flag else ""
        )
        signal_cards += (
            f'<div style="border:1px solid {border};border-radius:8px;padding:14px 16px;margin:10px 0;background:{bg};page-break-inside:avoid">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<span style="font-weight:bold;font-size:14px">{_esc(key.replace("_", " ").title())}</span>'
            f'<div style="display:flex;align-items:center;gap:8px">{badge}'
            f'<span style="font-size:12px;color:#6b7280">Score: {score:.2f} | Weight: {weight}</span></div></div>'
            f'{finding}</div>\n'
        )

    # ── Timeline section ─────────────────────────────────────────────────────
    timeline = cached.get("timeline") or []
    timeline_rows = ""
    for t in timeline:
        timeline_rows += (
            f"<tr><td>{_esc(t.get('month', ''))}</td>"
            f"<td style='text-align:right'>{_fmt(t.get('total_paid', 0))}</td>"
            f"<td style='text-align:right'>{t.get('total_claims', 0):,}</td>"
            f"<td style='text-align:right'>{t.get('total_unique_beneficiaries', 0):,}</td></tr>\n"
        )

    gen = _dt.now().strftime("%Y-%m-%d %H:%M UTC")

    # ── Build full HTML ──────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Fraud Referral Packet — NPI {_esc(npi)}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;max-width:960px;margin:0 auto;padding:40px 24px;color:#111;background:#fff;line-height:1.6}}
h1{{color:#991b1b;border-bottom:3px solid #991b1b;padding-bottom:10px;margin-top:0;font-size:24px}}
h2{{color:#1f2937;margin-top:32px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;font-size:18px}}
h3{{color:#374151;margin-top:20px;font-size:15px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}}
th{{background:#f3f4f6;text-align:left;padding:8px 12px;font-weight:600;border-bottom:2px solid #d1d5db}}
td{{padding:8px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top}}
tr:hover td{{background:#f9fafb}}
.header-banner{{background:linear-gradient(135deg,#1e3a5f,#2d4a7a);color:#fff;border-radius:10px;padding:24px 28px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center}}
.confidential{{background:#1f2937;color:#fff;text-align:center;padding:8px;font-size:11px;letter-spacing:2px;border-radius:4px;margin-bottom:20px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}}
.kpi{{border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;text-align:center}}
.kpi .val{{font-size:20px;font-weight:bold}}
.kpi .lbl{{font-size:10px;color:#9ca3af;text-transform:uppercase;margin-top:4px;letter-spacing:0.5px}}
.risk-banner{{border-radius:8px;padding:20px;margin:16px 0;display:flex;justify-content:space-between;align-items:center}}
.section-break{{page-break-before:always}}
@media print{{
  body{{padding:20px;font-size:12px}}
  .no-print{{display:none!important}}
  .kpi-grid{{grid-template-columns:repeat(4,1fr)}}
  h2{{margin-top:24px}}
  table{{font-size:11px}}
  td,th{{padding:5px 8px}}
}}
</style>
</head>
<body>

<div class="confidential">CONFIDENTIAL — MEDICAID FRAUD REFERRAL PACKET — FOR OFFICIAL USE ONLY</div>

<div class="header-banner">
  <div>
    <div style="font-size:10px;letter-spacing:2px;opacity:0.7;text-transform:uppercase">Medicaid Fraud Inspector</div>
    <div style="font-size:22px;font-weight:bold;margin-top:4px">Fraud Investigation Referral Packet</div>
    <div style="font-size:13px;opacity:0.8;margin-top:4px">NPI: {_esc(npi)} &nbsp;|&nbsp; Generated: {gen}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:48px;font-weight:bold;color:{'#fca5a5' if risk_score >= 50 else '#fbbf24' if risk_score >= 25 else '#86efac'}">{risk_score:.0f}</div>
    <div style="font-size:10px;letter-spacing:1px;opacity:0.7">RISK SCORE</div>
  </div>
</div>

<h2>1. Provider Identification</h2>
<table>
<tr><th style="width:200px">Field</th><th>Value</th></tr>
<tr><td>NPI</td><td><strong>{_esc(npi)}</strong></td></tr>
<tr><td>Provider Name</td><td><strong>{_esc(name)}</strong></td></tr>
<tr><td>Entity Type</td><td>{_esc(entity_type)}</td></tr>
<tr><td>Practice Address</td><td>{_esc(addr.get('line1', ''))} {_esc(addr.get('line2', ''))}, {_esc(addr.get('city', ''))}, {_esc(addr.get('state', ''))} {_esc(addr.get('zip', ''))}</td></tr>
<tr><td>Specialty</td><td>{_esc(tax.get('description') or tax.get('desc') or '—')}</td></tr>
<tr><td>Taxonomy Code</td><td>{_esc(tax.get('code', '—'))}</td></tr>
{f"<tr><td>Authorized Official</td><td>{_esc(auth_official.get('name', ''))} — {_esc(auth_official.get('title', ''))}</td></tr>" if auth_official.get('name') else ""}
<tr><td>NPI Enumeration Date</td><td>{_esc(nppes.get('enumeration_date', '—'))}</td></tr>
<tr><td>NPPES Status</td><td>{_esc(nppes.get('status', '—'))}</td></tr>
</table>

<h2>2. Risk Score Summary</h2>
<div class="risk-banner" style="background:{'#fef2f2;border:2px solid #fca5a5' if risk_score >= 50 else '#fffbeb;border:2px solid #fcd34d' if risk_score >= 25 else '#f0fdf4;border:2px solid #86efac'}">
<div>
  <p style="margin:0;font-size:14px;color:#6b7280">COMPOSITE RISK SCORE</p>
  <div style="font-size:48px;font-weight:bold;color:{risk_color}">{risk_score:.0f}<span style="font-size:20px;color:#9ca3af">/100</span></div>
  <p style="margin:8px 0 0;font-weight:bold;color:{risk_color}">{_esc(risk_label)}</p>
</div>
<div style="text-align:right">
  <p style="margin:0;font-size:14px"><strong>{len(flagged)}</strong> of <strong>{len(signals)}</strong> fraud signals triggered</p>
  <p style="color:#6b7280;font-size:13px;margin-top:4px">Billing period: {fm} through {lm}</p>
  <p style="color:#6b7280;font-size:13px;margin-top:2px">Active months: {am}</p>
</div>
</div>

{oig_html}

<h2>3. Billing Summary</h2>
<div class="kpi-grid">
<div class="kpi"><div class="val" style="color:#1d4ed8">{_fmt(tp)}</div><div class="lbl">Total Paid</div></div>
<div class="kpi"><div class="val">{tc:,}</div><div class="lbl">Total Claims</div></div>
<div class="kpi"><div class="val">{tb:,}</div><div class="lbl">Beneficiaries</div></div>
<div class="kpi"><div class="val">{_fmt(avg_per_claim)}</div><div class="lbl">Avg $/Claim</div></div>
</div>
<div class="kpi-grid" style="grid-template-columns:repeat(2,1fr)">
<div class="kpi"><div class="val">{_fmt(rpb)}</div><div class="lbl">Revenue / Beneficiary</div></div>
<div class="kpi"><div class="val">{cpb:.1f}</div><div class="lbl">Claims / Beneficiary</div></div>
</div>

<h2>4. Top HCPCS Codes Billed</h2>
<table>
<tr><th>Code</th><th>Description</th><th style="text-align:right">Amount Billed</th><th style="text-align:right">Claims</th><th style="text-align:right">% of Total</th></tr>
{hcpcs_rows}
</table>

<h2>5. Fraud Signal Analysis</h2>
<p style="color:#6b7280;font-size:13px">Each fraud signal is scored 0&ndash;1 and multiplied by its weight. The composite risk score is the weighted sum, capped at 100. Signals marked TRIGGERED indicate anomalous behavior that warrants investigation.</p>
{signal_cards}

<h2>6. Monthly Billing Timeline</h2>
{'<table><tr><th>Month</th><th style="text-align:right">Amount Paid</th><th style="text-align:right">Claims</th><th style="text-align:right">Beneficiaries</th></tr>' + timeline_rows + '</table>' if timeline_rows else '<p style="color:#6b7280">No monthly timeline data available.</p>'}

{review_html}

<h2 class="section-break">8. Referral Recommendation</h2>
<div style="border:2px solid {'#dc2626' if risk_score >= 50 else '#f59e0b' if risk_score >= 25 else '#22c55e'};border-radius:8px;padding:20px;margin:16px 0;background:{'#fef2f2' if risk_score >= 50 else '#fffbeb' if risk_score >= 25 else '#f0fdf4'}">
<p style="font-weight:bold;font-size:16px;margin:0 0 12px;color:{'#991b1b' if risk_score >= 50 else '#92400e' if risk_score >= 25 else '#166534'}">
{'RECOMMENDED FOR IMMEDIATE REFERRAL TO MFCU / OIG' if risk_score >= 50 else 'RECOMMENDED FOR FURTHER INVESTIGATION' if risk_score >= 25 else 'LOW RISK — CONTINUE MONITORING'}
</p>
<ul style="font-size:13px;color:#374151;margin:0;padding-left:20px">
<li>Risk Score: <strong>{risk_score:.0f}/100</strong> ({_esc(risk_label)})</li>
<li>Triggered Signals: <strong>{len(flagged)}</strong> of {len(signals)}</li>
<li>Total Medicaid Payments: <strong>{_fmt(tp)}</strong> across {tc:,} claims</li>
{'<li style="color:#991b1b;font-weight:bold">PROVIDER IS ON OIG EXCLUSION LIST</li>' if oig_excluded else ''}
</ul>
</div>

<h2>9. Methodology</h2>
<p style="font-size:12px;color:#374151">This referral packet was generated by the Medicaid Inspector fraud detection system. Risk scores are computed using {len(signals)} fraud detection signals derived from CMS Medicaid claims data. Each signal is scored 0&ndash;1 and multiplied by its assigned weight; the composite score is the weighted sum capped at 100. Signal thresholds are based on OIG enforcement guidance, CMS Program Integrity Manual criteria, and statistical peer comparison (z-scores vs. providers billing the same primary HCPCS code). This document is a screening tool — all findings must be verified by a qualified investigator before any enforcement action is taken.</p>
<p style="font-size:11px;color:#9ca3af">Data: CMS Medicaid Provider Utilization and Payment Data (Public Use File) | NPPES: National Plan and Provider Enumeration System | HCPCS: NLM Clinical Tables Service | OIG: Office of Inspector General LEIE</p>

<div style="margin-top:40px;border-top:2px solid #e5e7eb;padding-top:16px;text-align:center">
<p style="font-size:11px;color:#9ca3af;letter-spacing:1px">END OF REFERRAL PACKET — {_esc(npi)} — {gen}</p>
<p style="font-size:10px;color:#d1d5db">Medicaid Fraud Inspector</p>
</div>

</body>
</html>"""
