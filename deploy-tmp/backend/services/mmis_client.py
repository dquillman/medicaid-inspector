"""
MMIS (Medicaid Management Information System) integration stub.
Real MMIS connections require state-specific credentials and VPN access.
This module provides a configurable interface with stubbed sample data
so downstream code can be developed and tested before live integration.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)


# ── Abstract interface ────────────────────────────────────────────────────────

class MMISClientBase(ABC):
    """Abstract MMIS integration interface."""

    @abstractmethod
    async def check_eligibility(self, bene_id: str) -> dict:
        """Check beneficiary eligibility status."""
        ...

    @abstractmethod
    async def get_enrollment(self, npi: str) -> dict:
        """Check provider enrollment status in the state MMIS."""
        ...

    @abstractmethod
    async def get_status(self) -> dict:
        """Return connection/configuration status."""
        ...


# ── Stub implementation ──────────────────────────────────────────────────────

class MMISStubClient(MMISClientBase):
    """Stub implementation returning sample data for development/testing."""

    async def check_eligibility(self, bene_id: str) -> dict:
        now = datetime.utcnow()
        return {
            "bene_id": bene_id,
            "eligible": True,
            "status": "active",
            "plan": "Medicaid Fee-for-Service",
            "effective_date": (now - timedelta(days=365)).strftime("%Y-%m-%d"),
            "end_date": None,
            "aid_category": "SSI",
            "county": "Sample County",
            "managed_care_plan": None,
            "source": "stub",
        }

    async def get_enrollment(self, npi: str) -> dict:
        now = datetime.utcnow()
        return {
            "npi": npi,
            "enrolled": True,
            "enrollment_status": "active",
            "enrollment_date": (now - timedelta(days=730)).strftime("%Y-%m-%d"),
            "revalidation_due": (now + timedelta(days=180)).strftime("%Y-%m-%d"),
            "provider_type": "Individual",
            "specialty": "Internal Medicine",
            "accepts_new_patients": True,
            "sanctions": [],
            "source": "stub",
        }

    async def get_status(self) -> dict:
        configured = bool(settings.MMIS_ENDPOINT_URL)
        return {
            "configured": configured,
            "endpoint_url": settings.MMIS_ENDPOINT_URL or None,
            "has_api_key": bool(settings.MMIS_API_KEY),
            "connection_status": "stub_mode" if not configured else "configured_not_tested",
            "mode": "stub",
            "message": (
                "MMIS integration is running in stub mode. "
                "Configure MMIS_ENDPOINT_URL and MMIS_API_KEY for live data."
            ),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: Optional[MMISClientBase] = None


def get_mmis_client() -> MMISClientBase:
    global _client
    if _client is None:
        _client = MMISStubClient()
    return _client
