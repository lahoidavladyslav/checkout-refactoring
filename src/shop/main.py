"""Production entry point.

Run with ``uvicorn --factory shop.main:build_app``.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from shop.api.app import create_app
from shop.composition import Settings, build_container
from shop.observability import configure_logging


def build_app() -> FastAPI:
    configure_logging()
    settings = Settings.from_env()
    client = httpx.Client(timeout=settings.http_timeout)
    container = build_container(settings, http_client=client)
    return create_app(
        checkout=container.checkout, orders=container.orders, on_shutdown=client.close
    )
