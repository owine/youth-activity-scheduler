"""Shared Jinja Environment for all outbound-email templates.

StrictUndefined is the linchpin: a template referencing a field its payload
doesn't have raises UndefinedError at render, which the delivery layer routes
into the same skipped-alert + 'Delivery Issues' machinery as a permanent send
failure. Silent half-rendered emails are the bug we're fixing.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from yas.email.filters import fmt as fmt_filter
from yas.email.filters import price as price_filter
from yas.email.filters import rel_date as rel_date_filter

_TEMPLATES_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html", "html.j2")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["price"] = price_filter
env.filters["rel_date"] = rel_date_filter
env.filters["fmt"] = fmt_filter
