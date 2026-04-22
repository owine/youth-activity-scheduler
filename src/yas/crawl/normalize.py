"""Name normalization shared by the reconciler (today) and the matcher (Phase 3)."""

from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_name(s: str) -> str:
    """lowercase → strip punctuation → collapse whitespace → trim."""
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s
