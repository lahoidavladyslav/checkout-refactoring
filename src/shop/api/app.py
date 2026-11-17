"""HTTP layer: parse, call a service, translate the result. No business logic."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request

from shop.api.errors import install_error_handlers
from shop.api.middleware import CorrelationIdMiddleware
from shop.api.schemas import CheckoutIn, ErrorOut, OrderOut, StatusChangeIn
from shop.application.checkout import CheckoutService
from shop.application.orders import OrderService

_ERRORS: dict[int | str, dict[str, Any]] = {
    402: {"model": ErrorOut, "description": "The card was declined"},
    404: {"model": ErrorOut, "description": "No such order"},
    409: {"model": ErrorOut, "description": "The status change is not allowed"},
    422: {"model": ErrorOut, "description": "The request was rejected"},
    502: {"model": ErrorOut, "description": "The payment provider is unavailable"},
}


def _checkout_service(request: Request) -> CheckoutService:
    service: CheckoutService = request.app.state.checkout
    return service


def _order_service(request: Request) -> OrderService:
    service: OrderService = request.app.state.orders
    return service


CheckoutDep = Annotated[CheckoutService, Depends(_checkout_service)]
OrdersDep = Annotated[OrderService, Depends(_order_service)]


def create_app(
    *,
    checkout: CheckoutService,
    orders: OrderService,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if on_shutdown:
            on_shutdown()

    app = FastAPI(title="Checkout", version="1.0.0", lifespan=lifespan)
    app.state.checkout = checkout
    app.state.orders = orders
    install_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    # The handlers are plain `def`: the services are blocking, so FastAPI runs them in its
    # thread pool instead of stalling the event loop.
    @app.post("/checkout", status_code=201, response_model=OrderOut, responses=_ERRORS)
    def place_order(body: CheckoutIn, service: CheckoutDep) -> OrderOut:
        return OrderOut.from_domain(service.place_order(body.to_command()))

    @app.get("/orders/{order_id}", response_model=OrderOut, responses=_ERRORS)
    def get_order(order_id: int, service: OrdersDep) -> OrderOut:
        return OrderOut.from_domain(service.get(order_id))

    @app.patch("/orders/{order_id}/status", response_model=OrderOut, responses=_ERRORS)
    def change_status(order_id: int, body: StatusChangeIn, service: OrdersDep) -> OrderOut:
        return OrderOut.from_domain(service.change_status(order_id, body.status))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
