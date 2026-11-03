"""Single-row household settings with immediate-geocode on home-address save."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.config import Settings
from yas.crawl.normalize import normalize_name
from yas.db.models import GeocodeAttempt, HouseholdSettings, Location, Offering
from yas.db.session import session_scope
from yas.geo.client import Geocoder, GeocoderUnavailable
from yas.geo.enricher import record_geocode_attempt
from yas.logging import get_logger
from yas.matching.matcher import rematch_all_active_kids
from yas.web.routes.household_schemas import CredentialStatus, HouseholdOut, HouseholdPatch

log = get_logger("yas.web.household")

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


async def _distance_inputs(
    session: AsyncSession, hh: HouseholdSettings
) -> tuple[int | None, float | None, float | None, float | None]:
    """What the matcher's distance gate reads from the household."""
    lat = lon = None
    if hh.home_location_id is not None:
        loc = await session.get(Location, hh.home_location_id)
        if loc is not None:
            lat, lon = loc.lat, loc.lon
    return (hh.home_location_id, lat, lon, hh.default_max_distance_mi)


async def _clear_home(session: AsyncSession, hh: HouseholdSettings) -> None:
    """Unset the home location, deleting its row unless an offering shares it."""
    loc_id = hh.home_location_id
    if loc_id is None:
        return
    hh.home_location_id = None
    await session.flush()
    shared = (
        await session.execute(select(Offering.id).where(Offering.location_id == loc_id).limit(1))
    ).first()
    if shared is None:
        loc = await session.get(Location, loc_id)
        if loc is not None:
            # Otherwise an ungeocoded orphan keeps the enricher retrying it.
            await session.delete(loc)


_SECRET_KEYS = {
    "password_value",
    "api_token_value",
    "auth_token_value",
    "user_key_value",
    "app_token_value",
}


_CHANNEL_CONFIG_KEYS = ("smtp_config_json", "ntfy_config_json", "pushover_config_json")


