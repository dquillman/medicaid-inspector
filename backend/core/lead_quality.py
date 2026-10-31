"""
Reliability gate for per-se "paid while terminated" leads.

Re-checking the 109 strongest per-se leads against public records (2026-10-28)
found three ways the raw lead lies. They are filtered from the DOJ shortlist
(still visible on the Excluded page with the reason attached):

  reinstated         a state later put the provider back to ACTIVE, so the
                     termination was a suspension that ended. Money paid inside
                     the window is not "paid while barred" (Living Waters,
                     New Freedom, Lucy Chie, ...).
  state_mismatch     the terminating state is not where NPPES says the provider
                     practises. The spend file has no billing state, so the
                     money cannot be tied to the terminating state (a $46M
                     Washington lead was an Oregon nonprofit; Connecticut
                     "license revoked" for doctors now in CA/NY/VA).
  unobservable_state NPPES practice state is one the enrollment file carries no
                     NPIs for (NM, OR), so "no active enrollment anywhere" could
                     not be tested and proves nothing.

  unsupported_exclusion_label
                     the state status code says "Medicare/Medicaid exclusion" but
                     the NPI is on no federal list. 5 such leads held $18.9M
                     (2026-10-30), led by a $15.7M Massachusetts nonprofit whose
                     payments never changed, and 94,306 North Carolina NPIs share
                     one code-72 date (a system migration, not 94,306 exclusions).

Unknown practice state is NOT treated as a mismatch: a lead is only dropped on
evidence, and the gap is surfaced as `practice_state_unknown`.
"""
from __future__ import annotations


_FEDERAL_LABELS = ("MEDICARE/MEDICAID EXCLUSION", "FEDERAL EXCLUSION")


def quality_flags(lead: dict, blind_states: list[str] | set[str] | None = None,
                  federal_record: bool | None = None) -> list[str]:
    """Reasons a paid_while_terminated lead should not be presented as filing-ready.

    `federal_record` says whether the NPI has an OIG exclusion or a Medicare
    revocation on file. None means the caller could not check, which never flags.
    """
    if lead.get("kind") != "paid_while_terminated":
        return []
    flags: list[str] = []
    status = (lead.get("enrollment_status") or "").upper()
    if federal_record is False and any(label in status for label in _FEDERAL_LABELS):
        flags.append("unsupported_exclusion_label")
    if lead.get("reinstated_after"):
        flags.append("reinstated")
    practice = (lead.get("practice_state") or "").upper()
    terminating = (lead.get("state") or lead.get("terminated_state") or "").upper()
    if practice and terminating and practice != terminating:
        flags.append("state_mismatch")
    if practice and practice in {s.upper() for s in (blind_states or ())}:
        flags.append("unobservable_state")
    return flags


FLAG_TEXT = {
    "unsupported_exclusion_label": "The state status says Medicare/Medicaid or federal exclusion, but the NPI "
                                   "is on neither the OIG exclusion list nor the Medicare revocation list.",
    "reinstated": "A state later reinstated this provider; the termination was reversed.",
    "state_mismatch": "The terminating state is not the state the provider practises in, so the "
                      "payments cannot be tied to that termination.",
    "unobservable_state": "The provider practises in a state whose enrollment records carry no NPIs, "
                          "so enrollment there could not be checked.",
}
