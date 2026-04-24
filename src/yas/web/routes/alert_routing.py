"""CRUD endpoints for /api/alert_routing."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import AlertRouting, HouseholdSettings
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.logging import get_logger
from yas.web.routes.alert_routing_schemas import AlertRoutingOut, AlertRoutingPatch

log = get_logger("yas.web.alert_routing")

router = APIRouter(prefix="/api/alert_routing", tags=["alert_routing"])

# Known channel types in the system
_KNOWN_CHANNELS = {"email", "ntfy", "pushover"}


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


def _get_configured_channels(household: HouseholdSettings | None) -> set[str]:
    """Return the set of configured notifier channel names from household settings."""
    configured: set[str] = set()
    if household is None:
        return configured

    if household.smtp_config_json is not None:
        configured.add("email")
    if household.ntfy_config_json is not None:
        configured.add("ntfy")
    if household.pushover_config_json is not None:
        configured.add("pushover")

    return configured


@router.get("", response_model=list[AlertRoutingOut])
async def list_alert_routing(request: Request) -> list[AlertRoutingOut]:
    """Return all alert routing configurations."""
    async with session_scope(_engine(request)) as s:
        rows = (await s.execute(select(AlertRouting))).scalars().all()
        return [AlertRoutingOut.model_validate(row) for row in rows]


@router.patch("/{alert_type}", response_model=AlertRoutingOut)
async def patch_alert_routing(
    request: Request,
    alert_type: AlertType,
    body: AlertRoutingPatch,
) -> AlertRoutingOut:
    """Update alert routing for a specific alert type.

    Validate channels against configured notifiers:
    - Unknown channel names (not in {email, ntfy, pushover}) → 422.
    - Known but unconfigured channels → 200 (warn log, pass validation).
    """
    # Check that at least one field is being updated
    if body.channels is None and body.enabled is None:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'channels' or 'enabled' must be provided",
        )

    async with session_scope(_engine(request)) as s:
        # Fetch the routing row
        row = (
            await s.execute(
                select(AlertRouting).where(AlertRouting.type == alert_type.value)
            )
        ).scalar_one_or_none()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"alert routing for type {alert_type} not found",
            )

        # Validate channels if provided
        if body.channels is not None:
            # Load household to check configured channels
            household = (
                await s.execute(select(HouseholdSettings).limit(1))
            ).scalar_one_or_none()
            configured = _get_configured_channels(household)

            # Check for unknown channel names
            for ch in body.channels:
                if ch not in _KNOWN_CHANNELS:
                    raise HTTPException(
                        status_code=422,
                        detail=f"unknown channel type: {ch}",
                    )

            # Warn about known but unconfigured channels
            for ch in body.channels:
                if ch in _KNOWN_CHANNELS and ch not in configured:
                    log.warning(
                        "channel.not_configured",
                        channel=ch,
                        alert_type=alert_type.value,
                    )

            row.channels = body.channels

        if body.enabled is not None:
            row.enabled = body.enabled

        s.add(row)
        await s.flush()

        return AlertRoutingOut.model_validate(row)