def _merge_secrets(
    incoming: dict[str, Any] | None, stored: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Carry stored secrets the incoming channel config omits.

    GET redacts secrets, so the settings form never has them to send back: it
    leaves a saved secret blank and omits it. Replacing the whole blob would
    wipe the secret on every unrelated save. An omitted key keeps the stored
    value; an explicit null or "" clears it; a value replaces it. Switching
    email transport drops the old one's secret, since it belongs to that
    transport alone.
    """
    if incoming is None:
        return None
    stored = stored or {}
    merged = dict(incoming)
    same_transport = incoming.get("transport") == stored.get("transport")
    for key in _SECRET_KEYS:
        if key in merged:
            if merged[key] is None or merged[key] == "":
                del merged[key]
        elif same_transport and key in stored:
            merged[key] = stored[key]
    return merged


def _redact_config(cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of the channel config with secret-bearing keys stripped.

    Non-secret fields (transport, host, port, from_addr, to_addrs,
    devices, base_url, topic, emergency_*) are preserved so the form
    can pre-populate them. Secret values stay server-side.
    """
    if cfg is None:
        return None
    return {k: v for k, v in cfg.items() if k not in _SECRET_KEYS}


def _credential_status(
    cfg: dict[str, Any] | None,
    *,
    value_key: str,
    env_var_name: str,
    settings_value: str | None,
) -> CredentialStatus:
    """Resolve where a single credential comes from.

    Form value wins over env. Returns via=None when neither is set so
    the UI can render an "unconfigured" state without guessing.
    """
    form_value = cfg.get(value_key) if cfg else None
    if form_value:
        return CredentialStatus(via="form", env_var=env_var_name)
    if settings_value:
        return CredentialStatus(via="env", env_var=env_var_name)
    return CredentialStatus(via=None, env_var=env_var_name)


def _settings(req: Request) -> Settings:
    return req.app.state.yas.settings  # type: ignore[no-any-return]


async def _to_out(s: AsyncSession, hh: HouseholdSettings, settings: Settings) -> HouseholdOut:
    loc = None
    if hh.home_location_id is not None:
        loc = (
            await s.execute(select(Location).where(Location.id == hh.home_location_id))
        ).scalar_one_or_none()
    # Always return all five credential statuses, regardless of whether
    # the user has saved a *_config_json row yet. Otherwise the badge
    # never appears on a fresh form even when env vars are set, leaving
    # users unsure whether they need to paste a value.
    smtp = hh.smtp_config_json
    cred_status: dict[str, CredentialStatus] = {
        "smtp_password": _credential_status(
            smtp if smtp and smtp.get("transport") == "smtp" else None,
            value_key="password_value",
            env_var_name="YAS_SMTP_PASSWORD",
            settings_value=settings.smtp_password,
        ),
        "forwardemail_api_token": _credential_status(
            smtp if smtp and smtp.get("transport") == "forwardemail" else None,
            value_key="api_token_value",
            env_var_name="YAS_FORWARDEMAIL_API_TOKEN",
            settings_value=settings.forwardemail_api_token,
        ),
        "ntfy_auth_token": _credential_status(
            hh.ntfy_config_json,
            value_key="auth_token_value",
            env_var_name="YAS_NTFY_AUTH_TOKEN",
            settings_value=settings.ntfy_auth_token,
        ),
        "pushover_user_key": _credential_status(
            hh.pushover_config_json,
            value_key="user_key_value",
            env_var_name="YAS_PUSHOVER_USER_KEY",
            settings_value=settings.pushover_user_key,
        ),
        "pushover_app_token": _credential_status(
            hh.pushover_config_json,
            value_key="app_token_value",
            env_var_name="YAS_PUSHOVER_APP_TOKEN",
            settings_value=settings.pushover_app_token,
        ),
    }

    return HouseholdOut(
        id=hh.id,
        home_location_id=hh.home_location_id,
        home_address=loc.address if loc else None,
        home_location_name=loc.name if loc else None,
        home_lat=loc.lat if loc else None,
        home_lon=loc.lon if loc else None,
        default_max_distance_mi=hh.default_max_distance_mi,
        digest_time=hh.digest_time,
        quiet_hours_start=hh.quiet_hours_start,
        quiet_hours_end=hh.quiet_hours_end,
        daily_llm_cost_cap_usd=hh.daily_llm_cost_cap_usd,
        email_configured=hh.smtp_config_json is not None,
        ntfy_configured=hh.ntfy_config_json is not None,
        pushover_configured=hh.pushover_config_json is not None,
        credential_status=cred_status,
        smtp_config_json=_redact_config(hh.smtp_config_json),
        ntfy_config_json=_redact_config(hh.ntfy_config_json),
        pushover_config_json=_redact_config(hh.pushover_config_json),
    )


@router.get("", response_model=HouseholdOut)
async def get_household(request: Request) -> HouseholdOut:
    async with session_scope(_engine(request)) as s:
        hh = await _load_or_create(s)
        return await _to_out(s, hh, _settings(request))


@router.patch("", response_model=HouseholdOut)
async def patch_household(patch: HouseholdPatch, request: Request) -> HouseholdOut:
    geocoder = _geocoder(request)
    async with session_scope(_engine(request)) as s:
        hh = await _load_or_create(s)
        data = patch.model_dump(exclude_unset=True)
        distance_before = await _distance_inputs(s, hh)

        # Handle home_address ergonomics: create/update a Location row.
        # Omitted means unchanged; an explicit null (or blank) clears it.
        address_sent = "home_address" in data
        address = data.pop("home_address", None)
        loc_name = data.pop("home_location_name", None) or "Home"
        if address_sent and (address is None or not address.strip()):
            await _clear_home(s, hh)
        elif address is not None:
            existing_id = hh.home_location_id
            needs_geocode = True
            if existing_id is not None:
                loc = (
                    await s.execute(select(Location).where(Location.id == existing_id))
                ).scalar_one()
                # The settings form re-sends home_address on every save, so an
                # unchanged address must keep its coordinates. Wiping them
                # during a geocoder outage would leave the distance gate
                # passing everything until the enricher's retry.
                same_address = normalize_name(address) == normalize_name(loc.address or "")
                needs_geocode = not same_address or loc.lat is None
                loc.name = loc_name
                loc.address = address
                if needs_geocode:
                    loc.lat = None  # invalidate; will re-geocode
                    loc.lon = None
            else:
                loc = Location(name=loc_name, address=address)
                s.add(loc)
                await s.flush()
                hh.home_location_id = loc.id
            # Immediate geocode attempt. On failure the Location keeps lat=None
            # and the enricher picks it up once enricher.retry_due allows.
            if geocoder is not None and needs_geocode:
                result = None
                outcome = "not_found"
                detail: str | None = None
                try:
                    result = await geocoder.geocode(address)
                except GeocoderUnavailable as exc:
                    log.warning(
                        "household.geocode_unavailable", location_id=loc.id, reason=str(exc)
                    )
                    outcome, detail = "unavailable", str(exc)
                except Exception as exc:
                    # The client turns transport/HTTP/parse trouble into
                    # GeocoderUnavailable, so anything else is a bug. Tagged by
                    # id, not address: the address is the household's home.
                    sentry_sdk.capture_exception(exc, tags={"location_id": str(loc.id)})
                    outcome, detail = "error", str(exc)
                addr_norm = normalize_name(address)
                prior = (
                    await s.execute(
                        select(GeocodeAttempt).where(GeocodeAttempt.address_norm == addr_norm)
                    )
                ).scalar_one_or_none()
                if result is not None:
                    loc.lat = result.lat
                    loc.lon = result.lon
                    outcome = "ok"
                record_geocode_attempt(
                    s, prior, addr_norm, outcome, now=datetime.now(UTC), detail=detail
                )

        for key in _CHANNEL_CONFIG_KEYS:
            if key in data:
                data[key] = _merge_secrets(data[key], getattr(hh, key))

        for key, value in data.items():
            setattr(hh, key, value)

        await s.flush()
        # The distance gate reads home coords and the default radius, so a change
        # to either must not wait for the daily sweep to take effect.
        if await _distance_inputs(s, hh) != distance_before:
            await rematch_all_active_kids(s)
            await s.flush()
        return await _to_out(s, hh, _settings(request))
