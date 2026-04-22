"""Deterministic junk-URL filter for discovery candidates.

Filters out navigation/boilerplate and non-document URLs before the LLM
classifier sees them, saving tokens on predictable garbage. PDFs are NOT
filtered — discovery surfaces them with kind="pdf" for visibility.
"""

from __future__ import annotations

from urllib.parse import urlparse

_PATH_PREFIX_REJECTS: tuple[str, ...] = (
    "/wp-admin",
    "/wp-content",
    "/wp-json",
    "/wp-login",
    "/feed",
    "/author/",
    "/tag/",
    "/category/",
    "/comments/",
    "/comments",
    "/login",
    "/logout",
    "/account",
    "/cart",
    "/checkout",
)

_QUERY_SIGNATURES: tuple[str, ...] = ("replytocom=", "s=")

_REJECTED_EXTENSIONS: tuple[str, ...] = (
    ".xml",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)


def is_junk(url: str) -> bool:
    """True if URL should be dropped before classification."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(path.startswith(p) for p in _PATH_PREFIX_REJECTS):
        return True
    if any(path.endswith(ext) for ext in _REJECTED_EXTENSIONS):
        return True
    query = parsed.query
    return bool(query) and any(sig in query for sig in _QUERY_SIGNATURES)
