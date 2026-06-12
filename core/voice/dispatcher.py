"""
Sends a parsed VoiceIntent to the Vance orchestrator API.
Receives the response and hands it back to the voice loop for TTS delivery.
"""

import logging

import httpx

from .intent.intent_schema import VoiceIntent

logger = logging.getLogger(__name__)


class VoiceDispatcher:
    def __init__(self, config: dict):
        self.base_url = config["url"]
        self.timeout = config["timeout_seconds"]
        self.intent_endpoint = config["intent_endpoint"]

    def dispatch(self, intent: VoiceIntent) -> str:
        """
        Send intent to orchestrator. Returns a spoken response string.

        The orchestrator returns:
          { task_ids: [...], agents: [...], spoken_response: "string for TTS" }

        If dispatch fails, returns a safe error message for TTS.
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}{self.intent_endpoint}",
                    json=intent.model_dump(mode="json"),
                )
                response.raise_for_status()
                data = response.json()

                spoken = data.get(
                    "spoken_response",
                    f"Got it. Dispatching to {intent.agent}.",
                )
                logger.info(
                    f"Dispatched intent {intent.intent} → tasks: {data.get('task_ids', [])}"
                )
                return spoken

        except httpx.ConnectError:
            logger.error("Orchestrator not reachable — is it running on port 7700?")
            return "I can't reach the orchestrator. Make sure it's running."

        except httpx.TimeoutException:
            logger.error("Orchestrator timed out")
            return "That's taking longer than expected. I'll keep working on it."

        except Exception as e:
            logger.error(f"Dispatch error: {e}")
            return "Something went wrong dispatching that. Check the logs."
