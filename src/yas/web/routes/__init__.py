from yas.web.routes.alert_routing import router as alert_routing_router
from yas.web.routes.alerts import router as alerts_router
from yas.web.routes.digest_preview import router as digest_preview_router
from yas.web.routes.enrollments import router as enrollments_router
from yas.web.routes.household import router as household_router
from yas.web.routes.kids import router as kids_router
from yas.web.routes.matches import router as matches_router
from yas.web.routes.sites import router as sites_router
from yas.web.routes.unavailability import router as unavailability_router
from yas.web.routes.watchlist import router as watchlist_router

__all__ = [
    "alert_routing_router",
    "alerts_router",
    "digest_preview_router",
    "enrollments_router",
    "household_router",
    "kids_router",
    "matches_router",
    "sites_router",
    "unavailability_router",
    "watchlist_router",
]
