"""Read-only /api/matches endpoint with filters + pagination."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import Location, Match, Offering, Site
from yas.db.session import session_scope
from yas.web.routes.matches_schemas import MatchOut, OfferingSummary

router = APIRouter(prefix="/api/matches", tags=["matches"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("", response_model=list[MatchOut])
async def list_matches(
    request: Request,
    kid_id: int | None = Query(default=None),
    offering_id: int | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[MatchOut]:
    async with session_scope(_engine(request)) as s:
        q = (
            select(Match, Offering, Site.name, Location.lat, Location.lon)
            .join(Offering, Match.offering_id == Offering.id)
            .join(Site, Site.id == Offering.site_id)
            .outerjoin(Location, Location.id == Offering.location_id)
        )
        if kid_id is not None:
            q = q.where(Match.kid_id == kid_id)
        if offering_id is not None:
            q = q.where(Match.offering_id == offering_id)
        if min_score is not None:
            q = q.where(Match.score >= min_score)
        q = q.order_by(Match.score.desc()).limit(limit).offset(offset)
        rows = (await s.execute(q)).all()
        result: list[MatchOut] = []
        for match, offering, site_name, loc_lat, loc_lon in rows:
            offering_data = {
                k: getattr(offering, k)
                for k in OfferingSummary.model_fields
                if k not in ("site_name", "registration_opens_at", "location_lat", "location_lon")
            }
            offering_data["site_name"] = site_name
            offering_data["registration_opens_at"] = offering.registration_opens_at
            offering_data["location_lat"] = loc_lat
            offering_data["location_lon"] = loc_lon
            result.append(
                MatchOut(
                    kid_id=match.kid_id,
                    offering_id=match.offering_id,
                    score=match.score,
                    reasons=match.reasons,
                    computed_at=match.computed_at,
                    offering=OfferingSummary.model_validate(offering_data),
                )
            )
        return result
