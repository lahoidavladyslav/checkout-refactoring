"""Translation of domain errors into HTTP responses."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shop.api.schemas import ErrorBody, ErrorOut
from shop.domain.errors import (
    CheckoutError,
    DomainError,
    InvalidMoneyError,
    InvalidTransitionError,
    OrderNotFoundError,
    PaymentDeclinedError,
    PaymentGatewayUnavailableError,
)

# Lookup walks the exception's MRO, so a subclass inherits the status of its closest parent.
_STATUS: dict[type, int] = {
    PaymentDeclinedError: 402,
    PaymentGatewayUnavailableError: 502,
    OrderNotFoundError: 404,
    InvalidTransitionError: 409,
    InvalidMoneyError: 422,
    CheckoutError: 422,
}


def _status_for(error: DomainError) -> int:
    for cls in type(error).__mro__:
        if cls in _STATUS:
            return _STATUS[cls]
    return 400


def _respond(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status, content=ErrorOut(error=body).model_dump(exclude_none=True)
    )


async def _domain_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast(DomainError, exc)
    return _respond(_status_for(error), ErrorBody(code=error.code, message=error.message))


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    invalid = cast(RequestValidationError, exc)
    # `input` is dropped from every entry: it echoes the offending value, which may be a card.
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in invalid.errors()
    ]
    return _respond(
        422, ErrorBody(code="validation_error", message="request is invalid", details=details)
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
