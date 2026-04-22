"""Single-row household settings with immediate-geocode on home-address save."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.crawl.normalize import normalize_name
from yas.db.models import GeocodeAttempt, HouseholdSettings, Location
from yas.db.session import session_scope
from yas.geo.client import Geocoder
from yas.web.routes.household_schemas import HouseholdOut, HouseholdPatch

router = APIRouter(prefix="/api/household", tags=["household"])


def _engine(req: Request) -> Any:
    return req.app.state.yas.engine


def _geocoder(req: Request) -> Geocoder | None:
    return req.app.state.yas.geocoder  # type: ignore[no-any-return]


async def _load_or_create(session: AsyncSession) -> HouseholdSettings:
    hh = (await session.execute(select(HouseholdSettings))).scalars().first()
    if hh is None:
        hh = HouseholdSettings(id=1)
        session.add(hh)
        await session.flush()
    return hh


@router.get("", response_model=HouseholdOut)
async def get_household(request: Request) -> HouseholdOut:
    async with session_scope(_engine(request)) as s:
        hh = await _load_or_create(s)
        return HouseholdOut.model_validate(hh)


@router.patch("", response_model=HouseholdOut)
async def patch_household(patch: HouseholdPatch, request: Request) -> HouseholdOut:
    geocoder = _geocoder(request)
    async with session_scope(_engine(request)) as s:
        hh = await _load_or_create(s)
        data = patch.model_dump(exclude_unset=True)

        # Handle home_address ergonomics: create/update a Location row.
        address = data.pop("home_address", None)
        loc_name = data.pop("home_location_name", None) or "Home"
        if address is not None:
            existing_id = hh.home_location_id
            if existing_id is not None:
                loc = (
                    await s.execute(select(Location).where(Location.id == existing_id))
                ).scalar_one()
                loc.name = loc_name
                loc.address = address
                loc.lat = None  # invalidate; will re-geocode
                loc.lon = None
            else:
                loc = Location(name=loc_name, address=address)
                s.add(loc)
                await s.flush()
                hh.home_location_id = loc.id
            # Immediate geocode attempt.
            if geocoder is not None:
                try:
                    result = await geocoder.geocode(address)
                except Exception:
                    result = None
                addr_norm = normalize_name(address)
                prior = (
                    await s.execute(
                        select(GeocodeAttempt).where(GeocodeAttempt.address_norm == addr_norm)
                    )
                ).scalar_one_or_none()
                now = datetime.now(UTC)
                if result is not None:
                    loc.lat = result.lat
                    loc.lon = result.lon
                    if prior is None:
                        s.add(GeocodeAttempt(address_norm=addr_norm, last_tried=now, result="ok"))
                    else:
                        prior.last_tried = now
                        prior.result = "ok"
                else:
                    if prior is None:
                        s.add(
                            GeocodeAttempt(
                                address_norm=addr_norm,
                                last_tried=now,
                                result="not_found",
                            )
                        )
                    else:
                        prior.last_tried = now
                        prior.result = "not_found"

        for key, value in data.items():
            setattr(hh, key, value)

        await s.flush()
        return HouseholdOut.model_validate(hh)
