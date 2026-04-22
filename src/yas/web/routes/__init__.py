from yas.web.routes.household import router as household_router
from yas.web.routes.kids import router as kids_router
from yas.web.routes.sites import router as sites_router
from yas.web.routes.unavailability import router as unavailability_router
from yas.web.routes.watchlist import router as watchlist_router

__all__ = [
    "household_router",
    "kids_router",
    "sites_router",
    "unavailability_router",
    "watchlist_router",
]
