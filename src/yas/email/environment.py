"""Shared Jinja Environment for all outbound-email templates.

StrictUndefined is the linchpin: a template referencing a field its payload
doesn't have raises UndefinedError at render, which the delivery layer routes
into the same skipped-alert + 'Delivery Issues' machinery as a permanent send
failure. Silent half-rendered emails are the bug we're fixing.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

# Temporary import: filters currently live in yas.alerts.digest. Task 4 of the
# email-template-layer plan relocates them to yas.email.filters and replaces
# yas.alerts.digest.filters with a re-export shim. Do not add new
# yas.email -> yas.alerts imports — this is the only one.
from yas.alerts.digest.filters import fmt as fmt_filter
from yas.alerts.digest.filters import price as price_filter
from yas.alerts.digest.filters import rel_date as rel_date_filter

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
