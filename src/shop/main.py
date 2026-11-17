"""Production entry point.

Run with ``uvicorn --factory shop.main:build_app``.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI

from shop.api.app import create_app
from shop.composition import Settings, build_container


def build_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    client = httpx.Client(timeout=settings.http_timeout)
    container = build_container(settings, http_client=client)
    return create_app(
        checkout=container.checkout, orders=container.orders, on_shutdown=client.close
    )
