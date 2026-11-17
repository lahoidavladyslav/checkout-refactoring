"""Engine factory."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


def create_db_engine(url: str) -> Engine:
    """``pool_pre_ping`` makes the pool discard connections the server has closed."""
    return create_engine(url, pool_pre_ping=True)
