"""Connector registry — maps service name strings to connector classes."""
from __future__ import annotations

from .connectors.backblaze import BackblazeConnector
from .connectors.base_connector import BaseConnector
from .connectors.calendly import CalendlyConnector
from .connectors.cloudflare import CloudflareConnector
from .connectors.github import GitHubConnector
from .connectors.google_ads import GoogleAdsConnector
from .connectors.google_analytics import GoogleAnalyticsConnector
from .connectors.google_business_profile import GoogleBusinessProfileConnector
from .connectors.google_workspace import GoogleWorkspaceConnector
from .connectors.meta_ads import MetaAdsConnector
from .connectors.quickbooks import QuickBooksConnector
from .connectors.railway import RailwayConnector
from .connectors.slack import SlackConnector
from .connectors.square import SquareConnector
from .connectors.stripe import StripeConnector
from .connectors.supabase import SupabaseConnector
from .connectors.twenty_crm import TwentyCRMConnector
from .connectors.twilio import TwilioConnector
from .connectors.vercel import VercelConnector

_REGISTRY: dict[str, type[BaseConnector]] = {
    "github": GitHubConnector,
    "vercel": VercelConnector,
    "cloudflare": CloudflareConnector,
    "railway": RailwayConnector,
    "supabase": SupabaseConnector,
    "stripe": StripeConnector,
    "square": SquareConnector,
    "quickbooks": QuickBooksConnector,
    "google_workspace": GoogleWorkspaceConnector,
    "google_analytics": GoogleAnalyticsConnector,
    "google_ads": GoogleAdsConnector,
    "google_business_profile": GoogleBusinessProfileConnector,
    "meta_ads": MetaAdsConnector,
    "slack": SlackConnector,
    "twilio": TwilioConnector,
    "calendly": CalendlyConnector,
    "twenty_crm": TwentyCRMConnector,
    "backblaze": BackblazeConnector,
}


def get_connector(service: str) -> type[BaseConnector]:
    cls = _REGISTRY.get(service)
    if cls is None:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown service '{service}'. Available: {available}")
    return cls


def list_services() -> list[str]:
    return sorted(_REGISTRY)
