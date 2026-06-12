"""Google Business Profile API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from ._google_auth import get_google_access_token
from .base_connector import BaseConnector

_MYBIZ = "https://mybusiness.googleapis.com/v4"
_MYBIZ_INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"


class GoogleBusinessProfileConnector(BaseConnector):
    service_name = "google_business_profile"
    _rate_limit_config = (600, 60)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"refresh_token": settings.GBP_REFRESH_TOKEN}

    def _token(self) -> str:
        return get_google_access_token(self._redis, "gbp", settings.GBP_REFRESH_TOKEN)

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------

    def get_location(self, account_name: str, location_name: str) -> dict:
        resp = self.request(
            "GET",
            f"{_MYBIZ}/{account_name}/locations/{location_name}",
            headers=self._auth(),
        )
        return resp.json()

    def update_location(
        self,
        account_name: str,
        location_name: str,
        location_data: dict,
        update_mask: str = "",
    ) -> dict:
        params = {"updateMask": update_mask} if update_mask else {}
        resp = self.request(
            "PATCH",
            f"{_MYBIZ}/{account_name}/locations/{location_name}",
            headers=self._auth(),
            params=params,
            json=location_data,
        )
        return resp.json()

    def list_reviews(
        self,
        account_name: str,
        location_name: str,
        page_size: int = 10,
    ) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/reviews",
            headers=self._auth(),
            params={"pageSize": page_size},
        )
        return resp.json().get("reviews", [])

    def reply_to_review(
        self,
        account_name: str,
        location_name: str,
        review_name: str,
        reply_text: str,
    ) -> dict:
        resp = self.request(
            "PUT",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/reviews/{review_name}/reply",
            headers=self._auth(),
            json={"comment": reply_text},
        )
        return resp.json()

    def delete_review_reply(
        self,
        account_name: str,
        location_name: str,
        review_name: str,
    ) -> dict:
        resp = self.request(
            "DELETE",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/reviews/{review_name}/reply",
            headers=self._auth(),
        )
        return {"deleted": resp.status_code == 200}

    def create_post(
        self,
        account_name: str,
        location_name: str,
        post_data: dict,
    ) -> dict:
        resp = self.request(
            "POST",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/localPosts",
            headers=self._auth(),
            json=post_data,
        )
        return resp.json()

    def list_posts(self, account_name: str, location_name: str) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/localPosts",
            headers=self._auth(),
        )
        return resp.json().get("localPosts", [])

    def get_insights(
        self,
        account_name: str,
        location_names: list[str],
        basic_request: dict | None = None,
    ) -> dict:
        body = {
            "locationNames": [f"{account_name}/locations/{n}" for n in location_names],
            "basicRequest": basic_request or {
                "metricRequests": [
                    {"metric": "QUERIES_DIRECT"},
                    {"metric": "QUERIES_INDIRECT"},
                    {"metric": "VIEWS_MAPS"},
                    {"metric": "VIEWS_SEARCH"},
                    {"metric": "ACTIONS_WEBSITE"},
                    {"metric": "ACTIONS_PHONE"},
                ]
            },
        }
        resp = self.request(
            "POST",
            f"{_MYBIZ}/{account_name}/locations:reportInsights",
            headers=self._auth(),
            json=body,
        )
        return resp.json()

    def get_questions(self, account_name: str, location_name: str) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/questions",
            headers=self._auth(),
        )
        return resp.json().get("questions", [])

    def answer_question(
        self,
        account_name: str,
        location_name: str,
        question_name: str,
        answer_text: str,
    ) -> dict:
        resp = self.request(
            "POST",
            f"{_MYBIZ}/{account_name}/locations/{location_name}/questions/{question_name}/answers",
            headers=self._auth(),
            json={"text": answer_text},
        )
        return resp.json()
