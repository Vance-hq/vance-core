"""
Reviews agent — monitor, respond, detect fakes, and request reviews.

Actions:
  monitor_reviews    — poll GBP/Yelp/Facebook for new reviews; enqueue responses
  respond_to_review  — generate + post a response to a specific review
  flag_fake_review   — score reviews for fakeness; auto-report if confidence > threshold
  reputation_alert   — check rolling average; alert Slack + strategy if below threshold
  review_request     — send SMS + email to customer 24h after job completion
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from agents.integrations.connectors.slack import SlackConnector
from shared.logger import get_logger
from shared.queue.queue import TaskQueue
from shared.types import Task, TaskResult

from .db import ReviewsDB
from .fake_detector import FakeReviewDetector
from .platforms.facebook import FacebookReviews
from .platforms.gbp import GBPReviews
from .platforms.yelp import YelpReviews
from .request_sender import ReviewRequestSender
from .responder import ReviewResponder

logger = get_logger(__name__)

_DEFAULT_THRESHOLDS = {"trusted_plumbing": 4.5}
_DEFAULT_THRESHOLD_FALLBACK = 4.2


class ReviewsAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ReviewsDB()
        self._responder = ReviewResponder(self._db)
        self._detector = FakeReviewDetector()
        self._request_sender = ReviewRequestSender(self._db, cfg)
        self._gbp = GBPReviews()
        self._yelp = YelpReviews()
        self._fb = FacebookReviews()
        self._listings = cfg.get("listings", {})
        self._thresholds = cfg.get("alert_thresholds", _DEFAULT_THRESHOLDS)
        self._rolling_days = int(cfg.get("rolling_average_days", 30))
        self._fake_threshold = float(cfg.get("fake_review_confidence_threshold", 0.8))

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "monitor_reviews":   lambda: self._handle_monitor(p),
            "respond_to_review": lambda: self._handle_respond(p),
            "flag_fake_review":  lambda: self._handle_flag_fake(p),
            "reputation_alert":  lambda: self._handle_reputation_alert(p),
            "review_request":    lambda: self._handle_review_request(p),
        }

        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown reviews action: {action}")

        logger.info("reviews_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.unanswered_reviews(limit=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # monitor_reviews
    # ------------------------------------------------------------------

    def _handle_monitor(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Poll configured listings for new reviews.
        Enqueues respond_to_review + flag_fake_review for each new review found.

        Optional payload:
          platform (str)  — restrict to one platform ('google','yelp','facebook')
          business (str)  — restrict to one business
        """
        platform_filter = p.get("platform")
        business_filter = p.get("business")

        new_count = 0
        errors: list[str] = []

        # GBP
        if not platform_filter or platform_filter == "google":
            for listing in self._listings.get("gbp", []):
                business = listing.get("business", "")
                if business_filter and business != business_filter:
                    continue
                try:
                    reviews = self._gbp.poll(business)
                    new_count += self._ingest_reviews(reviews)
                except Exception as exc:
                    errors.append(f"gbp/{business}: {exc}")
                    logger.error("monitor_gbp_failed", business=business, error=str(exc))

        # Yelp
        if not platform_filter or platform_filter == "yelp":
            for listing in self._listings.get("yelp", []):
                business = listing.get("business", "")
                if business_filter and business != business_filter:
                    continue
                try:
                    reviews = self._yelp.poll(business)
                    new_count += self._ingest_reviews(reviews)
                except Exception as exc:
                    errors.append(f"yelp/{business}: {exc}")
                    logger.error("monitor_yelp_failed", business=business, error=str(exc))

        # Facebook
        if not platform_filter or platform_filter == "facebook":
            for listing in self._listings.get("facebook", []):
                business = listing.get("business", "")
                if business_filter and business != business_filter:
                    continue
                try:
                    reviews = self._fb.poll(business)
                    new_count += self._ingest_reviews(reviews)
                except Exception as exc:
                    errors.append(f"facebook/{business}: {exc}")
                    logger.error("monitor_facebook_failed", business=business, error=str(exc))

        return {"new_reviews_found": new_count, "errors": errors}

    def _ingest_reviews(self, reviews: list[dict[str, Any]]) -> int:
        new = 0
        for r in reviews:
            if self._db.review_exists(r["platform"], r["external_id"]):
                continue
            if r.get("already_replied"):
                continue

            review_id = self._db.upsert_review(
                platform=r["platform"],
                external_id=r["external_id"],
                reviewer_name=r.get("reviewer_name", ""),
                rating=int(r["rating"]),
                review_text=r.get("review_text", ""),
                posted_at=r["posted_at"],
                business=r["business"],
                platform_ref=r.get("platform_ref"),
                reviewer_review_count=r.get("reviewer_review_count"),
                reviewer_has_photo=bool(r.get("reviewer_has_photo")),
            )
            new += 1

            self._queue.push(
                agent="reviews",
                payload={"action": "respond_to_review", "review_id": review_id},
            )
            self._queue.push(
                agent="reviews",
                payload={"action": "flag_fake_review", "review_id": review_id},
            )

        return new

    # ------------------------------------------------------------------
    # respond_to_review
    # ------------------------------------------------------------------

    def _handle_respond(self, p: dict[str, Any]) -> dict[str, Any]:
        review_id = p.get("review_id")
        if not review_id:
            return {"error": "review_id required"}
        return self._responder.respond(review_id)

    # ------------------------------------------------------------------
    # flag_fake_review
    # ------------------------------------------------------------------

    def _handle_flag_fake(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          review_id (str) — score a single review
          (none)          — batch scan all unscanned reviews
        """
        review_id = p.get("review_id")

        if review_id:
            review = self._db.get_review(review_id)
            reviews = [review] if review else []
        else:
            reviews = self._db.reviews_for_fake_scan()

        flagged = 0
        for review in reviews:
            rid = str(review["id"])
            confidence, reasons = self._detector.score(review)
            auto_report = self._detector.should_flag(confidence, self._fake_threshold)

            if auto_report or confidence > 0.4:
                self._db.flag_review(
                    review_id=rid,
                    reason="; ".join(reasons),
                    confidence=confidence,
                    auto_reported=auto_report,
                )
                if auto_report:
                    flagged += 1
                    logger.info(
                        "review_flagged",
                        review_id=rid,
                        confidence=confidence,
                        platform=review.get("platform"),
                    )

        return {"reviews_scanned": len(reviews), "auto_flagged": flagged}

    # ------------------------------------------------------------------
    # reputation_alert
    # ------------------------------------------------------------------

    def _handle_reputation_alert(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          business (str) — check one business; omit to check all configured businesses
        """
        business_filter = p.get("business")

        all_businesses: set[str] = set()
        for listings in self._listings.values():
            for item in listings:
                all_businesses.add(item.get("business", ""))

        targets = [business_filter] if business_filter else list(all_businesses)

        alerts_sent: list[dict[str, Any]] = []

        for business in targets:
            avg = self._db.rolling_average(business, self._rolling_days)
            count = self._db.recent_review_count(business, self._rolling_days)

            if avg is None or count < 5:
                continue

            threshold = self._thresholds.get(business, _DEFAULT_THRESHOLD_FALLBACK)
            if avg >= threshold:
                continue

            message = (
                f"*Reputation alert — {business}*\n"
                f"Rolling {self._rolling_days}-day average: {avg:.2f} "
                f"(threshold: {threshold}, reviews: {count})"
            )
            try:
                from shared.config.settings import settings as _s
                slack = SlackConnector(called_by="reviews", method_name="reputation_alert")
                channel = getattr(_s, "REVIEWS_ALERT_CHANNEL", "#reviews")
                slack.send_message(channel, message)
            except Exception as exc:
                logger.error("reputation_slack_failed", business=business, error=str(exc))

            self._queue.push(
                agent="strategy",
                payload={
                    "action": "reputation_alert",
                    "business": business,
                    "rolling_avg": round(avg, 2),
                    "threshold": threshold,
                    "review_count": count,
                    "days": self._rolling_days,
                },
            )

            alerts_sent.append({"business": business, "avg": round(avg, 2), "threshold": threshold})
            logger.info(
                "reputation_alert_sent",
                business=business,
                avg=round(avg, 2),
                threshold=threshold,
            )

        return {"alerts_sent": len(alerts_sent), "details": alerts_sent}

    # ------------------------------------------------------------------
    # review_request
    # ------------------------------------------------------------------

    def _handle_review_request(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          job_id      (str)       — unique job identifier
          business    (str)       — defaults to 'trusted_plumbing'
          contact_id  (str|None)  — optional CRM contact ID
          phone       (str|None)  — customer mobile (E.164)
          email       (str|None)  — customer email
          first_name  (str)
          tech_name   (str)       — technician name
          job_type    (str)       — e.g., "water heater replacement"
          address     (str)       — first line only
        """
        job_id = p.get("job_id")
        if not job_id:
            return {"error": "job_id required"}

        return self._request_sender.send(
            job_id=job_id,
            business=p.get("business", "trusted_plumbing"),
            contact_id=p.get("contact_id"),
            phone=p.get("phone"),
            email=p.get("email"),
            first_name=p.get("first_name", ""),
            tech_name=p.get("tech_name", "our tech"),
            job_type=p.get("job_type", "service call"),
            address=p.get("address", "your place"),
        )


if __name__ == "__main__":
    config = AgentConfig.load("reviews")
    ReviewsAgent("reviews", config).run()
