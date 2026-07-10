"""
Referral-packet assembler.

Builds a single STRUCTURED packet dict for a provider by REUSING the fraud
signal, timeline, exclusion, ownership-network and narrative data the app has
already computed elsewhere — nothing here recomputes a score or re-scans the
dataset. `build_referral_packet()` returns pure data (testable, format-agnostic);
`render_referral_html()` turns that data into the print-ready HTML the app ships.

Data reused (never recomputed):
  - fraud signals + risk score .......... provider dict (signal_results / flags)
  - per-signal methodology + citations .. services.narrative_generator._SIGNAL_META
  - per-signal threshold / proof ........ routes.providers.provider_signal_evidence (best-effort)
  - exclusion status (LEIE/SAM/NPI) ..... core.exclusion_aggregator.check_all_exclusions
  - ownership network + cluster risk .... routes.providers.get_ownership_chain
  - plain-English narrative ............. services.narrative_generator.generate_narrative
  - HCPCS + monthly timeline ............ provider dict (slim-cache enriched by caller)
"""
from __future__ import annotations

import html as _html
import logging
from datetime import datetime as _dt

logger = logging.getLogger(__name__)


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _fmt(v: float) -> str:
    v = float(v or 0)
    if v >= 1e9: return f"${v / 1e9:.2f}B"
    if v >= 1e6: return f"${v / 1e6:.2f}M"
    if v >= 1e3: return f"${v / 1e3:.0f}K"
    return f"${v:.2f}"


# ── Assembly ──────────────────────────────────────────────────────────────────

