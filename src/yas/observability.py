"""Error reporting to a Sentry-protocol endpoint (GlitchTip).

Reporting is explicit: structlog here writes straight to stderr through
PrintLoggerFactory and never touches stdlib ``logging``, so Sentry's logging
integration cannot see ``log.error`` calls. Sites that should reach GlitchTip
call ``sentry_sdk.capture_exception`` / ``capture_message`` themselves; see
docs/observability.md for which sites do and why.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.transport import Transport
from sentry_sdk.types import Breadcrumb, BreadcrumbHint

from yas.config import Settings
from yas.db.models import Page, Site

# sentry-sdk's httpx integration records every request as an `httplib`
# breadcrumb, query string included. Nominatim requests carry the household
# address in `q=`, and crawl URLs add nothing the crawl tags don't already say.
_DROPPED_BREADCRUMB_CATEGORIES = frozenset({"httplib"})


def _drop_network_breadcrumb(crumb: Breadcrumb, _hint: BreadcrumbHint) -> Breadcrumb | None:
    if crumb.get("category") in _DROPPED_BREADCRUMB_CATEGORIES:
        return None
    return crumb


def init_sentry(settings: Settings, *, transport: Transport | None = None) -> bool:
    """Initialise the SDK once per process. Returns False (and does nothing) without a DSN.

    ``transport`` exists for tests, which swap in an in-memory one.
    """
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        release=None if settings.git_sha == "unknown" else settings.git_sha,
        environment=settings.sentry_environment,
        traces_sample_rate=0,
        send_default_pii=False,
        # Default is "every URL": sentry-trace + baggage (which embeds the DSN
        # public key) would go to every site the crawler fetches.
        trace_propagation_targets=[],
        before_breadcrumb=_drop_network_breadcrumb,
        integrations=[
            # App logs never pass through stdlib logging (see module docstring),
            # so stdlib breadcrumbs are only third-party noise — httpx's INFO
            # line includes the full request URL. Third-party ERROR records
            # (uvicorn's "Exception in ASGI application", asyncio) still report.
            LoggingIntegration(level=None, event_level=logging.ERROR),
        ],
        transport=transport,
    )
    return True


def crawl_scope(site: Site, page: Page) -> dict[str, Any]:
    """Scope kwargs for ``capture_exception`` / ``capture_message`` on a crawl failure.

    Tags let GlitchTip filter and break an issue down by site; they don't change
    grouping. Failures caused by one site's content pass their own per-site
    ``fingerprint`` as well, so each site gets its own issue.
    """
    return {
        "tags": {"site": site.name, "site_id": str(site.id), "page_id": str(page.id)},
        "contexts": {"crawl": {"page_url": page.url, "site_url": site.base_url}},
    }


def browser_sentry_dsn(value: str | None) -> str | None:
    """The browser DSN if it is safe to render into public HTML, else None.

    Soft-validated: anything wrong means "browser reporting off", never a
    crash. A real DSN's userinfo is the public key only; one carrying a
    password is a pasted wrong URL and would go to every visitor's browser.
    """
    dsn = (value or "").strip()
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.password is not None:
        return None
    return dsn
