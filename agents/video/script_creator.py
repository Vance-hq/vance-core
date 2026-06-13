"""ScriptCreator — LLM-generated video scripts per topic and persona."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import VideoDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a video scriptwriter for a SaaS company. Write an engaging video script. "
    "Output JSON only: "
    "{\"hook\": str, \"script\": str, \"cta\": str, \"duration_est_s\": int, "
    "\"title_options\": [str]}"
)

_SHORTS_SYSTEM = (
    "You are a short-form video editor. Given a long video script, extract 3 standalone short clips (under 60 seconds each). "
    "Output JSON only: [{\"title\": str, \"clip_outline\": str, \"duration_s\": int}]"
)

_TITLE_SYSTEM = (
    "You are a YouTube SEO expert. Given a video topic and current title, suggest 3 alternative titles "
    "optimized for search and click-through. Output JSON only: [{\"title\": str, \"rationale\": str}]"
)


class ScriptCreator:

    def __init__(self, db: VideoDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def create_script(self, product: str, topic: str, persona: str, tone: str, fmt: str) -> dict[str, Any]:
        prompt = (
            f"Product: {product}\n"
            f"Topic: {topic}\n"
            f"Target persona: {persona}\n"
            f"Tone: {tone}\n"
            f"Format: {fmt} ({'under 60 seconds' if fmt == 'short' else '5-10 minutes'})"
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=1500,
        )
        raw = resp.content[0].text.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"hook": "", "script": raw, "cta": "", "duration_est_s": 300, "title_options": []}

        script_id = self._db.save_script(
            product=product,
            topic=topic,
            persona=persona,
            script=data.get("script", ""),
            hook=data.get("hook", ""),
            duration_est_s=int(data.get("duration_est_s", 300)),
            fmt=fmt,
        )

        logger.info("video_script_created", product=product, topic=topic, fmt=fmt)
        return {"script_id": script_id, "product": product, "topic": topic, **data}

    def create_shorts(self, script: str) -> list[dict[str, Any]]:
        resp = llm.complete(
            messages=[{"role": "user", "content": f"Long video script:\n{script}"}],
            system=_SHORTS_SYSTEM,
            max_tokens=800,
        )
        raw = resp.content[0].text.strip()
        try:
            clips = json.loads(raw)
        except json.JSONDecodeError:
            match = __import__("re").search(r"\[.*\]", raw, __import__("re").DOTALL)
            clips = json.loads(match.group(0)) if match else []
        return clips

    def optimize_title(self, topic: str, current_title: str) -> list[dict[str, Any]]:
        resp = llm.complete(
            messages=[{"role": "user", "content": f"Topic: {topic}\nCurrent title: {current_title}"}],
            system=_TITLE_SYSTEM,
            max_tokens=400,
        )
        raw = resp.content[0].text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return [{"title": current_title, "rationale": "Could not parse alternatives"}]