async def build_referral_packet(npi: str, *, provider: dict) -> dict:
    """Assemble the structured referral packet for `provider` (already fetched &
    slim-cache-enriched by the caller). Every enrichment is best-effort: a
    failure in one source degrades that section, never the whole packet."""
    from core.risk_utils import classify_risk
    from services.narrative_generator import _SIGNAL_META

    nppes = provider.get("nppes") or {}
    addr = nppes.get("address") or {}
    tax = nppes.get("taxonomy") or {}
    auth_official = nppes.get("authorized_official") or {}

    tp = float(provider.get("total_paid") or 0)
    tc = int(provider.get("total_claims") or 0)
    tb = int(provider.get("total_beneficiaries") or 0)
    risk_score = float(provider.get("risk_score") or 0)
    risk_label, risk_color = classify_risk(risk_score)

    signals = provider.get("signal_results") or provider.get("flags") or []
    flagged = [s for s in signals if s.get("flagged")]

    # ── Per-signal: methodology + citations (+ best-effort threshold/proof) ──
    signal_items = []
    all_citations: list[str] = []
    for s in signals:
        key = s.get("signal", "")
        meta = _SIGNAL_META.get(key, {})
        cites = meta.get("citations", []) if s.get("flagged") else []
        for c in cites:
            if c not in all_citations:
                all_citations.append(c)
        signal_items.append({
            "key": key,
            "label": meta.get("label") or key.replace("_", " ").title(),
            "flagged": bool(s.get("flagged")),
            "score": float(s.get("score") or 0),
            "weight": s.get("weight", 0),
            "reason": s.get("reason", ""),          # the computed proof text
            "methodology": meta.get("explanation", ""),
            "citations": cites,
        })

    # ── Exclusions — one call covers OIG LEIE + SAM.gov + NPI status ──────────
    exclusions = {"checks": [], "any_excluded": False, "risk_level": "unknown"}
    try:
        from core.exclusion_aggregator import check_all_exclusions
        exclusions = await check_all_exclusions(npi, nppes.get("name", "") or "")
    except Exception:
        logger.warning("referral: exclusion check failed for %s", npi, exc_info=True)

    # ── Ownership network + cluster risk ─────────────────────────────────────
    network = None
    try:
        from routes.providers import get_ownership_chain
        network = await get_ownership_chain(npi)
    except Exception:
        logger.warning("referral: ownership chain failed for %s", npi, exc_info=True)

    # ── Plain-English narrative (reuse the case-narrative generator) ──────────
    narrative = None
    try:
        from services.narrative_generator import generate_narrative
        narrative = generate_narrative(npi, provider_override=provider)
    except Exception:
        logger.warning("referral: narrative generation failed for %s", npi, exc_info=True)

    # ── Recommendation (mirrors the app's risk bands) ────────────────────────
    if risk_score >= 50:
        rec_level = "RECOMMENDED FOR IMMEDIATE REFERRAL TO MFCU / OIG"
    elif risk_score >= 25:
        rec_level = "RECOMMENDED FOR FURTHER INVESTIGATION"
    else:
        rec_level = "LOW RISK — CONTINUE MONITORING"

    return {
        "npi": npi,
        "generated_at": _dt.now().strftime("%Y-%m-%d %H:%M UTC"),
        "provider": {
            "name": nppes.get("name") or provider.get("provider_name") or f"NPI {npi}",
            "entity_type": "Organization" if nppes.get("entity_type") == "NPI-2" else "Individual Provider",
            "address": addr,
            "specialty": tax.get("description") or tax.get("desc") or "",
            "taxonomy_code": tax.get("code") or "",
            "authorized_official": {"name": auth_official.get("name", ""), "title": auth_official.get("title", "")},
            "enumeration_date": nppes.get("enumeration_date", ""),
            "nppes_status": nppes.get("status", ""),
        },
        "risk": {
            "score": risk_score, "label": risk_label, "color": risk_color,
            "flagged_count": len(flagged), "total_signals": len(signals),
            "first_month": provider.get("first_month") or "",
            "last_month": provider.get("last_month") or "",
            "active_months": provider.get("active_months") or 0,
        },
        "billing": {
            "total_paid": tp, "total_claims": tc, "total_beneficiaries": tb,
            "avg_per_claim": (tp / tc) if tc else 0,
            "revenue_per_beneficiary": float(provider.get("revenue_per_beneficiary") or (tp / tb if tb else 0)),
            "claims_per_beneficiary": float(provider.get("claims_per_beneficiary") or (tc / tb if tb else 0)),
        },
        "exclusions": exclusions,
        "signals": signal_items,
        "timeline": provider.get("timeline") or [],
        "hcpcs": provider.get("hcpcs") or [],
        "hcpcs_summary": {
            "distinct_hcpcs": provider.get("distinct_hcpcs") or 0,
            "top_hcpcs": provider.get("top_hcpcs") or "",
        },
        "network": network,
        "narrative": narrative,
        "citations": all_citations,
        "recommendation": {
            "level": rec_level,
            "any_excluded": bool(exclusions.get("any_excluded")),
        },
        "review": provider.get("_review_item"),
    }


# ── Rendering (structured dict -> print-ready HTML) ───────────────────────────

def _timeline_svg(timeline: list) -> str:
    """Inline SVG bar chart of monthly paid $ — self-contained (no external
    deps), so the anomaly is visible at a glance in the packet/PDF. The peak
    month is highlighted red."""
    rows = [t for t in timeline if t]
    if len(rows) < 2:
        return ""
    vals = [float(t.get("total_paid") or 0) for t in rows]
    peak = max(vals) or 1
    n = len(rows)
    bw = max(4, min(28, int(680 / n)))
    gap = 3
    chart_h = 120
    width = n * (bw + gap) + 40
    bars = []
    for i, (t, v) in enumerate(zip(rows, vals)):
        h = max(1, int((v / peak) * (chart_h - 10)))
        x = 30 + i * (bw + gap)
        y = chart_h - h
        color = "#dc2626" if v >= peak * 0.999 else "#3b82f6"
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bw}" height="{h}" fill="{color}" rx="1">'
            f'<title>{_esc(t.get("month",""))}: {_fmt(v)}</title></rect>'
        )
    peak_i = vals.index(peak)
    labels = []
    for i in sorted({0, peak_i, n - 1}):
        x = 30 + i * (bw + gap) + bw / 2
        labels.append(
            f'<text x="{x:.0f}" y="{chart_h + 12}" font-size="8" fill="#6b7280" '
            f'text-anchor="middle">{_esc(rows[i].get("month",""))}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {chart_h + 18}" width="100%" '
        f'style="max-width:720px;margin:8px 0" role="img" '
        f'aria-label="Monthly paid amount bar chart">'
        f'<line x1="30" y1="{chart_h}" x2="{width}" y2="{chart_h}" stroke="#e5e7eb"/>'
        f'{"".join(bars)}{"".join(labels)}'
        f'<text x="0" y="10" font-size="8" fill="#9ca3af">{_fmt(peak)}</text>'
        f'</svg>'
    )


