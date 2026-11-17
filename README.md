# shop-checkout

The checkout module of an online store, refactored from a single legacy function into a small,
layered, fully tested service with an HTTP API.

The legacy function (`legacy/checkout.py`, kept untouched as a behavioural reference) did everything in
one place: validation, pricing, charging, persistence, logging and notifications. Adding a promo code
or a delivery method meant editing the same `if/elif` chains and hoping nothing else broke.
This project keeps the observable behaviour, fixes the defects that were found on the way, and makes
the parts that change most often additive.

- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API](#api)
- [Business rules](#business-rules)
- [Development](#development)
- [How behaviour is preserved](#how-behaviour-is-preserved)
- [Proving the design is open for extension](#proving-the-design-is-open-for-extension)
- [Project layout](#project-layout)
- [Optional tasks](#optional-tasks)
- [Documentation](#documentation)

## Quick start

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # install dependencies, including dev tools
make check              # lint, types, architecture contracts, tests
make run                # http://127.0.0.1:8000  (docs at /docs)
```

`make run` is `uvicorn --factory shop.main:build_app --reload`.

## Configuration

All settings come from environment variables and have defaults, see `shop/composition.py`.

| Variable | Default | Meaning |
|---|---|---|
| `SHOP_PAYMENTS_URL` | `https://payments.example.com/charge` | Payment provider endpoint |
| `SHOP_MAIL_URL` | `https://mail.example.com/send` | Email service endpoint |
| `SHOP_SLACK_URL` | `https://slack.example.com/hook` | Slack webhook |
| `SHOP_HTTP_TIMEOUT` | `5` | Timeout in seconds for email and Slack calls |
| `SHOP_PAYMENT_TIMEOUT` | `10` | Timeout in seconds for payment calls |

The cash-on-delivery limit (5000) and the big-order alert threshold (10000) are fields of `Settings` and
are wired in the composition root, not hard-coded in the services.

## API

Interactive documentation is served at `/docs`.

| Method and path | Purpose | Success |
|---|---|---|
| `POST /checkout` | Place an order | `201` and the order |
| `GET /orders/{id}` | Fetch an order | `200` |
| `PATCH /orders/{id}/status` | Move an order to another status | `200` and the order |
| `GET /health` | Liveness | `200` |

Amounts in responses are strings with two decimals (`"145.00"`), never floats.

### Place an order

```bash
curl -s -X POST localhost:8000/checkout \
  -H 'content-type: application/json' \
  -d '{
        "items": [{"price": "100.00", "qty": 2}, {"price": "30.00", "qty": 1}],
        "email": "buyer@example.com",
        "promo": "BUY3",
        "delivery": "pickup",
        "payment": "cod"
      }'
```

```json
{
  "id": 1,
  "email": "buyer@example.com",
  "items": [
    {"price": "100.00", "qty": 2, "title": null},
    {"price": "30.00", "qty": 1, "title": null}
  ],
  "total": "200.00",
  "status": "new",
  "created_at": "2026-11-17T09:02:08.732785Z"
}
```

Pay by card as a VIP customer (the card token is forwarded to the payment provider and nowhere else):

```bash
curl -s -X POST localhost:8000/checkout \
  -H 'content-type: application/json' \
  -d '{
        "items": [{"price": "1000.00", "qty": 1}],
        "email": "vip@example.com",
        "user_type": "vip",
        "promo": "SALE10",
        "delivery": "nova",
        "payment": "card",
        "card": "tok_visa"
      }'
```

Request fields: `items` (`price` with at most two decimals, integer `qty`, optional `title`), `email`,
`promo`, `user_type` (`vip`, `b2b`, anything else is a regular customer), `delivery`, `city`,
`payment` (`card`, `cod`, `invoice`) and `card`. Unknown fields are ignored.

### Change an order's status

```bash
curl -s -X PATCH localhost:8000/orders/1/status \
  -H 'content-type: application/json' -d '{"status": "paid"}'
```

Allowed transitions: `new -> paid -> shipped -> delivered`, `new -> cancelled`, `paid -> cancelled`
(a paid order that is cancelled publishes a `RefundRequested` event).

### Errors

Every error has the same shape and a stable `code`; clients should branch on the code, not on the message.

```json
{"error": {"code": "invalid_transition", "message": "order 1 cannot go from new to delivered"}}
```

| HTTP | Codes |
|---|---|
| `422` | `no_items`, `bad_email`, `bad_qty`, `bad_delivery`, `unsupported_payment`, `card_required`, `cod_limit`, `invoice_b2b_only`, `validation_error` (malformed JSON shape, with `details`) |
| `402` | `payment_failed` (the provider declined the card) |
| `502` | `payment_unavailable` (the provider is down or answered with garbage) |
| `404` | `order_not_found` |
| `409` | `invalid_transition` |

## Business rules

Prices are applied in this order, and every step rounds to a whole kopiyk (half up):

1. subtotal of all lines;
2. promo code;
3. customer discount;
4. shipping, calculated on the total after steps 2 and 3.

| Promo code | Effect |
|---|---|
| `SALE10` | 10% off the subtotal |
| `MINUS50` | 50 UAH off if the subtotal is above 500 (exactly 500 does not qualify) |
| `FREESHIP` | free shipping |
| `BUY3` | with 3 or more units, the cheapest unit is free |

| Customer | Effect |
|---|---|
| `vip` | 5% off after the promo |

| Delivery | Cost |
|---|---|
| `nova` | 70, free if the total is above 1000 |
| `ukr` | 45 |
| `courier` | 120 in Kyiv, 170 elsewhere |
| `pickup` | free |

| Payment | Rule |
|---|---|
| `card` | charged immediately, the order is created as `paid` |
| `cod` | refused above 5000 (total with shipping), created as `new` |
| `invoice` | business customers (`user_type = b2b`) only, created as `new` |

Order confirmation emails use the `vip_order` template for VIP customers and `order` for the rest.
Orders above 10000 are also announced in Slack. A failing notification never fails the checkout.

## Development

```bash
make check       # everything CI runs
make format      # ruff fix + format
make test        # pytest only
```

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, `mypy --strict`,
`lint-imports` and `pytest` on Python 3.12 and 3.13.

Rules for contributing, including how to add a promo code, a delivery method or a payment method,
are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

### Tests

| Suite | Location | What it proves |
|---|---|---|
| Characterization | `tests/characterization` | The same table of 60 cases gives the same results on the legacy function and on the new service; 2 more pin intentional differences. |
| Domain | `tests/unit/domain` | `Money` arithmetic and rounding, the `Order` state machine, every pricing rule, boundary values. |
| Application | `tests/unit/application` | Use cases against hand-written fakes: rejections have no side effects, events, failure isolation. |
| Infrastructure | `tests/unit/infrastructure` | Adapters over `httpx.MockTransport`: declines vs outages, timeouts, templates, thresholds. |
| API | `tests/integration` | End-to-end through FastAPI with the real composition root and a fake HTTP transport. |

## How behaviour is preserved

`tests/characterization` is a golden-master suite. One table of cases (`cases.py`) is replayed against
two implementations through a common interface:

- `legacy.checkout.checkout`, with `requests` intercepted by `responses`, state reset between tests and a
  temporary working directory;
- the new `CheckoutService`, wired by the real composition root, with `httpx` replaced by an in-memory
  transport.

For each case the suite compares what an outside observer can see: the result, the stored order's total
and status, and **every outbound HTTP call** (payment, email, Slack) with its payload. The cases cover
each promo code, VIP and regular customers, all delivery methods including courier outside Kyiv, all
payment methods, every error branch and the boundary values 500, 1000, 5000 and 10000 on both sides.

Where the new code intentionally differs from the legacy one, the case lives in a separate table
(`DIVERGENCES`) that states both expectations. Defects of the legacy function are additionally pinned in
`test_legacy_behaviour.py`, so that the fixes are visible as explicit, reviewable changes.
The history reflects the order of work: tests, then refactoring, then fixes, then new features.

## Proving the design is open for extension

After the refactoring, two features were added in a single commit (`feat: add the BUY3 promo code and
the pickup delivery method`):

| File | Change |
|---|---|
| `src/shop/domain/pricing/cheapest_free.py` | **new**: the `CheapestUnitFree` promotion |
| `src/shop/domain/pricing/registry.py` | 3 lines: one import and two registry entries |
| `tests/...` | new tests only |

No existing strategy, `PricingCalculator`, `CheckoutService` or API code was touched. Pickup needed no new
class at all: it is the existing `FlatRate` with a zero price.

## Project layout

```
src/shop/
  domain/            pure business logic, no framework imports
    money.py         Money value object and the rounding rule
    order.py         Order aggregate and status state machine
    cart.py          Cart and OrderLine
    events.py        OrderPlaced, RefundRequested
    errors.py        DomainError hierarchy with stable codes
    pricing/         promotions, customer discounts, shipping, calculator, registries
  application/       use cases and ports
    checkout.py      CheckoutService
    orders.py        OrderService
    ports.py         PaymentGateway, OrderRepository, Notifier, Clock
    payment_methods.py, event_bus.py, handlers.py
  infrastructure/    adapters: HTTP payment gateway, notifiers, in-memory repository, clock
  api/               FastAPI app, schemas, error handlers
  composition.py     the composition root
  main.py            application factory for uvicorn
legacy/checkout.py   the original function, untouched
tests/
docs/CODE_REVIEW.md  review of the legacy code
ARCHITECTURE.md      layers, patterns, decisions, fixed and kept defects
```

## Optional tasks

| Task | Status |
|---|---|
| D. Architecture checks in CI (`import-linter` + GitHub Actions) | Done |
| G. `/arch-review` command for Claude Code (`.claude/commands/`) | Done |
| A. PostgreSQL repository | Not done |
| B. Transactional outbox with retries | Not done |
| C. Circuit breaker for the payment adapter | Not done |
| E. Mutation testing | Not done |
| F. Structured logs with correlation ids | Not done |

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md): layers, patterns and the problem each solves, where patterns
  were deliberately not used, defects fixed and kept, known limitations.
- [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md): the review of the legacy code that drove the work.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): architecture rules and workflow.
- [`CLAUDE.md`](CLAUDE.md): the rules AI-assisted work follows here.
- [`AI_LOG.md`](AI_LOG.md): how AI was used, where it went wrong, what was rejected.
