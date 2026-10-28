"""Pure frozen-ranking evaluation; no imports of stores, network clients or startup.

Caller supplies an already captured ranking and manually adjudicated outcomes.
No outcome is inferred from a score, referral, charge or analyst disposition.
"""
import hashlib
import json
import math
import re
from typing import Iterable


def freeze_ranking(ranking: list[dict], *, snapshot_id: str, provenance: dict, k: int = 50) -> dict:
    """Freeze exact supplied order. Caller stores returned manifest immutably.

    Private manifest contains identities/ranks; blinded_order contains only
    opaque case IDs, sorted independently of rank. Evidence packets must be
    separately scrubbed of model scores, conclusions and rank cues.
    """
    if not snapshot_id.strip() or not provenance or k < 1:
        raise ValueError("snapshot_id, provenance and positive k are required")
    selected = ranking[:k]
    identifiers = [str(row.get("npi") or "").strip() for row in selected]
    if not selected or any(not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Sample requires unique nonempty provider identifiers")
    rows = []
    for rank, (identifier, row) in enumerate(zip(identifiers, selected), 1):
        case_id = hashlib.sha256(f"{snapshot_id}:{identifier}".encode()).hexdigest()[:20]
        rows.append({"case_id": case_id, "rank": rank, "npi": identifier,
                     "score": row.get("brain_score", row.get("risk_score"))})
    payload = {"schema_version": 1, "snapshot_id": snapshot_id, "requested_k": k,
               "sample_size": len(rows), "provenance": provenance, "private_rows": rows}
    payload["manifest_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    payload["blinded_order"] = sorted(row["case_id"] for row in rows)
    return payload


def _wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - radius), min(1, center + radius)]


def evaluate_frozen_sample(manifest: dict, adjudications: Iterable[dict], *, require_complete: bool = False) -> dict:
    """Compute transparent bounds, retaining unresolved cases in denominator.

    outcome: substantiated / unsubstantiated / unresolved. Definitive findings
    require evidence_reference, reviewer and review_date. Missing rows remain
    unresolved; duplicate/foreign case IDs fail rather than changing sample.
    """
    signed = {key: value for key, value in manifest.items() if key not in ("manifest_sha256", "blinded_order")}
    digest = hashlib.sha256(json.dumps(signed, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if digest != manifest.get("manifest_sha256"):
        raise ValueError("Frozen manifest hash mismatch")
    private_rows = manifest.get("private_rows", [])
    case_ids = {row["case_id"] for row in private_rows}
    if (not case_ids or len(case_ids) != len(private_rows)
            or manifest.get("sample_size") != len(private_rows)
            or manifest.get("requested_k", 0) < len(private_rows)):
        raise ValueError("Frozen manifest sample structure is invalid")
    if any(not isinstance(case, str) or not re.fullmatch(r"[a-f0-9]{20}", case) for case in case_ids):
        raise ValueError("Invalid opaque case identifier")
    if manifest.get("blinded_order", []) != sorted(case_ids):
        raise ValueError("Blinded case inventory does not match frozen sample")
    by_id = {}
    for row in adjudications:
        case_id = row.get("case_id")
        if case_id not in case_ids or case_id in by_id:
            raise ValueError("Adjudication must reference each sampled case at most once")
        outcome = row.get("outcome", "unresolved")
        if outcome not in ("substantiated", "unsubstantiated", "unresolved"):
            raise ValueError("Unknown outcome; workflow actions are not findings")
        if outcome != "unresolved" and not all(str(row.get(key) or "").strip() for key in ("evidence_reference", "reviewer", "review_date")):
            raise ValueError("Definitive findings require evidence reference, reviewer and review date")
        by_id[case_id] = row
    positive = sum(row.get("outcome") == "substantiated" for row in by_id.values())
    negative = sum(row.get("outcome") == "unsubstantiated" for row in by_id.values())
    total = len(case_ids)
    resolved = positive + negative
    unresolved = total - resolved
    complete_top50 = manifest["requested_k"] == 50 and total == 50 and unresolved == 0
    if require_complete and (unresolved or len(by_id) != total or total != manifest["requested_k"]):
        raise ValueError("Incomplete review: missing, unresolved or unsampled cases cannot establish ranking effectiveness")
    return {"snapshot_id": manifest["snapshot_id"], "manifest_sha256": digest,
            "evaluation_status": "complete_outcome_review" if unresolved == 0 else "incomplete",
            "accuracy_proven": False,
            "sample_size": total, "substantiated": positive, "unsubstantiated": negative,
            "unresolved": unresolved, "resolution_rate": resolved / total,
            "precision_at_50": positive / total if complete_top50 else None,
            "resolved_case_fraction": positive / resolved if resolved else None,
            "resolved_fraction_wilson_95pct": _wilson(positive, resolved),
            "full_sample_precision_bounds": [positive / total, (positive + unresolved) / total],
            "limitations": "Frozen selected ranking only; resolved subset may be biased. Wilson interval assumes independent cases and omits network correlation. No population recall, fraud prevalence, recovery or ROI estimate."}


def evaluate_review_document(manifest: dict, document, *, require_complete: bool = False) -> dict:
    """Accept retained review wrapper only when bound to the frozen snapshot."""
    if not isinstance(document, dict) or document.get("snapshot_id") != manifest.get("snapshot_id") or document.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("Review document must identify the matching frozen snapshot and manifest hash")
    if not isinstance(document.get("adjudications"), list):
        raise ValueError("Review document requires an adjudications list")
    return evaluate_frozen_sample(manifest, document["adjudications"], require_complete=require_complete)
