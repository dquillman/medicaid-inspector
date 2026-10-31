"""OIG filing guide: the answers must follow the provider type (audit 2026-10-30)."""
from services.oig_filing_guide import build_filing_guide


def _guide(taxonomy: str) -> dict:
    return build_filing_guide(
        npi="1000000001", name="SYNTHETIC PROVIDER", taxonomy=taxonomy, state="CA",
        last_month="2024-06", flagged_signals=[], entity_type="NPI-2",
        previously_reported=False, address="1 Test St",
    )


def _answers(guide: dict) -> str:
    return " | ".join(str(v) for v in guide.values())


def test_cms_lab_supplier_label_is_a_laboratory_not_dme():
    # CMS names labs "PART B SUPPLIER - INDEPENDENT CLINICAL LABORATORY".
    text = _answers(_guide("PART B SUPPLIER - INDEPENDENT CLINICAL LABORATORY"))
    assert "Laboratory" in text
    assert "DME Company" not in text


def test_real_dme_supplier_still_maps_to_dme():
    text = _answers(_guide("DURABLE MEDICAL EQUIPMENT & MEDICAL SUPPLIES"))
    assert "DME Company" in text
