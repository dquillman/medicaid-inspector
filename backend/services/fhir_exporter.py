"""
FHIR R4 export service.
Converts provider data to FHIR Practitioner resources and
investigation findings to FHIR DocumentReference resources.
Basic FHIR R4 format — not a full implementation.
"""
import base64
import logging
from datetime import datetime

log = logging.getLogger(__name__)

FHIR_R4_BASE = "http://hl7.org/fhir"


def provider_to_fhir_practitioner(npi: str, nppes_data: dict, scoring: dict) -> dict:
    """
    Convert provider data to a FHIR R4 Practitioner resource.

    Args:
        npi: National Provider Identifier
        nppes_data: Data from NPPES registry
        scoring: Risk scoring data from prescan cache
    """
    address = nppes_data.get("address", {})
    taxonomy = nppes_data.get("taxonomy", {})
    entity_type = nppes_data.get("entity_type", "")
    name = nppes_data.get("name", "")

    # Parse name parts
    name_parts = name.split() if name else []
    family = name_parts[-1] if name_parts else ""
    given = name_parts[:-1] if len(name_parts) > 1 else []

    resource: dict = {
        "resourceType": "Practitioner",
        "id": npi,
        "meta": {
            "profile": [f"{FHIR_R4_BASE}/StructureDefinition/Practitioner"],
            "lastUpdated": datetime.utcnow().isoformat() + "Z",
        },
        "identifier": [
            {
                "system": "http://hl7.org/fhir/sid/us-npi",
                "value": npi,
            }
        ],
        "active": nppes_data.get("status", "").upper() != "DEACTIVATED",
        "name": [
            {
                "use": "official",
                "family": family,
                "given": given,
                "text": name,
            }
        ],
    }

    # Address
    if address.get("line1"):
        fhir_addr = {
            "use": "work",
            "type": "physical",
            "line": [l for l in [address.get("line1"), address.get("line2")] if l],
            "city": address.get("city", ""),
            "state": address.get("state", ""),
            "postalCode": address.get("zip", ""),
            "country": "US",
        }
        resource["address"] = [fhir_addr]

    # Qualification (taxonomy)
    if taxonomy.get("code"):
        resource["qualification"] = [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://nucc.org/provider-taxonomy",
                            "code": taxonomy.get("code", ""),
                            "display": taxonomy.get("description", ""),
                        }
                    ],
                    "text": taxonomy.get("description", ""),
                },
            }
        ]

    # Extension: risk score (custom)
    risk_score = scoring.get("risk_score", 0)
    flag_count = len(scoring.get("flags", []))
    resource["extension"] = [
        {
            "url": "http://medicaid-inspector.local/fhir/risk-score",
            "valueDecimal": round(risk_score, 2),
        },
        {
            "url": "http://medicaid-inspector.local/fhir/flag-count",
            "valueInteger": flag_count,
        },
        {
            "url": "http://medicaid-inspector.local/fhir/total-paid",
            "valueDecimal": round(scoring.get("total_paid", 0), 2),
        },
    ]

    return resource


def investigation_to_fhir_document_reference(
    npi: str,
    nppes_data: dict,
    scoring: dict,
    flags: list[dict],
) -> dict:
    """
    Convert investigation findings to a FHIR R4 DocumentReference resource.

    Args:
        npi: National Provider Identifier
        nppes_data: Data from NPPES registry
        scoring: Risk scoring data
        flags: List of signal/flag results
    """
    provider_name = nppes_data.get("name", f"Provider {npi}")
    risk_score = scoring.get("risk_score", 0)
    now = datetime.utcnow().isoformat() + "Z"

    # Build investigation summary text
    flag_lines = []
    for f in flags:
        if f.get("flagged"):
            flag_lines.append(
                f"- {f.get('signal', 'unknown')}: {f.get('reason', '')} "
                f"(score: {f.get('score', 0):.1f}, weight: {f.get('weight', 0):.1f})"
            )

    summary = (
        f"Fraud Investigation Report — {provider_name} (NPI: {npi})\n"
        f"Risk Score: {risk_score:.1f}/100\n"
        f"Total Paid: ${scoring.get('total_paid', 0):,.2f}\n"
        f"Total Claims: {scoring.get('total_claims', 0):,}\n"
        f"Flags: {len(flag_lines)}\n\n"
        + "\n".join(flag_lines)
    )

    # Determine security label based on risk
    if risk_score >= 75:
        security_label = "R"  # Restricted
    elif risk_score >= 50:
        security_label = "V"  # Very Restricted
    else:
        security_label = "N"  # Normal

    resource: dict = {
        "resourceType": "DocumentReference",
        "id": f"investigation-{npi}",
        "meta": {
            "profile": [f"{FHIR_R4_BASE}/StructureDefinition/DocumentReference"],
            "lastUpdated": now,
            "security": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                    "code": security_label,
                }
            ],
        },
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "55112-7",
                    "display": "Document summary",
                }
            ],
            "text": "Fraud Investigation Report",
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "55112-7",
                        "display": "Document summary",
                    }
                ]
            }
        ],
        "subject": {
            "reference": f"Practitioner/{npi}",
            "display": provider_name,
        },
        "date": now,
        "author": [
            {
                "display": "Medicaid Fraud Inspector (Automated)",
            }
        ],
        "description": f"Automated fraud investigation report for {provider_name}",
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "language": "en-US",
                    "data": base64.b64encode(summary.encode()).decode(),
                    "title": f"Investigation Report — {provider_name}",
                    "creation": now,
                },
            }
        ],
        "context": {
            "event": [
                {
                    "coding": [
                        {
                            "system": "http://medicaid-inspector.local/fhir/event-type",
                            "code": "fraud-investigation",
                            "display": "Fraud Investigation",
                        }
                    ]
                }
            ],
        },
    }

    # Custom extensions for risk data
    resource["extension"] = [
        {
            "url": "http://medicaid-inspector.local/fhir/risk-score",
            "valueDecimal": round(risk_score, 2),
        },
        {
            "url": "http://medicaid-inspector.local/fhir/flag-count",
            "valueInteger": len(flag_lines),
        },
    ]

    return resource
