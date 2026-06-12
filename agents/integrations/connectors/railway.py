"""Railway GraphQL API connector.

Railway has no complete REST API — all operations use the GraphQL endpoint.
"""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_GQL_URL = "https://backboard.railway.app/graphql/v2"


class RailwayConnector(BaseConnector):
    service_name = "railway"
    _rate_limit_config = (1000, 3600)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"token": settings.RAILWAY_API_TOKEN}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers = {
            "Authorization": f"Bearer {self.load_credentials()['token']}",
            "Content-Type": "application/json",
        }

    def _gql(self, query: str, variables: dict | None = None) -> dict:
        resp = self.request(
            "POST",
            _GQL_URL,
            json={"query": query, "variables": variables or {}},
            headers=self._headers,
        )
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Railway GraphQL error: {data['errors']}")
        return data.get("data", {})

    # ------------------------------------------------------------------

    def deploy_service(self, service_id: str, environment_id: str = "") -> dict:
        data = self._gql(
            """
            mutation serviceInstanceRedeploy($serviceId: String!, $environmentId: String!) {
              serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
            }
            """,
            {"serviceId": service_id, "environmentId": environment_id},
        )
        return {"triggered": data.get("serviceInstanceRedeploy", False)}

    def get_service_status(self, service_id: str) -> dict:
        data = self._gql(
            """
            query service($serviceId: ID!) {
              service(id: $serviceId) {
                id
                name
                serviceInstances {
                  edges {
                    node {
                      id
                      healthcheckPath
                      numReplicas
                      deployments(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
                        edges {
                          node {
                            id
                            status
                            createdAt
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            """,
            {"serviceId": service_id},
        )
        return data.get("service", {})

    def set_env_var(
        self,
        project_id: str,
        name: str,
        value: str,
        environment_id: str = "",
    ) -> dict:
        data = self._gql(
            """
            mutation variableUpsert($input: VariableUpsertInput!) {
              variableUpsert(input: $input)
            }
            """,
            {
                "input": {
                    "projectId": project_id,
                    "name": name,
                    "value": value,
                    "environmentId": environment_id or None,
                }
            },
        )
        return {"ok": data.get("variableUpsert", False)}

    def restart_service(self, service_id: str, environment_id: str = "") -> dict:
        return self.deploy_service(service_id, environment_id)

    def get_logs(self, deployment_id: str, limit: int = 100) -> list[dict]:
        data = self._gql(
            """
            query deploymentLogs($deploymentId: String!, $limit: Int) {
              deploymentLogs(deploymentId: $deploymentId, limit: $limit) {
                message
                timestamp
                severity
              }
            }
            """,
            {"deploymentId": deployment_id, "limit": limit},
        )
        return data.get("deploymentLogs", [])
