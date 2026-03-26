import io as _io
import csv as _csv
import json as _json
import re as _re
import tarfile as _tarfile
import html as _html
from datetime import datetime as _dt
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from data.duckdb_client import query_async, provider_aggregate_sql, get_parquet_path


# ── Input validation helpers (prevent SQL injection in DuckDB queries) ────────

def _validate_npi(npi: str) -> str:
    """Validate NPI is exactly 10 digits."""
    npi = npi.strip()
    if not _re.match(r'^\d{10}$', npi):
        raise HTTPException(400, f"Invalid NPI '{npi}' — must be exactly 10 digits")
    return npi


def _validate_hcpcs(code: str) -> str:
    """Validate HCPCS/CPT code is alphanumeric, 1-7 chars."""
    code = code.strip().upper()
    if not _re.match(r'^[A-Z0-9]{1,7}$', code):
        raise HTTPException(400, f"Invalid HCPCS code '{code}' — must be 1-7 alphanumeric characters")
    return code


def _validate_month(month: str) -> str:
    """Validate month is YYYY-MM format."""
    month = month.strip()
    if not _re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, f"Invalid month '{month}' — must be YYYY-MM format")
    return month
from data.nppes_client import get_provider, search_providers
from services.risk_scorer import score_provider
from core.store import get_prescanned, get_provider_by_npi
from core.review_store import get_review_queue
from core.risk_utils import classify_risk
from data.cpt_descriptions import CPT_DESCRIPTIONS
from services.hcpcs_lookup import (
    fetch_hcpcs_descriptions as _fetch_hcpcs_descriptions,
    register_cpt_descriptions as _register_cpt_descriptions,
)
from routes.auth import require_user

router = APIRouter(prefix="/api/providers", tags=["providers"], dependencies=[Depends(require_user)])


# CPT descriptions imported from data.cpt_descriptions
_CPT_DESCRIPTIONS = CPT_DESCRIPTIONS
_register_cpt_descriptions(_CPT_DESCRIPTIONS)


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
    "bene_concentration": {
        "name": "Beneficiary Concentration",
        "explanation": "An extremely high claims-per-beneficiary ratio may indicate phantom billing — submitting claims for a small number of real patients at unrealistic volumes, or billing for services never rendered to inflated patient counts.",
        "evidence_files": ["monthly_timeline.csv"],
        "citation": "OIG: Phantom Billing Schemes; CMS Program Integrity Manual § 4.19",
    },
    "upcoding_pattern": {
        "name": "Upcoding Pattern",
        "explanation": "Concentration on the highest-value E/M codes relative to peers suggests systematic upcoding — billing for more complex or expensive services than were actually provided, which inflates reimbursement.",
        "evidence_files": ["hcpcs_breakdown.csv"],
        "citation": "OIG: Upcoding of E&M Services — OEI-04-10-00180; 42 CFR § 447.15",
    },
    "address_cluster_risk": {
        "name": "Address Cluster Risk",
        "explanation": "Three or more providers sharing the same physical address raises concern for a fraud ring operating from a single location under multiple NPIs to multiply billing capacity or evade per-provider scrutiny.",
        "evidence_files": ["provider_summary.json"],
        "citation": "OIG: Co-Located Provider Fraud Rings; CMS Fraud Prevention System Address Clustering",
    },
    "oig_excluded": {
        "name": "OIG Exclusion Match",
        "explanation": "The provider appears on the OIG List of Excluded Individuals/Entities (LEIE). Federal law prohibits Medicaid payment for items or services furnished by excluded individuals. Any billing activity by an excluded provider is an automatic compliance violation.",
        "evidence_files": ["provider_summary.json"],
        "citation": "42 USC § 1320a-7; OIG LEIE; 42 CFR § 1001",
    },
    "specialty_mismatch": {
        "name": "Specialty Mismatch",
        "explanation": "Billing for procedure codes outside the provider's NPPES-registered taxonomy specialty suggests cross-specialty fraud — performing and billing for services the provider is not credentialed or trained to deliver.",
        "evidence_files": ["hcpcs_breakdown.csv", "provider_summary.json"],
        "citation": "OIG: Cross-Specialty Billing Fraud; CMS Provider Enrollment Requirements 42 CFR § 424",
    },
    "corporate_shell_risk": {
        "name": "Corporate Shell Risk",
        "explanation": "A single authorized official controlling three or more billing NPIs may indicate a corporate shell structure designed to distribute fraudulent billing across multiple entities, making detection harder and multiplying reimbursement capacity.",
        "evidence_files": ["provider_summary.json"],
        "citation": "OIG: Shell Company Fraud in Medicaid; CMS Provider Enrollment Integrity",
    },
    "dead_npi_billing": {
        "name": "Dead NPI Billing",
        "explanation": "A deactivated NPI with active Medicaid billing indicates possible identity theft — someone is using a defunct provider's credentials to submit fraudulent claims. Deactivated NPIs should have zero billing activity.",
        "evidence_files": ["provider_summary.json"],
        "citation": "OIG: Identity Theft in Provider Billing; NPPES Deactivation Records; 42 CFR § 455.23",
    },
    "new_provider_explosion": {
        "name": "New Provider Explosion",
        "explanation": "A newly enumerated NPI showing disproportionately high billing volume shortly after enrollment is a hallmark of hit-and-run fraud — enrolling specifically to extract maximum reimbursement before oversight catches up.",
        "evidence_files": ["monthly_timeline.csv", "provider_summary.json"],
        "citation": "OIG: New Provider Fraud Screening; CMS Program Integrity Manual § 15.19",
    },
    "geographic_impossibility": {
        "name": "Geographic Impossibility",
        "explanation": "When a provider's NPPES-registered practice state does not match the state where Medicaid claims are being billed, it suggests cross-state fraud — billing a state's Medicaid program from a location that cannot realistically serve that state's beneficiaries.",
        "evidence_files": ["provider_summary.json"],
        "citation": "OIG: Cross-State Billing Fraud; CMS Geographic Restriction Rules",
    },
}


