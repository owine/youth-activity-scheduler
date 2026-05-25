"""Programmatic Alembic runner used at process startup.

Every yas process calls `upgrade_to_head` before opening the SQLAlchemy
engine, replacing the dedicated `yas-migrate` compose service.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from yas.logging import get_logger

log = get_logger(__name__)


def _find_alembic_ini() -> Path:
    """Locate alembic.ini.

    The package can be installed editable (file lives under src/yas/db/) or
    non-editable into site-packages (file lives under .venv/.../yas/db/).
    Repo-root layout and image layout both put alembic.ini next to a top-level
    directory we can find by walking up from CWD. Prefer CWD because the image
    sets WORKDIR /app and the repo's pytest runs from the repo root.
    """
    cwd_candidate = Path.cwd() / "alembic.ini"
    if cwd_candidate.is_file():
        return cwd_candidate
    # Fallback: walk up from this file looking for alembic.ini. Handles the
    # less common case where CWD doesn't contain it.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("alembic.ini not found from CWD or via parent walk")


def upgrade_to_head(database_url: str) -> None:
    """Apply pending Alembic migrations against `database_url`.

    Idempotent: a no-op when the database is already at head.
    """
    cfg = Config(str(_find_alembic_ini()))
    # Pass URL via attributes — env.py's gate reads it from there and
    # propagates to set_main_option for both online and offline runners.
    # See alembic/env.py for the contract.
    cfg.attributes["sqlalchemy.url"] = database_url
    log.info("migrations.start", url=database_url)
    command.upgrade(cfg, "head")
    log.info("migrations.done")
