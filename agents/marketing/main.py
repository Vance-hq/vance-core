"""Marketing agent — campaign builder, copy generation, email sequencer."""

from __future__ import annotations

from typing import Any

from agents._base import BaseAgent, AgentConfig
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .copy_generator import generate_copy, framework_mode_for_position

logger = get_logger(__name__)


class MarketingAgent(BaseAgent):

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")

        if action == "generate_copy":
            output = self._generate_copy(task.payload)
        elif action == "build_sequence":
            output = self._build_sequence(task.payload)
        elif action == "create_campaign":
            output = self._create_campaign(task.payload)
        else:
            raise ValueError(f"Unknown action: {action}")

        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        return True

    def _generate_copy(self, payload: dict[str, Any]) -> dict[str, Any]:
        tone = payload.get("tone", self.get_config("default_tone") or "direct-response")
        position = int(payload.get("sequence_position", 1))
        mode = payload.get("framework_mode") or framework_mode_for_position(position)
        output = generate_copy(
            target_persona=payload.get("target_persona", ""),
            product=payload.get("product", ""),
            goal=payload.get("goal", payload.get("brief", "")),
            tone=tone,
            sequence_position=position,
            framework_mode=mode,
        )
        return dict(output)

    def _build_sequence(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = payload.get("goal", "")
        steps = int(payload.get("steps", self.get_config("sequence_max_steps") or 5))
        audience = payload.get("audience", "prospects")
        sequence = self.ask_llm(
            f"Write a {steps}-step email drip sequence targeting {audience}.\n\nGoal: {goal}\n\n"
            "Format each email as: Subject: ...\nBody: ...\n\nSeparate emails with ---",
            system_prompt=self.config.llm_system_prompt or "You are an email marketing specialist.",
        )
        return {"sequence": sequence, "steps": steps, "audience": audience}

    def _create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = payload.get("name", "Untitled Campaign")
        product = payload.get("product", "")
        target = payload.get("target", "")
        plan = self.ask_llm(
            f"Create a full direct-response marketing campaign plan.\n\n"
            f"Campaign: {name}\nProduct: {product}\nTarget audience: {target}\n\n"
            "Include: hook, offer, traffic channels, email sequence outline, KPIs.",
            system_prompt=self.config.llm_system_prompt or "You are a performance marketing strategist.",
        )
        return {"campaign": plan, "name": name, "product": product, "target": target}


if __name__ == "__main__":
    config = AgentConfig.load("marketing")
    MarketingAgent("marketing", config).run()
