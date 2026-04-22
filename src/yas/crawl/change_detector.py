"""HTML normalization + content hashing for cheap change detection."""

from __future__ import annotations

import hashlib
import re

from selectolax.parser import HTMLParser

_NOISE_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside")
_NOISE_CLASS_TERMS = ("cookie", "banner", "notification", "timestamp", "csrf", "track")
_NOISE_ATTR_PREFIXES = ("data-", "aria-")
_NOISE_ATTRS = {"style"}
_WS_RE = re.compile(r"\s+")


def normalize(html: str) -> str:
    """Strip dynamic/navigational noise; return canonical visible text."""
    tree = HTMLParser(html)
    # 1. Kill whole subtrees that never contribute stable content.
    for tag in _NOISE_TAGS:
        for node in tree.css(tag):
            node.decompose()
    # 2. Drop elements whose class name contains any noise term.
    for node in tree.css("[class]"):
        classes = (node.attributes.get("class") or "").lower()
        if any(term in classes for term in _NOISE_CLASS_TERMS):
            node.decompose()
    # 3. Strip attributes everywhere so presentational churn can't change the hash.
    for node in tree.css("*"):
        attrs = dict(node.attributes or {})
        for name in list(attrs.keys()):
            if (
                name in _NOISE_ATTRS
                or any(name.startswith(prefix) for prefix in _NOISE_ATTR_PREFIXES)
            ):
                del node.attrs[name]
    # 4. Emit visible text only.
    text = tree.body.text(separator=" ", strip=True) if tree.body else ""
    # 5. Collapse whitespace.
    return _WS_RE.sub(" ", text).strip()


def content_hash(normalized: str) -> str:
    """SHA-256 of the normalized string; hex-digested."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
