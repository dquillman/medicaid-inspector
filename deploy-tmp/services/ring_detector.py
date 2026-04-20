"""
Fraud Ring Detection — identifies clusters of providers linked by shared
attributes (address, phone/fax, overlapping HCPCS codes).
Uses union-find (disjoint set) for connected-component discovery.

Performance: runs entirely from in-memory prescan cache — no Parquet queries.
"""
import hashlib
import logging
from collections import defaultdict

from core.store import get_prescanned

log = logging.getLogger(__name__)

# ── Union-Find ────────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        self.rank.setdefault(x, 0)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

# ── Detection ─────────────────────────────────────────────────────────────────

_cached_rings: list[dict] | None = None


def _normalize(s: str | None) -> str:
    return (s or "").strip().lower()


async def detect_rings() -> list[dict]:
    """Build provider graph, find connected components, score them."""
    global _cached_rings

    providers = get_prescanned()
    if not providers:
        _cached_rings = []
        return []

    uf = UnionFind()
    edges: list[dict] = []

    npi_info: dict[str, dict] = {}
    npi_hcpcs: dict[str, set[str]] = {}  # NPI -> set of HCPCS codes

    for p in providers:
        npi = p["npi"]
        nppes = p.get("nppes") or {}
        addr = nppes.get("address") or {}
        npi_info[npi] = {
            "npi": npi,
            "provider_name": p.get("provider_name") or nppes.get("name") or "",
            "risk_score": p.get("risk_score", 0),
            "total_paid": p.get("total_paid", 0),
            "total_claims": p.get("total_claims", 0),
            "flag_count": len(p.get("flags") or []),
            "state": p.get("state") or addr.get("state", ""),
            "city": p.get("city") or addr.get("city", ""),
            "address_line1": _normalize(addr.get("line1")),
            "address_zip": _normalize(addr.get("zip")),
            "phone": _normalize(nppes.get("phone")),
            "fax": _normalize(nppes.get("fax")),
        }
        uf.find(npi)
        # Collect HCPCS codes for this provider
        hcpcs_list = p.get("hcpcs") or []
        npi_hcpcs[npi] = {h.get("hcpcs_code", "") for h in hcpcs_list if h.get("hcpcs_code")}

    # ── Link by shared address ────────────────────────────────────────────
    addr_groups: dict[str, list[str]] = defaultdict(list)
    for npi, info in npi_info.items():
        key = info["address_line1"] + "|" + info["address_zip"]
        if key.strip("|"):
            addr_groups[key].append(npi)

    for key, npis in addr_groups.items():
        if len(npis) < 2:
            continue
        for i in range(1, len(npis)):
            uf.union(npis[0], npis[i])
            edges.append({"source": npis[0], "target": npis[i], "type": "shared_address", "detail": key.split("|")[0]})

    # ── Link by shared phone/fax ──────────────────────────────────────────
    phone_groups: dict[str, list[str]] = defaultdict(list)
    fax_groups: dict[str, list[str]] = defaultdict(list)
    for npi, info in npi_info.items():
        if info["phone"] and len(info["phone"]) >= 7:
            phone_groups[info["phone"]].append(npi)
        if info["fax"] and len(info["fax"]) >= 7:
            fax_groups[info["fax"]].append(npi)

    for grp, label in [(phone_groups, "shared_phone"), (fax_groups, "shared_fax")]:
        for key, npis in grp.items():
            if len(npis) < 2:
                continue
            for i in range(1, len(npis)):
                uf.union(npis[0], npis[i])
                edges.append({"source": npis[0], "target": npis[i], "type": label, "detail": key})

    # ── Link by high HCPCS code overlap (proxy for shared billing patterns) ──
    # Build inverted index: HCPCS code -> list of NPIs
    code_to_npis: dict[str, list[str]] = defaultdict(list)
    for npi, codes in npi_hcpcs.items():
        for code in codes:
            code_to_npis[code].append(npi)

    # Find NPI pairs that share many codes (>= 5 shared HCPCS codes)
    pair_overlap: dict[tuple[str, str], int] = defaultdict(int)
    for code, npis in code_to_npis.items():
        if len(npis) < 2 or len(npis) > 200:  # Skip very common codes
            continue
        for i in range(len(npis)):
            for j in range(i + 1, min(len(npis), i + 50)):  # Cap comparisons
                pair = (min(npis[i], npis[j]), max(npis[i], npis[j]))
                pair_overlap[pair] += 1

    for (a, b), overlap in pair_overlap.items():
        if overlap >= 5:
            uf.union(a, b)
            edges.append({"source": a, "target": b, "type": "shared_hcpcs_codes", "detail": f"{overlap} shared codes"})

    # ── Collect components ────────────────────────────────────────────────
    components: dict[str, list[str]] = defaultdict(list)
    for npi in npi_info:
        components[uf.find(npi)].append(npi)

    # Only rings with 2+ members
    rings: list[dict] = []
    for root, members in components.items():
        if len(members) < 2:
            continue

        member_set = set(members)
        ring_edges = [e for e in edges if e["source"] in member_set and e["target"] in member_set]

        # Deduplicate edges
        seen_edges = set()
        deduped = []
        for e in ring_edges:
            key = tuple(sorted([e["source"], e["target"]])) + (e["type"],)
            if key not in seen_edges:
                seen_edges.add(key)
                deduped.append(e)

        member_infos = [npi_info[m] for m in members]
        total_paid = sum(m["total_paid"] for m in member_infos)
        avg_risk = sum(m["risk_score"] for m in member_infos) / len(member_infos) if member_infos else 0
        high_risk_count = sum(1 for m in member_infos if m["risk_score"] >= 50)
        total_flags = sum(m["flag_count"] for m in member_infos)
        connection_types = list({e["type"] for e in deduped})

        # Density: actual edges / possible edges
        max_edges = len(members) * (len(members) - 1) / 2
        density = len(deduped) / max_edges if max_edges > 0 else 0

        # Suspicion score: weighted combination
        suspicion = (
            high_risk_count * 20
            + avg_risk * 0.5
            + density * 30
            + min(total_paid / 1_000_000, 50)
            + total_flags * 2
        )

        ring_id = hashlib.md5(root.encode()).hexdigest()[:12]

        member_infos.sort(key=lambda m: m["risk_score"], reverse=True)

        rings.append({
            "ring_id": ring_id,
            "member_count": len(members),
            "total_paid": round(total_paid, 2),
            "avg_risk_score": round(avg_risk, 1),
            "high_risk_count": high_risk_count,
            "total_flags": total_flags,
            "density": round(density, 3),
            "suspicion_score": round(suspicion, 1),
            "connection_types": connection_types,
            "members": member_infos,
            "edges": deduped,
        })

    rings.sort(key=lambda r: r["suspicion_score"], reverse=True)
    _cached_rings = rings
    return rings


def get_cached_rings() -> list[dict] | None:
    return _cached_rings


def get_ring_by_id(ring_id: str) -> dict | None:
    if _cached_rings is None:
        return None
    for r in _cached_rings:
        if r["ring_id"] == ring_id:
            return r
    return None
