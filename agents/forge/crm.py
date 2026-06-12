"""Twenty CRM GraphQL API client — contact sync for Forge leads."""

from __future__ import annotations

from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

_UPSERT_PERSON = """
mutation UpsertPerson(
  $firstName: String, $lastName: String, $email: String,
  $jobTitle: String, $city: String, $phone: String, $company: String
) {
  upsertPerson(
    input: {
      firstName: { firstName: $firstName, lastName: $lastName }
      emails: { primaryEmail: $email }
      jobTitle: $jobTitle
      city: $city
      phones: { primaryPhoneNumber: $phone }
    }
    conflictFields: primaryEmail
  ) {
    id
  }
}
"""

_UPDATE_PERSON = """
mutation UpdatePerson($id: ID!, $score: Float, $status: String) {
  updatePerson(id: $id, input: {
    customFields: { leadScore: $score, forgeStatus: $status }
  }) {
    id
  }
}
"""


class TwentyCRMClient:
    def __init__(self) -> None:
        self._url = f"{settings.TWENTY_CRM_URL.rstrip('/')}/api"
        self._headers = {
            "Authorization": f"Bearer {settings.TWENTY_CRM_API_KEY}",
            "Content-Type": "application/json",
        }

    def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.post(
            self._url,
            headers=self._headers,
            json={"query": query, "variables": variables},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL error: {data['errors']}")
        return data.get("data", {})

    def upsert_contact(self, lead: dict[str, Any]) -> str | None:
        """Create or update a person. Returns the Twenty CRM person ID."""
        try:
            data = self._gql(
                _UPSERT_PERSON,
                {
                    "firstName": lead.get("first_name", ""),
                    "lastName": lead.get("last_name", ""),
                    "email": lead.get("email", ""),
                    "jobTitle": lead.get("title", ""),
                    "city": lead.get("city", ""),
                    "phone": lead.get("phone", ""),
                    "company": lead.get("company", ""),
                },
            )
            person_id = data.get("upsertPerson", {}).get("id")
            logger.info("crm_contact_upserted", crm_id=person_id, email=lead.get("email"))
            return person_id
        except Exception as exc:
            logger.warning("crm_upsert_failed", email=lead.get("email"), error=str(exc))
            return None

    def update_score(self, crm_id: str, score: int) -> bool:
        try:
            self._gql(_UPDATE_PERSON, {"id": crm_id, "score": float(score), "status": None})
            return True
        except Exception as exc:
            logger.warning("crm_update_score_failed", crm_id=crm_id, error=str(exc))
            return False

    def update_status(self, crm_id: str, status: str) -> bool:
        try:
            self._gql(_UPDATE_PERSON, {"id": crm_id, "score": None, "status": status})
            return True
        except Exception as exc:
            logger.warning("crm_update_status_failed", crm_id=crm_id, error=str(exc))
            return False
