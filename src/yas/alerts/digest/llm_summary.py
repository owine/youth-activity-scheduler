"""LLM-powered top-line generator for digest emails, with template fallback."""

from __future__ import annotations

import json
from typing import Any

from yas.alerts.digest.builder import DigestPayload
from yas.llm.client import LLMClient
from yas.logging import get_logger

_log = get_logger(__name__)

_TOOL_NAME = "report_top_line"
_TOOL_DESCRIPTION = "Produce a single-line summary of today's digest for the household."
_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "top_line": {
            "type": "string",
            "description": "One-sentence summary under 200 characters.",
        },
    },
    "required": ["top_line"],
}
_SYSTEM_PROMPT = (
    "You are writing a friendly one-line summary of today's activity digest for a parent. "
    "Keep it under 200 characters. Focus on the most interesting items. Do not use emojis."
)
_MAX_TOKENS = 256


def _fallback(payload: DigestPayload) -> str:
    return (
        f"{payload.kid_name}'s activities — "
        f"{len(payload.new_matches)} new matches, "
        f"{len(payload.registration_calendar)} opening soon"
    )


async def generate_top_line(
    payload: DigestPayload,
    llm: LLMClient | None,
    *,
    cost_cap_remaining_usd: float,
) -> str:
    """Generate a one-line digest summary, falling back to a template when needed.

    Parameters
    ----------
    payload:
        The assembled digest payload for one kid.
    llm:
        An LLMClient instance, or ``None`` to skip LLM entirely.
    cost_cap_remaining_usd:
        Remaining budget in USD. If below $0.01 the LLM is skipped.
    """
    if llm is None:
        _log.info(
            "llm_summary.fallback",
            reason="llm_is_none",
            kid_name=payload.kid_name,
        )
        return _fallback(payload)

    if cost_cap_remaining_usd < 0.01:
        _log.warning(
            "llm_summary.fallback",
            reason="cost_cap_exhausted",
            cost_cap_remaining_usd=cost_cap_remaining_usd,
            kid_name=payload.kid_name,
        )
        return _fallback(payload)

    user_json: dict[str, Any] = {
        "kid_name": payload.kid_name,
        "new_matches_count": len(payload.new_matches),
        "starting_soon_count": len(payload.starting_soon),
        "registration_opens_soon_count": len(payload.registration_calendar),
        "top_new_matches": [m.get("offering_name", "") for m in payload.new_matches[:3]],
        "top_registration_opens": [r.get("offering_name", "") for r in payload.registration_calendar[:3]],
    }
    user = json.dumps(user_json)

    try:
        result_tuple = await llm.call_tool(
            system=_SYSTEM_PROMPT,
            user=user,
            tool_name=_TOOL_NAME,
            tool_description=_TOOL_DESCRIPTION,
            input_schema=_INPUT_SCHEMA,
            max_tokens=_MAX_TOKENS,
        )
        result = result_tuple[0]
    except Exception as exc:
        _log.warning(
            "llm_summary.fallback",
            reason="llm_exception",
            exc=str(exc),
            kid_name=payload.kid_name,
        )
        return _fallback(payload)

    top_line: str = result.get("top_line", "")

    if not top_line:
        _log.warning(
            "llm_summary.fallback",
            reason="empty_top_line",
            kid_name=payload.kid_name,
        )
        return _fallback(payload)

    if len(top_line) > 200:
        _log.warning(
            "llm_summary.fallback",
            reason="top_line_too_long",
            length=len(top_line),
            kid_name=payload.kid_name,
        )
        return _fallback(payload)

    return top_line