def _build_signal_proof(provider: dict, hcpcs_list: list, timeline: list, signals: list) -> dict[str, str]:
    """Build HTML proof sections for each flagged signal, used in the export report."""
    import math as _m
    import html as _h
    from services.anomaly_detector import SPECIALTY_HCPCS_MAP, _EM_FAMILIES

    def _esc(s) -> str:
        return _h.escape(str(s or ""))

    def _fmt(v: float) -> str:
        if v >= 1e6: return f"${v/1e6:.2f}M"
        if v >= 1e3: return f"${v/1e3:.0f}K"
        return f"${v:.2f}"

    proof: dict[str, str] = {}
    flagged_keys = {s["signal"] for s in signals if s.get("flagged")}

    nppes = provider.get("nppes") or {}
    tp = provider.get("total_paid") or 0
    tc = provider.get("total_claims") or 0
    tb = provider.get("total_beneficiaries") or 0

    def _proof_box(title: str, body: str) -> str:
        return (
            f'<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;'
            f'padding:12px 16px;margin-top:12px">'
            f'<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px">PROOF: {_esc(title)}</p>'
            f'{body}</div>'
        )

    # Billing concentration
    if "billing_concentration" in flagged_keys and hcpcs_list:
        total = sum(h.get("total_paid", 0) for h in hcpcs_list) or 1
        rows = ""
        for h in hcpcs_list[:8]:
            code = h.get("hcpcs_code", "")
            paid = h.get("total_paid", 0)
            pct = paid / total * 100
            bar_w = min(pct, 100)
            bar_color = "#ef4444" if pct > 80 else "#f59e0b" if pct > 50 else "#3b82f6"
            rows += (
                f'<tr><td style="font-family:monospace;font-weight:bold">{_esc(code)}</td>'
                f'<td><div style="background:#e5e7eb;border-radius:4px;height:14px;width:100%">'
                f'<div style="background:{bar_color};height:14px;border-radius:4px;width:{bar_w}%"></div></div></td>'
                f'<td style="text-align:right;white-space:nowrap">{pct:.1f}%</td>'
                f'<td style="text-align:right;white-space:nowrap">{_fmt(paid)}</td></tr>'
            )
        body = f'<table style="width:100%;font-size:13px"><tr><th>Code</th><th style="width:50%">Share</th><th>%</th><th>Amount</th></tr>{rows}</table>'
        proof["billing_concentration"] = _proof_box("HCPCS Code Distribution", body)

    # Revenue per bene outlier
    if "revenue_per_bene_outlier" in flagged_keys:
        rpb = provider.get("revenue_per_beneficiary") or 0
        body = (
            f'<div style="display:flex;gap:16px">'
            f'<div style="flex:1;text-align:center;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:10px">'
            f'<div style="font-size:11px;color:#9ca3af">THIS PROVIDER</div>'
            f'<div style="font-size:24px;font-weight:bold;color:#b91c1c">{_fmt(rpb)}</div>'
            f'<div style="font-size:11px;color:#9ca3af">per beneficiary</div></div>'
            f'<div style="flex:1;text-align:center;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:10px">'
            f'<div style="font-size:11px;color:#9ca3af">PEER AVERAGE</div>'
            f'<div style="font-size:24px;font-weight:bold;color:#374151">See signal reason</div>'
            f'<div style="font-size:11px;color:#9ca3af">per beneficiary</div></div></div>'
        )
        proof["revenue_per_bene_outlier"] = _proof_box("Revenue vs Peers", body)

    # Billing ramp rate
    if "billing_ramp_rate" in flagged_keys and len(timeline) >= 6:
        max_val = max(t.get("total_paid", 0) for t in timeline[:6]) or 1
        bars = ""
        for i, t in enumerate(timeline[:6]):
            v = t.get("total_paid", 0)
            h_pct = max(int(v / max_val * 80), 2)
            color = "#ef4444" if i == 5 else "#3b82f6"
            bars += (
                f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0">'
                f'<span style="width:30px;font-size:11px;color:#6b7280">M{i+1}</span>'
                f'<div style="background:{color};height:16px;border-radius:3px;width:{h_pct}%"></div>'
                f'<span style="font-size:12px;color:#374151">{_fmt(v)}</span></div>'
            )
        proof["billing_ramp_rate"] = _proof_box("First 6 Months Billing", bars)

    # Bust-out pattern
    if "bust_out_pattern" in flagged_keys and timeline:
        values = [t.get("total_paid", 0) for t in timeline]
        max_val = max(values) or 1
        peak_idx = values.index(max(values))
        bars = ""
        for i, v in enumerate(values):
            h_pct = max(int(v / max_val * 60), 1)
            color = "#ef4444" if i == peak_idx else ("#374151" if v == 0 else "#3b82f6")
            bars += f'<div style="flex:1;background:{color};height:{h_pct}px;border-radius:2px" title="{_fmt(v)}"></div>'
        body = (
            f'<div style="display:flex;align-items:flex-end;gap:2px;height:80px;padding-top:20px">{bars}</div>'
            f'<p style="font-size:12px;color:#6b7280;margin-top:6px">Peak: {_fmt(values[peak_idx])} in month {peak_idx+1}, followed by zero-billing months</p>'
        )
        proof["bust_out_pattern"] = _proof_box("Billing Timeline — Bust-Out", body)

    # Ghost billing
    if "ghost_billing" in flagged_keys and timeline:
        ghost_months = [(t.get("month", ""), t.get("total_unique_beneficiaries", 0)) for t in timeline]
        ghost_ct = sum(1 for _, b in ghost_months if b == 12)
        cells = ""
        for m, b in ghost_months[:24]:
            bg = "#fee2e2" if b == 12 else "#f9fafb"
            fw = "bold" if b == 12 else "normal"
            cells += f'<span style="display:inline-block;padding:3px 6px;margin:2px;background:{bg};border:1px solid #e5e7eb;border-radius:3px;font-size:11px;font-weight:{fw}">{b}</span>'
        body = (
            f'<p style="font-size:13px;color:#374151">{ghost_ct} of {len(ghost_months)} months show exactly 12 beneficiaries (CMS suppression floor)</p>'
            f'<div style="margin-top:8px">{cells}</div>'
        )
        proof["ghost_billing"] = _proof_box("Monthly Beneficiary Counts", body)

    # Billing consistency
    if "billing_consistency" in flagged_keys and timeline:
        nonzero = [t.get("total_paid", 0) for t in timeline if t.get("total_paid", 0) > 0]
        if len(nonzero) >= 2:
            mean_v = sum(nonzero) / len(nonzero)
            variance = sum((v - mean_v) ** 2 for v in nonzero) / len(nonzero)
            cv = _m.sqrt(variance) / mean_v if mean_v else 0
            max_val = max(nonzero) or 1
            bars = ""
            for v in nonzero:
                h_pct = max(int(v / max_val * 60), 2)
                bars += f'<div style="flex:1;background:#f59e0b;height:{h_pct}px;border-radius:2px"></div>'
            body = (
                f'<div style="display:flex;align-items:flex-end;gap:1px;height:80px;padding-top:20px">{bars}</div>'
                f'<p style="font-size:12px;color:#6b7280;margin-top:6px">CV = {cv:.4f} (threshold &lt; 0.15) — Mean: {_fmt(mean_v)}/month across {len(nonzero)} months</p>'
            )
            proof["billing_consistency"] = _proof_box("Monthly Billing Variance", body)

    # Bene concentration
    if "bene_concentration" in flagged_keys:
        ratio = tc / tb if tb else 0
        body = (
            f'<div style="display:flex;gap:16px;text-align:center">'
            f'<div style="flex:1;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:10px">'
            f'<div style="font-size:11px;color:#9ca3af">CLAIMS</div><div style="font-size:24px;font-weight:bold">{tc:,}</div></div>'
            f'<div style="flex:1;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:10px">'
            f'<div style="font-size:11px;color:#9ca3af">BENEFICIARIES</div><div style="font-size:24px;font-weight:bold">{tb:,}</div></div>'
            f'<div style="flex:1;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:10px">'
            f'<div style="font-size:11px;color:#9ca3af">RATIO</div><div style="font-size:24px;font-weight:bold;color:#b91c1c">{ratio:.1f}</div></div></div>'
        )
        proof["bene_concentration"] = _proof_box("Claims vs Beneficiaries", body)

    # Specialty mismatch
    if "specialty_mismatch" in flagged_keys:
        tax = nppes.get("taxonomy") or {}
        taxonomy_desc = (tax.get("description") or tax.get("desc") or "").strip().rstrip(",").strip()
        matched_kw = None
        valid_pfx: list[str] = []
        for kw, pfx in SPECIALTY_HCPCS_MAP.items():
            if kw in taxonomy_desc.lower():
                matched_kw = kw
                valid_pfx = pfx
                break
        if matched_kw:
            total_hcpcs = sum(h.get("total_paid", 0) for h in hcpcs_list) or 1
            inside_rows = ""
            outside_rows = ""
            for h in hcpcs_list[:15]:
                code = h.get("hcpcs_code", "")
                paid = h.get("total_paid", 0)
                is_in = any(code.startswith(p) for p in valid_pfx)
                row = f'<tr><td style="font-family:monospace">{_esc(code)}</td><td style="text-align:right">{_fmt(paid)}</td><td style="text-align:right">{paid/total_hcpcs*100:.1f}%</td></tr>'
                if is_in:
                    inside_rows += row
                else:
                    outside_rows += row
            body = (
                f'<p style="font-size:13px;color:#374151;margin-bottom:8px">Specialty: <strong>{_esc(taxonomy_desc)}</strong> (keyword: {_esc(matched_kw)})</p>'
                f'<div style="display:flex;gap:12px">'
                f'<div style="flex:1"><p style="font-size:11px;color:#166534;font-weight:bold;margin-bottom:4px">WITHIN SPECIALTY</p>'
                f'<table style="width:100%;font-size:12px"><tr><th>Code</th><th>Paid</th><th>%</th></tr>{inside_rows or "<tr><td colspan=3><em>None</em></td></tr>"}</table></div>'
                f'<div style="flex:1"><p style="font-size:11px;color:#b91c1c;font-weight:bold;margin-bottom:4px">OUTSIDE SPECIALTY</p>'
                f'<table style="width:100%;font-size:12px"><tr><th>Code</th><th>Paid</th><th>%</th></tr>{outside_rows or "<tr><td colspan=3><em>None</em></td></tr>"}</table></div></div>'
            )
            proof["specialty_mismatch"] = _proof_box("Specialty Code Analysis", body)

    # Upcoding
    if "upcoding_pattern" in flagged_keys and hcpcs_list:
        code_claims = {h.get("hcpcs_code", ""): float(h.get("total_claims") or h.get("total_paid") or 0) for h in hcpcs_list}
        for fam_name, fam_codes in _EM_FAMILIES.items():
            fam_claims = {c: code_claims.get(c, 0) for c in fam_codes}
            fam_total = sum(fam_claims.values())
            if fam_total < 10:
                continue
            top_code = fam_codes[-1]
            top_pct = fam_claims[top_code] / fam_total * 100 if fam_total else 0
            if top_pct > 50:
                cells = ""
                for c in fam_codes:
                    v = fam_claims[c]
                    pct = v / fam_total * 100 if fam_total else 0
                    bg = "#fee2e2" if pct > 50 else "#f9fafb"
                    cells += (
                        f'<div style="flex:1;text-align:center;padding:6px;background:{bg};border:1px solid #e5e7eb;border-radius:4px">'
                        f'<div style="font-family:monospace;font-size:12px">{c}</div>'
                        f'<div style="font-weight:bold;font-size:16px">{pct:.0f}%</div></div>'
                    )
                body = (
                    f'<p style="font-size:13px;color:#374151;margin-bottom:8px">Family: {_esc(fam_name)} ({fam_total:.0f} claims)</p>'
                    f'<div style="display:flex;gap:6px">{cells}</div>'
                )
                proof["upcoding_pattern"] = _proof_box("E/M Code Distribution", body)
                break

    # Address cluster
    if "address_cluster_risk" in flagged_keys:
        addr = nppes.get("address") or {}
        zip5 = (addr.get("zip") or "")[:5]
        line1 = (addr.get("line1") or "").upper().strip()
        co_located = []
        if zip5 and line1:
            for p in get_prescanned():
                if p["npi"] == provider.get("npi"):
                    continue
                pa = (p.get("nppes") or {}).get("address") or {}
                if (pa.get("zip", "")[:5] == zip5 and (pa.get("line1") or "").upper().strip() == line1):
                    co_located.append(p)
        if co_located:
            rows = ""
            for p in co_located[:10]:
                pname = (p.get("nppes") or {}).get("name") or p.get("provider_name", "Unknown")
                rows += f'<tr><td style="font-family:monospace">{_esc(p["npi"])}</td><td>{_esc(pname)}</td><td style="text-align:right">{p.get("risk_score",0)}</td><td style="text-align:right">{_fmt(p.get("total_paid",0))}</td></tr>'
            body = (
                f'<p style="font-size:13px;color:#374151;margin-bottom:8px">Address: {_esc(addr.get("line1",""))}, {_esc(addr.get("city",""))}, {_esc(addr.get("state",""))} {_esc(zip5)}</p>'
                f'<table style="width:100%;font-size:12px"><tr><th>NPI</th><th>Name</th><th>Risk</th><th>Paid</th></tr>{rows}</table>'
            )
            proof["address_cluster_risk"] = _proof_box(f"{len(co_located)+1} Providers at Same Address", body)

    # Corporate shell
    if "corporate_shell_risk" in flagged_keys:
        auth = nppes.get("authorized_official") or {}
        auth_name = (auth.get("name") or "").lower().strip()
        siblings = []
        if auth_name:
            for p in get_prescanned():
                if p["npi"] == provider.get("npi"):
                    continue
                pa = (p.get("nppes") or {}).get("authorized_official") or {}
                if (pa.get("name") or "").lower().strip() == auth_name:
                    siblings.append(p)
        if siblings:
            rows = ""
            for p in siblings[:10]:
                pname = (p.get("nppes") or {}).get("name") or p.get("provider_name", "Unknown")
                rows += f'<tr><td style="font-family:monospace">{_esc(p["npi"])}</td><td>{_esc(pname)}</td><td style="text-align:right">{p.get("risk_score",0)}</td><td style="text-align:right">{_fmt(p.get("total_paid",0))}</td></tr>'
            body = (
                f'<p style="font-size:13px;color:#374151;margin-bottom:8px">Authorized Official: <strong>{_esc(auth.get("name",""))}</strong></p>'
                f'<table style="width:100%;font-size:12px"><tr><th>NPI</th><th>Entity Name</th><th>Risk</th><th>Paid</th></tr>{rows}</table>'
            )
            proof["corporate_shell_risk"] = _proof_box(f"{len(siblings)+1} NPIs Under Same Official", body)

    # Geographic impossibility
    if "geographic_impossibility" in flagged_keys:
        nppes_state = (nppes.get("address", {}).get("state") or "").upper()
        from core.store import get_scan_progress
        billing_state = (get_scan_progress().get("state_filter") or "").upper()
        body = (
            f'<div style="display:flex;gap:16px;text-align:center">'
            f'<div style="flex:1;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:12px">'
            f'<div style="font-size:11px;color:#9ca3af">REGISTERED IN</div><div style="font-size:32px;font-weight:bold">{_esc(nppes_state)}</div></div>'
            f'<div style="flex:1;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:12px">'
            f'<div style="font-size:11px;color:#9ca3af">BILLING IN</div><div style="font-size:32px;font-weight:bold;color:#b91c1c">{_esc(billing_state)}</div></div></div>'
        )
        proof["geographic_impossibility"] = _proof_box("State Mismatch", body)

    # Dead NPI
    if "dead_npi_billing" in flagged_keys:
        status = nppes.get("status", "")
        deact_date = nppes.get("deactivation_date", "")
        body = (
            f'<div style="display:flex;gap:16px;text-align:center">'
            f'<div style="flex:1;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:12px">'
            f'<div style="font-size:11px;color:#9ca3af">NPI STATUS</div><div style="font-size:24px;font-weight:bold;color:#b91c1c">{_esc(status or "DEACTIVATED")}</div>'
            f'{f"<div style=font-size:12px;color:#6b7280>Deactivated: {_esc(deact_date)}</div>" if deact_date else ""}</div>'
            f'<div style="flex:1;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:12px">'
            f'<div style="font-size:11px;color:#9ca3af">BILLING ACTIVITY</div><div style="font-size:24px;font-weight:bold">{_fmt(tp)}</div>'
            f'<div style="font-size:12px;color:#6b7280">{tc:,} claims</div></div></div>'
        )
        proof["dead_npi_billing"] = _proof_box("Deactivated NPI with Active Billing", body)

    # New provider explosion
    if "new_provider_explosion" in flagged_keys:
        enum_date = nppes.get("enumeration_date", "")
        body = (
            f'<div style="display:flex;gap:16px;text-align:center">'
            f'<div style="flex:1;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:12px">'
            f'<div style="font-size:11px;color:#9ca3af">NPI ENUMERATED</div><div style="font-size:20px;font-weight:bold">{_esc(enum_date)}</div></div>'
            f'<div style="flex:1;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:12px">'
            f'<div style="font-size:11px;color:#9ca3af">TOTAL BILLING</div><div style="font-size:24px;font-weight:bold;color:#b91c1c">{_fmt(tp)}</div></div></div>'
        )
        proof["new_provider_explosion"] = _proof_box("New Provider — High Billing Volume", body)

    # Total spend outlier
    if "total_spend_outlier" in flagged_keys:
        body = (
            f'<p style="font-size:13px;color:#374151">This provider\'s total Medicaid payments of <strong>{_fmt(tp)}</strong> '
            f'exceed 3 standard deviations above the mean for all {len(get_prescanned()):,} scanned providers. '
            f'See signal reason for exact z-score and peer statistics.</p>'
        )
        proof["total_spend_outlier"] = _proof_box("Spend Comparison", body)

    return proof


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

    risk_label, risk_color = classify_risk(risk_score)

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
    no_desc_html = '<em style="color:#9ca3af">—</em>'
    for h in hcpcs_list[:25]:
        code = h.get("hcpcs_code", "")
        paid = h.get("total_paid", 0)
        pct  = paid / total_hcpcs_paid * 100
        desc = hcpcs_descriptions.get(code, "")
        hcpcs_rows += (
            f"<tr><td><strong>{esc(code)}</strong></td>"
            f"<td>{esc(desc) if desc else no_desc_html}</td>"
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

    # Signal cards — build proof data for flagged signals
    signal_proof = _build_signal_proof(provider, hcpcs_list, timeline, signals)

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
        proof_html = signal_proof.get(key, "")
        signal_cards += (
            f'<div style="border:1px solid {border};border-radius:8px;padding:16px;margin:12px 0;background:{bg}">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<span style="font-weight:bold;font-size:15px">{esc(meta.get("name", key))}</span>'
            f'<div style="display:flex;align-items:center;gap:8px">{badge}'
            f'<span style="font-size:13px;color:#6b7280">Score: {s.get("score",0):.2f} · Weight: {s.get("weight",0)}</span></div></div>'
            f'{finding}{expl}{proof_html}{evidence}{citation}</div>\n'
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
<div style="text-align:center;margin-bottom:16px">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" style="display:inline-block">
  <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
  <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" stroke-width="1.5"/>
  <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" stroke-width="4"/>
  <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
  <text x="28" y="33" text-anchor="middle" font-family="Arial, sans-serif" font-weight="bold" font-size="11" fill="#f59e0b">$</text>
  <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" stroke-width="4.5" stroke-linecap="round"/>
  <circle cx="46" cy="18" r="6" fill="#ef4444"/>
  <text x="46" y="22" text-anchor="middle" font-family="Arial, sans-serif" font-weight="bold" font-size="9" fill="white">!</text>
</svg>
<div style="font-size:13px;font-weight:bold;letter-spacing:3px;color:#1e3a5f;margin-top:6px;font-variant:small-caps">MEDICAID FRAUD INSPECTOR</div>
</div>
<div class="confidential">CONFIDENTIAL — MEDICAID FRAUD INVESTIGATION REPORT — FOR OFFICIAL USE ONLY</div>
<h1>Fraud Investigation Report</h1>
<p style="color:#6b7280;font-size:13px;display:flex;align-items:center;gap:6px">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="20" height="20" style="vertical-align:middle;flex-shrink:0">
  <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
  <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" stroke-width="1.5"/>
  <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" stroke-width="4"/>
  <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
  <text x="28" y="33" text-anchor="middle" font-family="Arial, sans-serif" font-weight="bold" font-size="11" fill="#f59e0b">$</text>
  <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" stroke-width="4.5" stroke-linecap="round"/>
  <circle cx="46" cy="18" r="6" fill="#ef4444"/>
  <text x="46" y="22" text-anchor="middle" font-family="Arial, sans-serif" font-weight="bold" font-size="9" fill="white">!</text>
</svg>
<span>Generated: {gen} &nbsp;|&nbsp; Medicaid Inspector &nbsp;|&nbsp; NPI: <strong>{esc(npi)}</strong></span>
</p>

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
<p style="color:#6b7280;font-size:13px">17 fraud signals scored 0–1 and weighted. Composite score = weighted sum capped at 100. Signals marked TRIGGERED indicate anomalous behavior requiring investigation.</p>
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


@router.get("/export/csv")
async def export_providers_csv():
    """Export all scanned providers as a CSV download."""
    prescanned = get_prescanned()
    if not prescanned:
        raise HTTPException(404, "No scanned providers available")

    output = _io.StringIO()
    writer = _csv.writer(output)
    writer.writerow(["NPI", "Name", "Specialty", "State", "Risk Score", "Total Paid", "Flag Count", "Flags"])
    for p in sorted(prescanned, key=lambda x: -(x.get("risk_score") or 0)):
        nppes = p.get("nppes") or {}
        name = nppes.get("name", "")
        specialty = nppes.get("specialty", "")
        state = p.get("state") or nppes.get("address", {}).get("state", "")
        flags = p.get("flags") or []
        flag_names = "; ".join(f.get("signal", "") if isinstance(f, dict) else str(f) for f in flags)
        writer.writerow([
            p.get("npi", ""),
            name,
            specialty,
            state,
            f'{p.get("risk_score", 0):.1f}',
            f'{p.get("total_paid", 0):.2f}',
            len(flags),
            flag_names,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=providers_export.csv"},
    )


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

        # Attach review status / notes from review queue + OIG exclusion status
        from core.oig_store import is_excluded as _oig_check
        review_by_npi = {item["npi"]: item for item in get_review_queue()}
        enriched_slice = []
        for p in page_slice:
            rev = review_by_npi.get(p["npi"])
            entry = dict(p)
            if rev:
                entry["review_status"] = rev.get("status")
                entry["review_notes"]  = rev.get("notes", "")
            oig_excluded, oig_record = _oig_check(p["npi"])
            entry["oig_excluded"] = oig_excluded
            if oig_record:
                entry["oig_detail"] = oig_record
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
    npi = _validate_npi(npi)
    import asyncio

    # Check prescan cache first — avoids re-querying remote Parquet
    cached = get_provider_by_npi(npi)

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

    cached = get_provider_by_npi(npi)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not found in scan cache — run a scan first")

    nppes_data = cached.get("nppes") or await get_provider(npi)

    review_items = get_review_queue()
    review_item  = next((r for r in review_items if r.get("npi") == npi), None)

    # Fetch HCPCS descriptions
    hcpcs_list = cached.get("hcpcs") or []
    codes = [h.get("hcpcs_code", "") for h in hcpcs_list if h.get("hcpcs_code")][:20]
    hcpcs_descriptions = await _fetch_hcpcs_descriptions(codes)

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
    cached = get_provider_by_npi(npi)
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

    cached = get_provider_by_npi(npi)
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
    cached = get_provider_by_npi(npi)
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



@router.get("/{npi}/hcpcs")
async def get_hcpcs(npi: str):
    """HCPCS breakdown with descriptions — served from prescan cache when available."""
    cached = get_provider_by_npi(npi)
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


@router.get("/{npi}/signal-evidence/{signal}")
async def provider_signal_evidence(npi: str, signal: str):
    """Return detailed evidence for a specific fraud signal on this provider."""
    from services.risk_scorer import _hcpcs_sql, _timeline_sql, _peer_stats_sql
    from services.anomaly_detector import (
        SPECIALTY_HCPCS_MAP, _EM_FAMILIES, ADJACENT_STATES,
        compute_address_clusters, compute_auth_official_clusters,
    )
    from data.duckdb_client import query_async

    # Find provider in prescan cache
    provider = None
    for p in get_prescanned():
        if p["npi"] == npi:
            provider = p
            break
    if not provider:
        return {"error": "Provider not found in cache"}

    # Fetch supporting data
    hcpcs_rows = await query_async(_hcpcs_sql(npi))
    timeline_rows = await query_async(_timeline_sql(npi))
    peer_rows = await query_async(_peer_stats_sql(npi))
    peer = peer_rows[0] if peer_rows else {}
    peer_mean = float(peer.get("mean_rpb") or 0)
    peer_std = float(peer.get("std_rpb") or 0)

    evidence: dict = {"signal": signal, "npi": npi}

    if signal == "billing_concentration":
        total = sum(r["total_paid"] for r in hcpcs_rows) or 1
        top_codes = []
        for r in hcpcs_rows[:10]:
            pct = r["total_paid"] / total
            top_codes.append({
                "code": r["hcpcs_code"],
                "paid": round(r["total_paid"], 2),
                "pct": round(pct * 100, 1),
                "claims": r.get("total_claims", 0),
            })
        top = hcpcs_rows[0] if hcpcs_rows else None
        evidence["methodology"] = (
            "OIG flags providers where a single procedure code represents >80% "
            "of total billing. Legitimate providers bill a diverse mix of codes. "
            "Single-code dominance is a top enforcement target for personal care, "
            "home health, and DME."
        )
        evidence["threshold"] = ">80% of total billing from one HCPCS code"
        evidence["total_billed"] = round(total, 2)
        evidence["top_code_pct"] = round((top["total_paid"] / total * 100), 1) if top else 0
        evidence["top_codes"] = top_codes

    elif signal == "revenue_per_bene_outlier":
        rpb = provider.get("revenue_per_beneficiary") or 0.0
        z = (rpb - peer_mean) / peer_std if peer_std else 0
        evidence["methodology"] = (
            "Compares this provider's revenue-per-beneficiary against providers "
            "billing the same top procedure code (same-service peer group). "
            "Flags at >3 standard deviations above peer mean — the threshold "
            "used in CMS Comparative Billing Reports."
        )
        evidence["threshold"] = ">3σ above same-code peer mean"
        evidence["this_provider"] = round(rpb, 2)
        evidence["peer_mean"] = round(peer_mean, 2)
        evidence["peer_std"] = round(peer_std, 2)
        evidence["z_score"] = round(z, 2)
        evidence["multiple_of_mean"] = round(rpb / peer_mean, 1) if peer_mean else None

    elif signal == "claims_per_bene_anomaly":
        cpb = provider.get("claims_per_beneficiary") or 0.0
        # Compute peer stats for claims_per_bene from all scanned providers
        all_cpb = [
            p.get("claims_per_beneficiary") or 0
            for p in get_prescanned()
            if (p.get("claims_per_beneficiary") or 0) > 0
        ]
        import statistics
        cpb_mean = statistics.mean(all_cpb) if all_cpb else 0
        cpb_std = statistics.stdev(all_cpb) if len(all_cpb) > 2 else 0
        z = (cpb - cpb_mean) / cpb_std if cpb_std else 0
        evidence["methodology"] = (
            "Compares claims per unique beneficiary against all scanned providers. "
            "OIG cases document extreme examples — 312 claims per beneficiary in "
            "a single year. Flagged at >3σ above peer mean."
        )
        evidence["threshold"] = ">3σ above peer mean (or >100 absolute)"
        evidence["this_provider"] = round(cpb, 1)
        evidence["peer_mean"] = round(cpb_mean, 1)
        evidence["peer_std"] = round(cpb_std, 1)
        evidence["z_score"] = round(z, 2)
        evidence["total_claims"] = provider.get("total_claims", 0)
        evidence["total_beneficiaries"] = provider.get("total_beneficiaries", 0)

    elif signal == "billing_ramp_rate":
        evidence["methodology"] = (
            "Flags explosive billing growth in the first 6 months, requiring "
            "both >400% growth AND ≥$50K in month-6 billing. OIG screens new "
            "providers for rapid ramp-up before investigators can respond."
        )
        evidence["threshold"] = ">400% growth + ≥$50K month-6 billing"
        if len(timeline_rows) >= 6:
            start = timeline_rows[0]["total_paid"] or 0
            end_val = timeline_rows[5]["total_paid"] or 0
            pct = ((end_val - start) / start * 100) if start else float("inf")
            evidence["month_1_billing"] = round(start, 2)
            evidence["month_6_billing"] = round(end_val, 2)
            evidence["growth_pct"] = round(pct, 1) if pct != float("inf") else "infinite"
            evidence["first_6_months"] = [
                {"month": r.get("month", ""), "total_paid": round(r["total_paid"], 2)}
                for r in timeline_rows[:6]
            ]
        else:
            evidence["note"] = f"Only {len(timeline_rows)} months of history (need 6)"

    elif signal == "bust_out_pattern":
        values = [r["total_paid"] for r in timeline_rows]
        peak_idx = max(range(len(values)), key=lambda i: values[i]) if values else 0
        evidence["methodology"] = (
            "Detects 'ramp and exit' — peak billing followed by 3+ months of "
            "$0 activity. Fraudulent providers bill aggressively then stop, "
            "as documented in OIG enforcement actions."
        )
        evidence["threshold"] = "Peak billing + ≥3 consecutive months at $0"
        evidence["timeline"] = [
            {
                "month": r.get("month", ""),
                "total_paid": round(r["total_paid"], 2),
                "is_peak": i == peak_idx,
            }
            for i, r in enumerate(timeline_rows)
        ]
        evidence["peak_month"] = timeline_rows[peak_idx].get("month", "") if timeline_rows else ""
        evidence["peak_amount"] = round(values[peak_idx], 2) if values else 0

    elif signal == "ghost_billing":
        months_data = []
        for r in timeline_rows:
            months_data.append({
                "month": r.get("month", ""),
                "total_paid": round(r.get("total_paid") or 0, 2),
                "beneficiaries": r.get("total_unique_beneficiaries", 0),
                "is_ghost": (r.get("total_paid") or 0) > 0 and (r.get("total_unique_beneficiaries") or 0) == 12,
            })
        ghost_count = sum(1 for m in months_data if m["is_ghost"])
        evidence["methodology"] = (
            "CMS suppresses exact beneficiary counts below 11, always displaying "
            "12. Providers consistently showing exactly 12 beneficiaries may be "
            "fabricating claims to stay below the detection floor."
        )
        evidence["threshold"] = ">50% of billing months show exactly 12 beneficiaries (over 6+ months)"
        evidence["months"] = months_data
        evidence["ghost_month_count"] = ghost_count
        evidence["total_months"] = len(months_data)
        evidence["ghost_pct"] = round(ghost_count / len(months_data) * 100, 1) if months_data else 0

    elif signal == "total_spend_outlier":
        total = provider.get("total_paid") or 0
        all_paid = [p.get("total_paid") or 0 for p in get_prescanned() if (p.get("total_paid") or 0) > 0]
        import statistics
        spend_mean = statistics.mean(all_paid) if all_paid else 0
        spend_std = statistics.stdev(all_paid) if len(all_paid) > 2 else 0
        z = (total - spend_mean) / spend_std if spend_std else 0
        evidence["methodology"] = (
            "Absolute spending level is the single strongest predictor in OIG "
            "ML models. Major fraud cases almost universally involve providers "
            "billing far above the peer median."
        )
        evidence["threshold"] = ">3σ above all-provider mean"
        evidence["this_provider"] = round(total, 2)
        evidence["peer_mean"] = round(spend_mean, 2)
        evidence["peer_std"] = round(spend_std, 2)
        evidence["z_score"] = round(z, 2)
        evidence["peer_count"] = len(all_paid)
        evidence["multiple_of_mean"] = round(total / spend_mean, 1) if spend_mean else None

    elif signal == "billing_consistency":
        nonzero = [r.get("total_paid") or 0 for r in timeline_rows if (r.get("total_paid") or 0) > 0]
        import math as _math
        mean_val = sum(nonzero) / len(nonzero) if nonzero else 0
        variance = sum((v - mean_val) ** 2 for v in nonzero) / len(nonzero) if nonzero else 0
        cv = _math.sqrt(variance) / mean_val if mean_val else 0
        evidence["methodology"] = (
            "Real providers have natural month-to-month variation. A coefficient "
            "of variation below 0.15 across 12+ months is an OIG flag for "
            "automated or manufactured claims."
        )
        evidence["threshold"] = "CV < 0.15 over 12+ months"
        evidence["cv"] = round(cv, 4)
        evidence["monthly_mean"] = round(mean_val, 2)
        evidence["monthly_std"] = round(_math.sqrt(variance), 2)
        evidence["active_months"] = len(nonzero)
        evidence["monthly_values"] = [
            {"month": r.get("month", ""), "total_paid": round(r.get("total_paid") or 0, 2)}
            for r in timeline_rows
        ]

    elif signal == "bene_concentration":
        total_claims = provider.get("total_claims") or 0
        total_bene = provider.get("total_beneficiaries") or provider.get("total_unique_beneficiaries") or 0
        ratio = total_claims / total_bene if total_bene else 0
        evidence["methodology"] = (
            "Phantom billing — fabricating services for a small pool of beneficiaries — "
            "produces abnormally high claims-per-beneficiary ratios. OIG cases "
            "document 20–50+ services per beneficiary per year vs. peers at 3–5."
        )
        evidence["threshold"] = ">15 claims/beneficiary OR <20 beneficiaries with >200 claims"
        evidence["total_claims"] = total_claims
        evidence["total_beneficiaries"] = total_bene
        evidence["claims_per_bene"] = round(ratio, 1)

    elif signal == "upcoding_pattern":
        families_found = []
        for fam_name, fam_codes in _EM_FAMILIES.items():
            code_claims = {r["hcpcs_code"]: float(r.get("total_claims") or r.get("total_paid") or 0) for r in hcpcs_rows}
            fam_claims = {c: code_claims.get(c, 0) for c in fam_codes}
            fam_total = sum(fam_claims.values())
            if fam_total < 10:
                continue
            breakdown = [{"code": c, "claims": fam_claims[c], "pct": round(fam_claims[c] / fam_total * 100, 1)} for c in fam_codes if fam_claims[c] > 0]
            families_found.append({"family": fam_name, "total_claims": fam_total, "codes": breakdown})
        evidence["methodology"] = (
            "Upcoding — billing a higher-level E/M code than warranted — is one "
            "of the most common Medicaid fraud forms. OIG compares a provider's "
            "E/M level distribution against peers. >50% on the highest code is flagged."
        )
        evidence["threshold"] = ">50% of family claims on highest-level code (peer expectation <25%)"
        evidence["em_families"] = families_found

    elif signal == "address_cluster_risk":
        cluster_sizes = compute_address_clusters()
        size = cluster_sizes.get(npi, 0)
        # Find co-located providers
        nppes_data = (provider.get("nppes") or {})
        addr = nppes_data.get("address", {})
        co_located = []
        if size >= 2:
            target_zip = addr.get("zip", "")[:5]
            target_line = (addr.get("line1") or "").lower().strip()
            for p in get_prescanned():
                if p["npi"] == npi:
                    continue
                pa = (p.get("nppes") or {}).get("address", {})
                if (pa.get("zip", "")[:5] == target_zip and
                        (pa.get("line1") or "").lower().strip() == target_line):
                    co_located.append({
                        "npi": p["npi"],
                        "name": (p.get("nppes") or {}).get("name", "Unknown"),
                        "risk_score": p.get("risk_score", 0),
                        "total_paid": p.get("total_paid", 0),
                    })
        evidence["methodology"] = (
            "OIG investigations have found fraudulent providers operating multiple "
            "entities from the same address — sometimes dozens of NPIs at one suite. "
            "3+ providers at the same street+ZIP warrants investigation."
        )
        evidence["threshold"] = "≥3 providers at same street address + ZIP"
        evidence["address"] = {
            "line1": addr.get("line1", ""),
            "city": addr.get("city", ""),
            "state": addr.get("state", ""),
            "zip": addr.get("zip", ""),
        }
        evidence["cluster_size"] = size
        evidence["co_located_providers"] = co_located[:20]

    elif signal == "oig_excluded":
        from core.oig_store import is_excluded as _is_excluded
        excluded, record = _is_excluded(npi)
        evidence["methodology"] = (
            "Providers on the OIG LEIE (List of Excluded Individuals/Entities) "
            "are formally barred from all federal health care programs. Any "
            "Medicaid billing by an excluded provider is per se fraudulent "
            "under 42 USC 1320a-7b."
        )
        evidence["threshold"] = "Present on OIG LEIE exclusion list"
        evidence["excluded"] = excluded
        evidence["record"] = record

    elif signal == "specialty_mismatch":
        nppes_data = provider.get("nppes") or {}
        tax = nppes_data.get("taxonomy") or {}
        taxonomy_desc = tax.get("description") or tax.get("desc") or ""
        if not taxonomy_desc:
            taxonomies = nppes_data.get("taxonomies") or []
            if taxonomies and isinstance(taxonomies[0], dict):
                taxonomy_desc = taxonomies[0].get("desc") or taxonomies[0].get("description") or ""
        taxonomy_desc = taxonomy_desc.strip().rstrip(",").strip()
        matched_keyword = None
        valid_prefixes = []
        for kw, pfx in SPECIALTY_HCPCS_MAP.items():
            if kw in taxonomy_desc.lower():
                matched_keyword = kw
                valid_prefixes = pfx
                break
        total_paid = 0.0
        inside_codes = []
        outside_codes = []
        for h in hcpcs_rows:
            paid = float(h.get("total_paid") or 0)
            total_paid += paid
            code = str(h.get("hcpcs_code") or "")
            entry = {"code": code, "paid": round(paid, 2), "claims": h.get("total_claims", 0)}
            if any(code.startswith(pfx) for pfx in valid_prefixes):
                inside_codes.append(entry)
            else:
                outside_codes.append(entry)
        evidence["methodology"] = (
            "Cross-specialty billing — e.g., a podiatrist billing psychiatric codes — "
            "is a documented OIG fraud pattern. Providers whose billing falls >30% "
            "outside their declared specialty's expected HCPCS codes are flagged."
        )
        evidence["threshold"] = ">30% of total paid dollars outside expected specialty codes"
        evidence["specialty"] = taxonomy_desc
        evidence["matched_keyword"] = matched_keyword
        evidence["valid_prefixes"] = valid_prefixes
        evidence["total_paid"] = round(total_paid, 2)
        evidence["inside_specialty_codes"] = inside_codes[:15]
        evidence["outside_specialty_codes"] = outside_codes[:15]
        inside_total = sum(c["paid"] for c in inside_codes)
        outside_total = sum(c["paid"] for c in outside_codes)
        evidence["inside_pct"] = round(inside_total / total_paid * 100, 1) if total_paid else 0
        evidence["outside_pct"] = round(outside_total / total_paid * 100, 1) if total_paid else 0

    elif signal == "corporate_shell_risk":
        auth_clusters = compute_auth_official_clusters()
        size = auth_clusters.get(npi, 0)
        nppes_data = provider.get("nppes") or {}
        auth_official = nppes_data.get("authorized_official") or {}
        # Find sibling NPIs under same auth official
        auth_name = (auth_official.get("name") or "").lower().strip()
        siblings = []
        if auth_name and size >= 3:
            for p in get_prescanned():
                if p["npi"] == npi:
                    continue
                pa = (p.get("nppes") or {}).get("authorized_official") or {}
                if (pa.get("name") or "").lower().strip() == auth_name:
                    siblings.append({
                        "npi": p["npi"],
                        "name": (p.get("nppes") or {}).get("name", "Unknown"),
                        "risk_score": p.get("risk_score", 0),
                        "total_paid": p.get("total_paid", 0),
                    })
        evidence["methodology"] = (
            "A single individual registering 3+ billing NPIs — each appearing "
            "independent — is a 'corporate shell' pattern. OIG has uncovered "
            "networks of 5–20+ shell entities under one person billing millions."
        )
        evidence["threshold"] = "≥3 NPIs under same authorized official"
        evidence["authorized_official"] = auth_official
        evidence["cluster_size"] = size
        evidence["sibling_npis"] = siblings[:20]

    elif signal == "geographic_impossibility":
        nppes_state = (provider.get("nppes", {}).get("address", {}).get("state") or provider.get("state", "")).strip().upper()
        from core.store import get_scan_progress
        progress = get_scan_progress()
        billing_state = (progress.get("state_filter") or "").strip().upper()
        evidence["methodology"] = (
            "Medicaid is state-administered — providers must be enrolled where "
            "they deliver services. A provider registered in one state but billing "
            "a distant state's Medicaid is a strong indicator of identity theft or "
            "billing mill fraud."
        )
        evidence["threshold"] = "Non-adjacent state mismatch between NPPES registration and billing state"
        evidence["nppes_state"] = nppes_state
        evidence["billing_state"] = billing_state
        evidence["adjacent_states"] = ADJACENT_STATES.get(nppes_state, [])
        evidence["is_adjacent"] = billing_state in ADJACENT_STATES.get(nppes_state, [])

    elif signal == "dead_npi_billing":
        nppes_data = provider.get("nppes") or {}
        evidence["methodology"] = (
            "A deactivated NPI is no longer valid for billing. Claims under "
            "deactivated NPIs may indicate identity theft — using a deceased or "
            "retired provider's NPI to submit fraudulent claims."
        )
        evidence["threshold"] = "NPI status = deactivated with billing activity"
        evidence["npi_status"] = nppes_data.get("status", "unknown")
        evidence["deactivation_date"] = nppes_data.get("deactivation_date", "")
        evidence["total_paid"] = provider.get("total_paid", 0)
        evidence["total_claims"] = provider.get("total_claims", 0)

    elif signal == "new_provider_explosion":
        nppes_data = provider.get("nppes") or {}
        enum_date = nppes_data.get("enumeration_date", "")
        evidence["methodology"] = (
            "Fraud mills obtain new NPIs specifically for billing fraud. A new "
            "provider billing $500K+ in their first 18 months is an extreme "
            "statistical outlier — legitimate practices take years to ramp up."
        )
        evidence["threshold"] = ">$500K in first 18 months or >$1M in first 12 months"
        evidence["enumeration_date"] = enum_date
        evidence["total_paid"] = provider.get("total_paid", 0)
        from datetime import date as _date
        from services.anomaly_detector import _parse_date_flexible
        parsed = _parse_date_flexible(enum_date)
        if parsed:
            age_days = (_date.today() - parsed).days
            evidence["age_months"] = round(age_days / 30.44, 1)
        else:
            evidence["age_months"] = None

    else:
        evidence["error"] = f"Unknown signal: {signal}"

    return evidence


@router.get("/{npi}/open-payments")
async def provider_open_payments(npi: str):
    """Check CMS Open Payments for industry payments to this provider."""
    from core.open_payments_store import get_open_payments
    return await get_open_payments(npi)


@router.get("/{npi}/sam-exclusion")
async def provider_sam_exclusion(npi: str):
    """Check SAM.gov federal exclusion list."""
    from core.sam_store import check_sam_exclusion
    # Also try by name from NPPES data
    name = ""
    for p in get_prescanned():
        if p["npi"] == npi:
            name = p.get("nppes", {}).get("name", "")
            break
    return await check_sam_exclusion(npi=npi, name=name)


@router.get("/{npi}/ml-score")
async def get_provider_ml_score(npi: str):
    """Return ML anomaly score for a provider (Isolation Forest)."""
    from services.ml_scorer import get_ml_score
    result = get_ml_score(npi)
    return {"npi": npi, **result}


@router.get("/{npi}/peer-distribution")
async def get_peer_distribution(npi: str):
    """Return histogram distribution data for peer comparison visualizations."""
    import math as _math

    cached = get_provider_by_npi(npi)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not in scan cache")

    top_code = cached.get("top_hcpcs") or ""
    if not top_code:
        hcpcs = cached.get("hcpcs") or []
        if hcpcs:
            top_code = hcpcs[0].get("hcpcs_code", "")

    if not top_code:
        return {"npi": npi, "top_hcpcs": None, "peer_count": 0, "distributions": []}

    metrics: dict[str, list[float]] = {
        "revenue_per_beneficiary": [],
        "claims_per_beneficiary": [],
        "total_paid": [],
    }
    for p in get_prescanned():
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
        if rpb   > 0: metrics["revenue_per_beneficiary"].append(rpb)
        if cpb   > 0: metrics["claims_per_beneficiary"].append(cpb)
        if spend > 0: metrics["total_paid"].append(spend)

    this_vals = {
        "revenue_per_beneficiary": float(cached.get("revenue_per_beneficiary") or 0),
        "claims_per_beneficiary":  float(cached.get("claims_per_beneficiary") or 0),
        "total_paid":              float(cached.get("total_paid") or 0),
    }

    labels = {
        "revenue_per_beneficiary": "Revenue / Beneficiary",
        "claims_per_beneficiary":  "Claims / Beneficiary",
        "total_paid":              "Total Paid",
    }

    distributions = []
    for metric_key, vals in metrics.items():
        if len(vals) < 3:
            continue
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        provider_value = this_vals[metric_key]
        pct = round(sum(1 for v in vals_sorted if v < provider_value) / n * 100, 1)
        p99_idx = min(n - 1, int(n * 0.99))
        lo = vals_sorted[0]
        hi = max(vals_sorted[p99_idx], provider_value * 1.05)
        if hi <= lo:
            hi = lo + 1
        num_buckets = min(15, max(5, n // 3))
        bucket_width = (hi - lo) / num_buckets

        buckets = []
        for i in range(num_buckets):
            b_min = lo + i * bucket_width
            b_max = lo + (i + 1) * bucket_width
            count = sum(1 for v in vals_sorted if b_min <= v < b_max) if i < num_buckets - 1 else sum(1 for v in vals_sorted if b_min <= v <= b_max)
            if i == num_buckets - 1:
                count += sum(1 for v in vals_sorted if v > b_max)
            buckets.append({"min": round(b_min, 2), "max": round(b_max, 2), "count": count})

        distributions.append({
            "metric": metric_key,
            "label": labels[metric_key],
            "buckets": buckets,
            "provider_value": round(provider_value, 2),
            "percentile": pct,
            "peer_count": n,
        })

    return {
        "npi": npi,
        "top_hcpcs": top_code,
        "peer_count": len(metrics["revenue_per_beneficiary"]),
        "distributions": distributions,
    }


@router.get("/{npi}/billing-network")
async def get_billing_network(npi: str):
    """Return the billing/servicing provider network for a given NPI."""
    import asyncio
    from core.oig_store import is_excluded as _is_excluded

    src = f"read_parquet('{get_parquet_path()}')"

    servicing_sql = f"""
    SELECT
        SERVICING_PROVIDER_NPI_NUM  AS connected_npi,
        'servicing'                 AS relationship,
        SUM(TOTAL_PAID)             AS total_paid,
        SUM(TOTAL_CLAIMS)           AS total_claims,
        COUNT(DISTINCT HCPCS_CODE)  AS distinct_hcpcs
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
      AND SERVICING_PROVIDER_NPI_NUM IS NOT NULL
      AND SERVICING_PROVIDER_NPI_NUM != '{npi}'
    GROUP BY SERVICING_PROVIDER_NPI_NUM
    ORDER BY total_paid DESC
    """

    billing_sql = f"""
    SELECT
        BILLING_PROVIDER_NPI_NUM    AS connected_npi,
        'billing'                   AS relationship,
        SUM(TOTAL_PAID)             AS total_paid,
        SUM(TOTAL_CLAIMS)           AS total_claims,
        COUNT(DISTINCT HCPCS_CODE)  AS distinct_hcpcs
    FROM {src}
    WHERE SERVICING_PROVIDER_NPI_NUM = '{npi}'
      AND BILLING_PROVIDER_NPI_NUM IS NOT NULL
      AND BILLING_PROVIDER_NPI_NUM != '{npi}'
    GROUP BY BILLING_PROVIDER_NPI_NUM
    ORDER BY total_paid DESC
    """

    servicing_rows, billing_rows = await asyncio.gather(
        query_async(servicing_sql),
        query_async(billing_sql),
    )

    cache_by_npi = {p["npi"]: p for p in get_prescanned()}

    def enrich(row: dict) -> dict:
        cnpi = row["connected_npi"]
        cached = cache_by_npi.get(cnpi, {})
        oig_excl, _ = _is_excluded(cnpi)
        return {
            "npi": cnpi,
            "relationship": row["relationship"],
            "total_paid": float(row.get("total_paid") or 0),
            "total_claims": int(row.get("total_claims") or 0),
            "distinct_hcpcs": int(row.get("distinct_hcpcs") or 0),
            "provider_name": cached.get("provider_name") or (cached.get("nppes") or {}).get("name") or "",
            "risk_score": cached.get("risk_score"),
            "oig_excluded": oig_excl,
        }

    connections = [enrich(r) for r in servicing_rows] + [enrich(r) for r in billing_rows]

    return {
        "npi": npi,
        "connections": connections,
        "servicing_count": len(servicing_rows),
        "billing_count": len(billing_rows),
        "total_connections": len(connections),
    }


@router.get("/{npi}/claim-lines")
async def get_claim_lines(
    npi: str,
    hcpcs_code: str | None = Query(None),
    month: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
):
    """Granular claim-line drill-down — raw monthly rows from Parquet."""
    npi = _validate_npi(npi)
    if hcpcs_code:
        hcpcs_code = _validate_hcpcs(hcpcs_code)
    if month:
        month = _validate_month(month)

    src = f"read_parquet('{get_parquet_path()}')"
    where_parts = [f"(BILLING_PROVIDER_NPI_NUM = '{npi}' OR SERVICING_PROVIDER_NPI_NUM = '{npi}')"]
    if hcpcs_code:
        where_parts.append(f"HCPCS_CODE = '{hcpcs_code}'")
    if month:
        where_parts.append(f"CLAIM_FROM_MONTH = '{month}'")
    where = " AND ".join(where_parts)

    offset = (page - 1) * limit

    count_sql = f"SELECT COUNT(*) AS cnt FROM {src} WHERE {where}"
    count_rows = await query_async(count_sql)
    total = count_rows[0]["cnt"] if count_rows else 0

    sql = f"""
    SELECT
        BILLING_PROVIDER_NPI_NUM   AS billing_npi,
        SERVICING_PROVIDER_NPI_NUM AS servicing_npi,
        HCPCS_CODE                 AS hcpcs_code,
        CLAIM_FROM_MONTH           AS month,
        TOTAL_UNIQUE_BENEFICIARIES AS beneficiaries,
        TOTAL_CLAIMS               AS claims,
        TOTAL_PAID                 AS paid
    FROM {src}
    WHERE {where}
    ORDER BY CLAIM_FROM_MONTH DESC, TOTAL_PAID DESC
    LIMIT {limit} OFFSET {offset}
    """
    rows = await query_async(sql)
    return {"npi": npi, "claim_lines": rows, "page": page, "limit": limit, "total": total}


@router.get("/{npi}/hcpcs/{code}/detail")
async def get_hcpcs_detail(npi: str, code: str):
    """Monthly breakdown for a specific HCPCS code."""
    npi = _validate_npi(npi)
    code = _validate_hcpcs(code)

    src = f"read_parquet('{get_parquet_path()}')"
    where = f"(BILLING_PROVIDER_NPI_NUM = '{npi}' OR SERVICING_PROVIDER_NPI_NUM = '{npi}') AND HCPCS_CODE = '{code}'"

    sql = f"""
    SELECT
        CLAIM_FROM_MONTH           AS month,
        SUM(TOTAL_CLAIMS)          AS claims,
        SUM(TOTAL_PAID)            AS paid,
        SUM(TOTAL_UNIQUE_BENEFICIARIES) AS beneficiaries,
        SERVICING_PROVIDER_NPI_NUM AS servicing_npi
    FROM {src}
    WHERE {where}
    GROUP BY CLAIM_FROM_MONTH, SERVICING_PROVIDER_NPI_NUM
    ORDER BY CLAIM_FROM_MONTH ASC
    """
    monthly = await query_async(sql)

    total_paid = sum(r["paid"] for r in monthly)
    total_claims = sum(r["claims"] for r in monthly)
    total_beneficiaries = sum(r["beneficiaries"] for r in monthly)
    month_count = len({r["month"] for r in monthly})

    total_sql = f"SELECT SUM(TOTAL_PAID) AS grand FROM {src} WHERE BILLING_PROVIDER_NPI_NUM = '{npi}' OR SERVICING_PROVIDER_NPI_NUM = '{npi}'"
    total_rows = await query_async(total_sql)
    grand_total = total_rows[0]["grand"] if total_rows and total_rows[0]["grand"] else 1

    descriptions = await _fetch_hcpcs_descriptions([code])
    description = descriptions.get(code, "")

    return {
        "npi": npi,
        "hcpcs_code": code,
        "description": description,
        "monthly": monthly,
        "total_paid": total_paid,
        "total_claims": total_claims,
        "total_beneficiaries": total_beneficiaries,
        "pct_of_total": round(total_paid / grand_total * 100, 2) if grand_total else 0,
        "avg_paid_per_month": round(total_paid / month_count, 2) if month_count else 0,
        "avg_claims_per_month": round(total_claims / month_count, 2) if month_count else 0,
        "month_count": month_count,
    }


@router.get("/{npi}/yoy-comparison")
async def yoy_comparison(npi: str):
    """Year-over-year comparison of billing metrics."""
    npi = _validate_npi(npi)
    src = f"read_parquet('{get_parquet_path()}')"
    sql = f"""
    SELECT
        SUBSTRING(CLAIM_FROM_MONTH, 1, 4) AS year,
        SUM(TOTAL_PAID)                   AS total_paid,
        SUM(TOTAL_CLAIMS)                 AS total_claims,
        SUM(TOTAL_UNIQUE_BENEFICIARIES)   AS total_beneficiaries,
        COUNT(DISTINCT HCPCS_CODE)        AS distinct_hcpcs
    FROM {src}
    WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
    GROUP BY year
    ORDER BY year ASC
    """
    rows = await query_async(sql)

    years = []
    for i, row in enumerate(rows):
        entry = {
            "year": row["year"],
            "total_paid": float(row.get("total_paid") or 0),
            "total_claims": int(row.get("total_claims") or 0),
            "total_beneficiaries": int(row.get("total_beneficiaries") or 0),
            "distinct_hcpcs": int(row.get("distinct_hcpcs") or 0),
            "pct_change_paid": None,
            "pct_change_claims": None,
            "pct_change_beneficiaries": None,
            "flagged": False,
        }
        if i > 0:
            prev = rows[i - 1]
            prev_paid = float(prev.get("total_paid") or 0)
            prev_claims = int(prev.get("total_claims") or 0)
            prev_bene = int(prev.get("total_beneficiaries") or 0)

            if prev_paid > 0:
                pct = ((entry["total_paid"] - prev_paid) / prev_paid) * 100
                entry["pct_change_paid"] = round(pct, 1)
                if pct > 200:
                    entry["flagged"] = True
            if prev_claims > 0:
                entry["pct_change_claims"] = round(
                    ((entry["total_claims"] - prev_claims) / prev_claims) * 100, 1
                )
            if prev_bene > 0:
                entry["pct_change_beneficiaries"] = round(
                    ((entry["total_beneficiaries"] - prev_bene) / prev_bene) * 100, 1
                )
        years.append(entry)

    return {"npi": npi, "years": years}


@router.get("/{npi}/ownership-chain")
async def get_ownership_chain(npi: str):
    """Build ownership network: authorized official -> all NPIs they control."""
    cached = get_provider_by_npi(npi)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not in scan cache")

    nppes = cached.get("nppes") or {}
    auth_off = nppes.get("authorized_official") or {}
    off_name = (auth_off.get("name") or "").strip()
    off_title = (auth_off.get("title") or "").strip()

    if not off_name:
        return {
            "official": None,
            "controlled_npis": [],
            "total_entities": 0,
            "total_combined_billing": 0,
            "shared_addresses": [],
        }

    off_key = off_name.lower().strip()

    controlled = []
    for p in get_prescanned():
        p_nppes = p.get("nppes") or {}
        p_auth = p_nppes.get("authorized_official") or {}
        p_off_name = (p_auth.get("name") or "").strip()
        if p_off_name.lower().strip() == off_key:
            p_addr = p_nppes.get("address") or {}
            controlled.append({
                "npi": p["npi"],
                "name": p.get("provider_name") or p_nppes.get("name") or "",
                "entity_type": p_nppes.get("entity_type") or "",
                "risk_score": p.get("risk_score", 0),
                "total_paid": p.get("total_paid", 0),
                "flag_count": len(p.get("flags") or []),
                "address": {
                    "line1": p_addr.get("line1", ""),
                    "city": p_addr.get("city", ""),
                    "state": p_addr.get("state", ""),
                    "zip": p_addr.get("zip", ""),
                },
                "specialty": (p_nppes.get("taxonomy") or {}).get("description") or "",
                "status": p_nppes.get("status") or "",
            })

    controlled.sort(key=lambda x: x["risk_score"], reverse=True)

    addr_groups: dict[str, list[str]] = {}
    for c in controlled:
        a = c["address"]
        zip5 = (a.get("zip") or "")[:5]
        line1 = (a.get("line1") or "").upper().strip()
        if zip5 and line1:
            key = f"{zip5}|{line1}"
            addr_groups.setdefault(key, []).append(c["npi"])

    shared_addresses = []
    for key, npis in addr_groups.items():
        if len(npis) >= 2:
            zip5, line1 = key.split("|", 1)
            shared_addresses.append({"address": f"{line1}, {zip5}", "npis": npis})

    total_billing = sum(c["total_paid"] for c in controlled)

    return {
        "official": {"name": off_name, "title": off_title},
        "controlled_npis": controlled,
        "total_entities": len(controlled),
        "total_combined_billing": total_billing,
        "shared_addresses": shared_addresses,
    }


@router.get("/{npi}/narrative")
async def provider_narrative(npi: str):
    """Generate an investigation-ready case narrative for this provider."""
    from services.narrative_generator import generate_narrative
    try:
        return generate_narrative(npi)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{npi}/exclusion-summary")
async def provider_exclusion_summary(npi: str):
    """Consolidated exclusion check across all sources for a single provider."""
    from core.exclusion_aggregator import check_all_exclusions
    name = ""
    for p in get_prescanned():
        if p["npi"] == npi:
            name = p.get("nppes", {}).get("name", "")
            break
    return await check_all_exclusions(npi=npi, name=name)


@router.get("/{npi}/forecast")
async def get_forecast(npi: str):
    """Billing forecast with anomaly detection for a provider."""
    from services.forecaster import forecast_billing

    tl_response = await get_timeline(npi)
    timeline = tl_response.get("timeline", [])

    result = forecast_billing(timeline)
    return {"npi": npi, **result}