def render_referral_html(packet: dict, *, hcpcs_descriptions: dict | None = None,
                         slim_note: str | None = None) -> str:
    """Render an assembled packet dict to the print-ready HTML the app ships."""
    hd = hcpcs_descriptions or {}
    npi = packet["npi"]
    gen = packet["generated_at"]
    prov = packet["provider"]
    risk = packet["risk"]
    bill = packet["billing"]
    addr = prov.get("address") or {}
    rs = float(risk["score"])
    head_color = "#fca5a5" if rs >= 50 else "#fbbf24" if rs >= 25 else "#86efac"

    # 3. Exclusion status — OIG LEIE + SAM.gov + NPI status, from one check.
    excl = packet.get("exclusions") or {}
    excl_rows = ""
    for c in excl.get("checks", []):
        st = (c.get("status") or "").lower()
        color = "#dc2626" if st == "excluded" else "#166534" if st == "clear" else "#6b7280"
        bg = "#fef2f2" if st == "excluded" else "#f0fdf4" if st == "clear" else "#f9fafb"
        msg = (c.get("details") or {}).get("message", "") or st.title()
        excl_rows += (
            f'<tr><td style="width:140px"><strong>{_esc(c.get("source",""))}</strong></td>'
            f'<td><span style="background:{bg};color:{color};padding:2px 10px;border-radius:4px;'
            f'font-weight:bold;font-size:12px">{_esc(st.upper() or "-")}</span> '
            f'<span style="color:#6b7280;font-size:12px">{_esc(msg)}</span></td></tr>'
        )
    excl_section = f'<table>{excl_rows}</table>' if excl_rows else '<p style="color:#6b7280">Exclusion status unavailable.</p>'

    # 7. Fraud signal analysis — methodology + proof + citations per signal.
    signal_cards = ""
    for s in packet["signals"]:
        is_flag = s["flagged"]
        border = "#ef4444" if is_flag else "#d1d5db"
        bg = "#fff5f5" if is_flag else "#f9fafb"
        badge = (
            '<span style="background:#fee2e2;color:#7c2d12;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold">TRIGGERED</span>'
            if is_flag else
            '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:12px">CLEAR</span>'
        )
        body = ""
        if is_flag:
            if s.get("methodology"):
                body += f'<p style="margin:8px 0 0;font-size:12px;color:#374151"><strong>Methodology:</strong> {_esc(s["methodology"])}</p>'
            if s.get("reason"):
                body += f'<p style="margin:6px 0 0;font-size:13px;color:#b91c1c"><strong>Finding (proof):</strong> {_esc(s["reason"])}</p>'
            _pts = s["score"] * float(s["weight"] or 0)
            body += (f'<p style="margin:6px 0 0;font-size:12px;color:#6b7280">'
                     f'Signal score {s["score"]:.2f} (0-1) &times; weight {s["weight"]} = {_pts:.1f} points toward the composite.</p>')
            if s.get("citations"):
                cites = "".join(f"<li>{_esc(c)}</li>" for c in s["citations"])
                body += f'<p style="margin:8px 0 2px;font-size:11px;color:#6b7280"><strong>Regulatory basis:</strong></p><ul style="margin:0;padding-left:18px;font-size:11px;color:#6b7280">{cites}</ul>'
        signal_cards += (
            f'<div style="border:1px solid {border};border-radius:8px;padding:14px 16px;margin:10px 0;background:{bg};page-break-inside:avoid">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<span style="font-weight:bold;font-size:14px">{_esc(s["label"])}</span>'
            f'<div style="display:flex;align-items:center;gap:8px">{badge}'
            f'<span style="font-size:12px;color:#6b7280">Score: {s["score"]:.2f} | Weight: {s["weight"]}</span></div></div>'
            f'{body}</div>\n'
        )

    # 6. Timeline — visual bar chart + table.
    timeline = packet.get("timeline") or []
    tl_svg = _timeline_svg(timeline)
    tl_rows = "".join(
        f"<tr><td>{_esc(t.get('month',''))}</td>"
        f"<td style='text-align:right'>{_fmt(t.get('total_paid',0))}</td>"
        f"<td style='text-align:right'>{int(t.get('total_claims',0) or 0):,}</td>"
        f"<td style='text-align:right'>{int(t.get('total_unique_beneficiaries',0) or 0):,}</td></tr>"
        for t in timeline
    )
    if tl_rows:
        timeline_section = (
            tl_svg +
            '<table><tr><th>Month</th><th style="text-align:right">Amount Paid</th>'
            '<th style="text-align:right">Claims</th><th style="text-align:right">Beneficiaries</th></tr>'
            + tl_rows + '</table>'
        )
    else:
        timeline_section = (
            '<div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:14px 16px;margin:12px 0">'
            f'<p style="margin:0;color:#92400e;font-size:13px">Monthly timeline detail is not loaded on this '
            f'deployment. Billing period {_esc(risk["first_month"]) or "-"} through '
            f'{_esc(risk["last_month"]) or "-"} ({risk["active_months"]} active months) is summarized above; '
            f'run a fresh scan or restore the full cache for the month-by-month breakdown.</p></div>'
        )

    # 5. HCPCS
    hcpcs = packet.get("hcpcs") or []
    if hcpcs:
        total = sum(h.get("total_paid", 0) for h in hcpcs) or 1
        rows = "".join(
            f"<tr><td><strong>{_esc(h.get('hcpcs_code',''))}</strong></td>"
            f"<td>{_esc(hd.get(h.get('hcpcs_code',''),'')) or '<em style=color:#9ca3af>-</em>'}</td>"
            f"<td style='text-align:right'>{_fmt(h.get('total_paid',0))}</td>"
            f"<td style='text-align:right'>{int(h.get('total_claims',0) or 0):,}</td>"
            f"<td style='text-align:right'>{float(h.get('total_paid',0))/total*100:.1f}%</td></tr>"
            for h in hcpcs[:15]
        )
        hcpcs_section = (
            '<table><tr><th>Code</th><th>Description</th><th style="text-align:right">Amount Billed</th>'
            '<th style="text-align:right">Claims</th><th style="text-align:right">% of Total</th></tr>'
            + rows + '</table>'
        )
    else:
        summ = packet.get("hcpcs_summary") or {}
        bits = ""
        if summ.get("distinct_hcpcs"):
            bits += f'<li><strong>{int(summ["distinct_hcpcs"]):,}</strong> distinct HCPCS codes billed</li>'
        if summ.get("top_hcpcs"):
            bits += f'<li>Top code: <strong>{_esc(summ["top_hcpcs"])}</strong></li>'
        hcpcs_section = (
            '<div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:14px 16px;margin:12px 0">'
            '<p style="margin:0 0 8px;color:#92400e;font-size:13px">Per-code billing detail is not loaded on this '
            'deployment; the scan-time aggregate summary is shown below.</p>'
            f'<ul style="margin:0;padding-left:20px;font-size:13px;color:#374151">{bits}</ul></div>'
            if bits else '<p style="color:#6b7280">No HCPCS data available.</p>'
        )

    # 8. Network findings
    net = packet.get("network") or {}
    controlled = net.get("controlled_npis") or []
    if net.get("official") and (net.get("official") or {}).get("name"):
        crs = net.get("cluster_risk_score")
        crs_html = (
            f'<div class="risk-banner" style="background:#f8fafc;border:1px solid #cbd5e1">'
            f'<div><p style="margin:0;font-size:13px;color:#6b7280">CLUSTER RISK SCORE</p>'
            f'<div style="font-size:32px;font-weight:bold">{crs}<span style="font-size:16px;color:#9ca3af">/100</span> '
            f'<span style="font-size:14px;color:#6b7280">{_esc(net.get("cluster_risk_band",""))}</span></div></div>'
            f'<div style="text-align:right;font-size:13px;color:#374151">'
            f'Authorized official: <strong>{_esc((net.get("official") or {}).get("name",""))}</strong><br>'
            f'{net.get("total_entities", len(controlled))} entities under this official &middot; '
            f'{_fmt(net.get("total_combined_billing",0))} combined billing</div></div>'
            if crs is not None else ""
        )
        conn_rows = "".join(
            f"<tr><td><strong>{_esc(c.get('npi',''))}</strong></td>"
            f"<td>{_esc(c.get('name',''))}</td>"
            f"<td style='text-align:right'>{float(c.get('risk_score',0) or 0):.0f}</td>"
            f"<td style='text-align:right'>{_fmt(c.get('total_paid',0))}</td></tr>"
            for c in sorted(controlled, key=lambda x: -(x.get("risk_score") or 0))[:15]
            if c.get("npi") != npi
        )
        shared = net.get("shared_addresses") or []
        shared_html = ""
        if shared:
            shared_html = '<h3>Shared Addresses</h3><ul style="font-size:12px;color:#374151">' + "".join(
                f"<li>{_esc(sa.get('address',''))} - {len(sa.get('npis',[]))} NPIs</li>" for sa in shared[:10]
            ) + "</ul>"
        network_section = (
            crs_html +
            (('<h3>Connected NPIs (shared authorized official)</h3>'
              '<table><tr><th>NPI</th><th>Name</th><th style="text-align:right">Risk</th>'
              '<th style="text-align:right">Total Paid</th></tr>' + conn_rows + '</table>') if conn_rows else
             '<p style="color:#6b7280">No other NPIs share this authorized official in the scanned data.</p>')
            + shared_html
        )
    else:
        network_section = '<p style="color:#6b7280">No authorized official on file, so no shared-official network could be traced.</p>'

    # 9. Narrative
    narr = packet.get("narrative") or {}
    narrative_section = ""
    for sec in (narr.get("sections") or []):
        narrative_section += (
            f'<h3>{_esc(sec.get("title",""))}</h3>'
            f'<p style="font-size:13px;color:#374151;white-space:pre-wrap">{_esc(sec.get("content",""))}</p>'
        )
    if not narrative_section:
        narrative_section = '<p style="color:#6b7280">Narrative summary unavailable.</p>'

    # 11. Citation trail
    cites = packet.get("citations") or []
    citation_section = (
        '<ul style="font-size:12px;color:#374151">' + "".join(f"<li>{_esc(c)}</li>" for c in cites) + '</ul>'
        if cites else '<p style="color:#6b7280">No signal-specific citations (no signals triggered).</p>'
    )

    rec = packet.get("recommendation") or {}
    slim_banner = (
        f'<div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;padding:8px 12px;margin:0 0 12px;font-size:11px;color:#92400e">Data note: {_esc(slim_note)}</div>'
        if slim_note else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Fraud Referral Packet - NPI {_esc(npi)}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;max-width:960px;margin:0 auto;padding:40px 24px;color:#111;background:#fff;line-height:1.6}}
h1{{color:#991b1b;border-bottom:3px solid #991b1b;padding-bottom:10px;margin-top:0;font-size:24px}}
h2{{color:#1f2937;margin-top:32px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;font-size:18px}}
h3{{color:#374151;margin-top:20px;font-size:15px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}}
th{{background:#f3f4f6;text-align:left;padding:8px 12px;font-weight:600;border-bottom:2px solid #d1d5db}}
td{{padding:8px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top}}
.confidential{{background:#1f2937;color:#fff;text-align:center;padding:8px;font-size:11px;letter-spacing:2px;border-radius:4px;margin-bottom:20px}}
.header-banner{{background:linear-gradient(135deg,#1e3a5f,#2d4a7a);color:#fff;border-radius:10px;padding:24px 28px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}}
.kpi{{border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;text-align:center}}
.kpi .val{{font-size:20px;font-weight:bold}}
.kpi .lbl{{font-size:10px;color:#9ca3af;text-transform:uppercase;margin-top:4px;letter-spacing:0.5px}}
.risk-banner{{border-radius:8px;padding:20px;margin:16px 0;display:flex;justify-content:space-between;align-items:center}}
.section-break{{page-break-before:always}}
@media print{{body{{padding:20px;font-size:12px}}table{{font-size:11px}}td,th{{padding:5px 8px}}}}
</style></head><body>
<div class="confidential">CONFIDENTIAL - MEDICAID FRAUD REFERRAL PACKET - FOR OFFICIAL USE ONLY</div>
{slim_banner}
<div class="header-banner">
  <div>
    <div style="font-size:10px;letter-spacing:2px;opacity:0.7;text-transform:uppercase">Medicaid Fraud Inspector</div>
    <div style="font-size:22px;font-weight:bold;margin-top:4px">Fraud Investigation Referral Packet</div>
    <div style="font-size:13px;opacity:0.8;margin-top:4px">NPI: {_esc(npi)} &nbsp;|&nbsp; Generated: {gen}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:48px;font-weight:bold;color:{head_color}">{rs:.0f}</div>
    <div style="font-size:10px;letter-spacing:1px;opacity:0.7">RISK SCORE</div>
  </div>
</div>

<h2>1. Provider Identification</h2>
<table>
<tr><th style="width:200px">Field</th><th>Value</th></tr>
<tr><td>NPI</td><td><strong>{_esc(npi)}</strong></td></tr>
<tr><td>Provider Name</td><td><strong>{_esc(prov["name"])}</strong></td></tr>
<tr><td>Entity Type</td><td>{_esc(prov["entity_type"])}</td></tr>
<tr><td>Practice Address</td><td>{_esc(addr.get('line1',''))} {_esc(addr.get('line2',''))}, {_esc(addr.get('city',''))}, {_esc(addr.get('state',''))} {_esc(addr.get('zip',''))}</td></tr>
<tr><td>Specialty</td><td>{_esc(prov["specialty"] or "-")}</td></tr>
<tr><td>Taxonomy Code</td><td>{_esc(prov["taxonomy_code"] or "-")}</td></tr>
{f'<tr><td>Authorized Official</td><td>{_esc(prov["authorized_official"]["name"])} - {_esc(prov["authorized_official"]["title"])}</td></tr>' if prov["authorized_official"]["name"] else ""}
<tr><td>NPI Enumeration Date</td><td>{_esc(prov["enumeration_date"] or "-")}</td></tr>
<tr><td>NPPES Status</td><td>{_esc(prov["nppes_status"] or "-")}</td></tr>
</table>

<h2>2. Risk Score Summary</h2>
<div class="risk-banner" style="background:{'#fef2f2;border:2px solid #fca5a5' if rs >= 50 else '#fffbeb;border:2px solid #fcd34d' if rs >= 25 else '#f0fdf4;border:2px solid #86efac'}">
<div><p style="margin:0;font-size:14px;color:#6b7280">COMPOSITE RISK SCORE</p>
<div style="font-size:48px;font-weight:bold;color:{risk['color']}">{rs:.0f}<span style="font-size:20px;color:#9ca3af">/100</span></div>
<p style="margin:8px 0 0;font-weight:bold;color:{risk['color']}">{_esc(risk['label'])}</p></div>
<div style="text-align:right">
<p style="margin:0;font-size:14px"><strong>{risk['flagged_count']}</strong> of <strong>{risk['total_signals']}</strong> fraud signals triggered</p>
<p style="color:#6b7280;font-size:13px;margin-top:4px">Billing period: {_esc(risk['first_month']) or '-'} through {_esc(risk['last_month']) or '-'}</p>
<p style="color:#6b7280;font-size:13px;margin-top:2px">Active months: {risk['active_months']}</p></div>
</div>

<h2>3. Federal Exclusion Status</h2>
{excl_section}

<h2>4. Billing Summary</h2>
<div class="kpi-grid">
<div class="kpi"><div class="val" style="color:#1d4ed8">{_fmt(bill['total_paid'])}</div><div class="lbl">Total Paid</div></div>
<div class="kpi"><div class="val">{bill['total_claims']:,}</div><div class="lbl">Total Claims</div></div>
<div class="kpi"><div class="val">{bill['total_beneficiaries']:,}</div><div class="lbl">Beneficiaries</div></div>
<div class="kpi"><div class="val">{_fmt(bill['avg_per_claim'])}</div><div class="lbl">Avg $/Claim</div></div>
</div>
<div class="kpi-grid" style="grid-template-columns:repeat(2,1fr)">
<div class="kpi"><div class="val">{_fmt(bill['revenue_per_beneficiary'])}</div><div class="lbl">Revenue / Beneficiary</div></div>
<div class="kpi"><div class="val">{bill['claims_per_beneficiary']:.1f}</div><div class="lbl">Claims / Beneficiary</div></div>
</div>

<h2>5. Top HCPCS Codes Billed</h2>
{hcpcs_section}

<h2>6. Monthly Billing Timeline</h2>
{timeline_section}

<h2 class="section-break">7. Fraud Signal Analysis</h2>
<p style="color:#6b7280;font-size:13px">Each signal is scored 0-1 and multiplied by its weight; the composite is the weighted sum capped at 100. Each triggered signal below carries its methodology, the specific finding (proof) computed for this provider, and the regulatory basis.</p>
{signal_cards or '<p style="color:#6b7280">No fraud signals available.</p>'}

<h2>8. Network Findings</h2>
{network_section}

<h2 class="section-break">9. Plain-English Narrative Summary</h2>
{narrative_section}

<h2>10. Referral Recommendation</h2>
<div style="border:2px solid {'#dc2626' if rs >= 50 else '#f59e0b' if rs >= 25 else '#22c55e'};border-radius:8px;padding:20px;margin:16px 0;background:{'#fef2f2' if rs >= 50 else '#fffbeb' if rs >= 25 else '#f0fdf4'}">
<p style="font-weight:bold;font-size:16px;margin:0 0 12px;color:{'#991b1b' if rs >= 50 else '#92400e' if rs >= 25 else '#166534'}">{_esc(rec.get('level',''))}</p>
<ul style="font-size:13px;color:#374151;margin:0;padding-left:20px">
<li>Risk Score: <strong>{rs:.0f}/100</strong> ({_esc(risk['label'])})</li>
<li>Triggered Signals: <strong>{risk['flagged_count']}</strong> of {risk['total_signals']}</li>
<li>Total Medicaid Payments: <strong>{_fmt(bill['total_paid'])}</strong> across {bill['total_claims']:,} claims</li>
{'<li style="color:#991b1b;font-weight:bold">PROVIDER IS ON A FEDERAL EXCLUSION LIST</li>' if rec.get('any_excluded') else ''}
</ul></div>

<h2>11. Source &amp; Citation Trail</h2>
<p style="font-size:12px;color:#374151">Regulatory bases for the triggered signals in this packet:</p>
{citation_section}
<p style="font-size:11px;color:#9ca3af;margin-top:12px">Data sources: CMS Medicaid Provider Utilization &amp; Payment Data (Public Use File) | NPPES | HCPCS (NLM Clinical Tables) | OIG LEIE | SAM.gov. This document is a screening tool; all findings must be verified by a qualified investigator before any enforcement action.</p>

<div style="margin-top:40px;border-top:2px solid #e5e7eb;padding-top:16px;text-align:center">
<p style="font-size:11px;color:#9ca3af;letter-spacing:1px">END OF REFERRAL PACKET - {_esc(npi)} - {gen}</p>
<p style="font-size:10px;color:#d1d5db">Medicaid Fraud Inspector</p>
</div>
</body></html>"""
