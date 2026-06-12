"""Monthly infra/tool cost collection and gross margin calculation."""

from __future__ import annotations

from datetime import date

from shared.config.settings import settings
from shared.logger import get_logger

from .db import FinanceDB

logger = get_logger(__name__)

# Vendor cost fetchers — each returns cost in cents for the current month.
# Real integrations hit vendor APIs; we provide a stub/env-based fallback.


class CostTracker:
    def __init__(self, config: dict, db: FinanceDB | None = None) -> None:
        self._cfg = config
        self._db = db or FinanceDB()
        self._vendors: list[dict] = config.get("vendors", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Collect costs from all configured vendors for the current month."""
        period_month = date.today().replace(day=1)
        totals: dict[str, int] = {}

        for vendor_cfg in self._vendors:
            vendor = vendor_cfg["name"]
            category = vendor_cfg.get("category", "infrastructure")
            try:
                cost_cents = self._fetch_vendor_cost(vendor)
                self._db.upsert_cost_snapshot(
                    period_month=period_month,
                    vendor=vendor,
                    cost_cents=cost_cents,
                    category=category,
                )
                totals[vendor] = cost_cents
            except Exception as exc:
                logger.error("cost_fetch_failed", vendor=vendor, error=str(exc))
                totals[vendor] = 0

        total_cost = sum(totals.values())
        return {
            "period_month": str(period_month),
            "vendor_costs": totals,
            "total_cost_cents": total_cost,
            "total_cost_usd": total_cost / 100,
        }

    def gross_margin(self, mrr_cents: int, period_month: date | None = None) -> dict:
        """Return gross margin given MRR and infra costs for the month."""
        if period_month is None:
            period_month = date.today().replace(day=1)
        cost_cents = self._db.get_total_cost_for_month(period_month)
        gross_profit = mrr_cents - cost_cents
        margin_pct = (gross_profit / mrr_cents * 100) if mrr_cents else 0.0
        return {
            "mrr_cents": mrr_cents,
            "cost_cents": cost_cents,
            "gross_profit_cents": gross_profit,
            "gross_margin_pct": round(margin_pct, 2),
        }

    # ------------------------------------------------------------------
    # Vendor-specific fetchers
    # ------------------------------------------------------------------

    def _fetch_vendor_cost(self, vendor: str) -> int:
        fetcher = {
            "contabo": self._contabo_cost,
            "anthropic": self._anthropic_cost,
            "vercel": self._vercel_cost,
        }.get(vendor, self._env_cost(vendor))
        return fetcher()

    def _contabo_cost(self) -> int:
        # Contabo charges flat monthly — read from env/settings
        raw = getattr(settings, "CONTABO_MONTHLY_COST_CENTS", None)
        return int(raw) if raw else 0

    def _anthropic_cost(self) -> int:
        raw = getattr(settings, "ANTHROPIC_MONTHLY_COST_CENTS", None)
        return int(raw) if raw else 0

    def _vercel_cost(self) -> int:
        raw = getattr(settings, "VERCEL_MONTHLY_COST_CENTS", None)
        return int(raw) if raw else 0

    def _env_cost(self, vendor: str):
        def _fetch() -> int:
            key = f"{vendor.upper()}_MONTHLY_COST_CENTS"
            raw = getattr(settings, key, None)
            return int(raw) if raw else 0
        return _fetch
