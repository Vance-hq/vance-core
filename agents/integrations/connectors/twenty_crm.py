"""Twenty CRM REST API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector


class TwentyCRMConnector(BaseConnector):
    service_name = "twenty_crm"
    _rate_limit_config = (0, 60)  # self-hosted; no enforced limit

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "url": settings.TWENTY_CRM_URL,
            "api_key": settings.TWENTY_CRM_API_KEY,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._base = creds["url"].rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {creds['api_key']}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # People (contacts)
    # ------------------------------------------------------------------

    def create_contact(
        self,
        first_name: str,
        last_name: str,
        email: str,
        phone: str | None = None,
        company_name: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "name": {"firstName": first_name, "lastName": last_name},
            "emails": {"primaryEmail": email},
        }
        if phone:
            body["phones"] = {"primaryPhoneNumber": phone}
        if company_name:
            body["company"] = {"name": company_name}
        resp = self.request("POST", f"{self._base}/api/people", headers=self._headers, json=body)
        return resp.json()

    def update_contact(self, contact_id: str, **kwargs: Any) -> dict:
        resp = self.request(
            "PATCH",
            f"{self._base}/api/people/{contact_id}",
            headers=self._headers,
            json=kwargs,
        )
        return resp.json()

    def get_contact(self, contact_id: str) -> dict:
        resp = self.request("GET", f"{self._base}/api/people/{contact_id}", headers=self._headers)
        return resp.json()

    def list_contacts(self, filter: str | None = None, limit: int = 20) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if filter:
            params["filter"] = filter
        resp = self.request("GET", f"{self._base}/api/people", headers=self._headers, params=params)
        return resp.json().get("data", {}).get("people", [])

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------

    def create_company(
        self,
        name: str,
        domain_name: str = "",
        employees: int | None = None,
    ) -> dict:
        body: dict[str, Any] = {"name": {"text": name}}
        if domain_name:
            body["domainName"] = {"primaryLinkUrl": domain_name}
        if employees is not None:
            body["employees"] = employees
        resp = self.request("POST", f"{self._base}/api/companies", headers=self._headers, json=body)
        return resp.json()

    # ------------------------------------------------------------------
    # Opportunities (deals)
    # ------------------------------------------------------------------

    def create_deal(
        self,
        name: str,
        amount: float | None = None,
        stage: str = "LEAD",
        company_id: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"name": name, "stage": stage}
        if amount is not None:
            body["amount"] = {"amountMicros": int(amount * 1_000_000), "currencyCode": "USD"}
        if company_id:
            body["company"] = {"id": company_id}
        resp = self.request(
            "POST",
            f"{self._base}/api/opportunities",
            headers=self._headers,
            json=body,
        )
        return resp.json()

    def update_deal(self, deal_id: str, **kwargs: Any) -> dict:
        resp = self.request(
            "PATCH",
            f"{self._base}/api/opportunities/{deal_id}",
            headers=self._headers,
            json=kwargs,
        )
        return resp.json()

    def list_deals(self, stage: str | None = None, limit: int = 20) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if stage:
            params["filter"] = f"stage[eq]:{stage}"
        resp = self.request(
            "GET",
            f"{self._base}/api/opportunities",
            headers=self._headers,
            params=params,
        )
        return resp.json().get("data", {}).get("opportunities", [])

    # ------------------------------------------------------------------
    # Notes & tasks
    # ------------------------------------------------------------------

    def create_note(
        self,
        body: str,
        contact_id: str | None = None,
        company_id: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"body": body}
        if contact_id:
            payload["noteTargets"] = [{"personId": contact_id}]
        if company_id:
            payload.setdefault("noteTargets", []).append({"companyId": company_id})
        resp = self.request("POST", f"{self._base}/api/notes", headers=self._headers, json=payload)
        return resp.json()

    def create_task(
        self,
        title: str,
        due_at: str | None = None,
        assignee_id: str | None = None,
        status: str = "TODO",
    ) -> dict:
        body: dict[str, Any] = {"title": title, "status": status}
        if due_at:
            body["dueAt"] = due_at
        if assignee_id:
            body["assignee"] = {"id": assignee_id}
        resp = self.request("POST", f"{self._base}/api/tasks", headers=self._headers, json=body)
        return resp.json()
