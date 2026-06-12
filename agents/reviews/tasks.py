"""Celery tasks for the reviews agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.reviews.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.reviews.tasks.poll_reviews_gbp", ignore_result=True)
def poll_reviews_gbp() -> None:
    """Poll Google Business Profile for new reviews — every 4 hours."""
    from agents._base import AgentConfig
    from agents.reviews.db import ReviewsDB
    from agents.reviews.platforms.gbp import GBPReviews
    from shared.logger import get_logger
    from shared.queue.queue import TaskQueue

    logger = get_logger(__name__)
    cfg = AgentConfig.load("reviews").custom
    db = ReviewsDB()
    gbp = GBPReviews()
    queue = TaskQueue()
    new_total = 0

    for listing in cfg.get("listings", {}).get("gbp", []):
        business = listing.get("business", "")
        if not business:
            continue
        try:
            reviews = gbp.poll(business)
            for r in reviews:
                if db.review_exists(r["platform"], r["external_id"]):
                    continue
                if r.get("already_replied"):
                    continue
                review_id = db.upsert_review(
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
                queue.push(agent="reviews", payload={"action": "respond_to_review", "review_id": review_id})
                queue.push(agent="reviews", payload={"action": "flag_fake_review", "review_id": review_id})
                new_total += 1
        except Exception as exc:
            logger.error("poll_reviews_gbp_failed", business=business, error=str(exc))

    logger.info("poll_reviews_gbp_ran", new_reviews=new_total)


@app.task(name="agents.reviews.tasks.poll_reviews_yelp_facebook", ignore_result=True)
def poll_reviews_yelp_facebook() -> None:
    """Poll Yelp + Facebook for new reviews — every 6 hours."""
    from agents._base import AgentConfig
    from agents.reviews.db import ReviewsDB
    from agents.reviews.platforms.facebook import FacebookReviews
    from agents.reviews.platforms.yelp import YelpReviews
    from shared.logger import get_logger
    from shared.queue.queue import TaskQueue

    logger = get_logger(__name__)
    cfg = AgentConfig.load("reviews").custom
    db = ReviewsDB()
    yelp = YelpReviews()
    fb = FacebookReviews()
    queue = TaskQueue()
    new_total = 0

    def _ingest(reviews: list) -> int:
        count = 0
        for r in reviews:
            if db.review_exists(r["platform"], r["external_id"]):
                continue
            if r.get("already_replied"):
                continue
            review_id = db.upsert_review(
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
            queue.push(agent="reviews", payload={"action": "respond_to_review", "review_id": review_id})
            queue.push(agent="reviews", payload={"action": "flag_fake_review", "review_id": review_id})
            count += 1
        return count

    for listing in cfg.get("listings", {}).get("yelp", []):
        business = listing.get("business", "")
        if business:
            try:
                new_total += _ingest(yelp.poll(business))
            except Exception as exc:
                logger.error("poll_yelp_failed", business=business, error=str(exc))

    for listing in cfg.get("listings", {}).get("facebook", []):
        business = listing.get("business", "")
        if business:
            try:
                new_total += _ingest(fb.poll(business))
            except Exception as exc:
                logger.error("poll_facebook_failed", business=business, error=str(exc))

    logger.info("poll_reviews_yelp_facebook_ran", new_reviews=new_total)


@app.task(name="agents.reviews.tasks.check_reputation_scores", ignore_result=True)
def check_reputation_scores() -> None:
    """Check rolling review averages and alert if below threshold — daily."""
    from agents._base import AgentConfig
    from agents.reviews.db import ReviewsDB
    from agents.integrations.connectors.slack import SlackConnector
    from shared.config.settings import settings
    from shared.logger import get_logger
    from shared.queue.queue import TaskQueue

    logger = get_logger(__name__)
    cfg = AgentConfig.load("reviews").custom
    db = ReviewsDB()
    queue = TaskQueue()

    thresholds = cfg.get("alert_thresholds", {"trusted_plumbing": 4.5})
    default_threshold = 4.2
    rolling_days = int(cfg.get("rolling_average_days", 30))

    listings: set[str] = set()
    for platform_listings in cfg.get("listings", {}).values():
        for item in platform_listings:
            if item.get("business"):
                listings.add(item["business"])

    for business in listings:
        avg = db.rolling_average(business, rolling_days)
        count = db.recent_review_count(business, rolling_days)
        if avg is None or count < 5:
            continue
        threshold = thresholds.get(business, default_threshold)
        if avg >= threshold:
            continue
        try:
            slack = SlackConnector(called_by="reviews", method_name="check_reputation")
            channel = getattr(settings, "REVIEWS_ALERT_CHANNEL", "#reviews")
            slack.send_message(
                channel,
                f"*Reputation alert — {business}*\n"
                f"Rolling {rolling_days}-day average: {avg:.2f} "
                f"(threshold: {threshold}, reviews: {count})",
            )
        except Exception as exc:
            logger.error("check_reputation_slack_failed", business=business, error=str(exc))
        queue.push(
            agent="strategy",
            payload={
                "action": "reputation_alert",
                "business": business,
                "rolling_avg": round(avg, 2),
                "threshold": threshold,
                "review_count": count,
                "days": rolling_days,
            },
        )
        logger.info("reputation_alert_sent", business=business, avg=round(avg, 2))
