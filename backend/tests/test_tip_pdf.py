"""
The full referral narrative as a formatted PDF (services/tip_pdf.py).
"""

SAMPLE = """DOJ CRIMINAL TIP REWARDS PILOT PROGRAM - Suspected Medicaid Provider Fraud
Submitted via the federal fraud portal: https://america.gov/fraud

SUBJECT OF COMPLAINT
  Provider name: TEST CARE, LLC
  NPI: 1000000001

NATURE OF THE ALLEGATION
  Automated analysis flagged this provider.

  ** KEY FINDING (verifiable from public records):
     Medicare revoked this provider's enrollment effective 2022-12-30 \u2014 still paid.
     Amount paid after Medicare revoked the provider: $4,648,498 **

  TOTAL MEDICAID PAID TO SUBJECT (period): $10,473,627

SUPPORTING INDICATORS (1)
  - Billing Ramp Rate: Billing grew 900% in first 6 months
      Regulatory basis: 42 CFR \u00a7 455.23
"""


def test_tip_pdf_is_a_real_pdf_with_the_text(client, auth_headers):
    r = client.post("/api/oig-tips/pdf", headers=auth_headers,
                    json={"npi": "1000000001", "text": SAMPLE, "provider_name": "TEST CARE, LLC"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert 'filename="DOJ-tip-1000000001.pdf"' in r.headers["content-disposition"]


def test_tip_pdf_needs_auth_and_text(client, auth_headers):
    assert client.post("/api/oig-tips/pdf", json={"npi": "1", "text": "x"}).status_code == 401
    assert client.post("/api/oig-tips/pdf", headers=auth_headers,
                       json={"npi": "1", "text": "  "}).status_code == 400
