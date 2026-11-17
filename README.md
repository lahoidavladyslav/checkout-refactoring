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
| `SHOP_PAYMENT_BREAKER_THRESHOLD` | `5` | Consecutive payment outages that open the circuit breaker |
| `SHOP_PAYMENT_BREAKER_RESET` | `30` | Seconds before an open circuit lets one probe call through |
| `SHOP_DATABASE_URL` | unset | `postgresql+psycopg://user:pass@host/db`. Unset: in-memory storage and in-process notifications |
| `SHOP_OUTBOX_MAX_ATTEMPTS` | `6` | Delivery attempts before an outbox message is marked dead |
| `SHOP_OUTBOX_BASE_DELAY` | `10` | Seconds before the first retry; doubles on every failure, capped at one hour |
| `SHOP_OUTBOX_POLL` | `2` | Seconds the worker sleeps when the outbox is empty |

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

## Running with PostgreSQL

By default orders live in memory. With `SHOP_DATABASE_URL` set, orders are stored in PostgreSQL and
notifications go through a transactional outbox.

```bash
docker compose up -d --wait db          # or: make db-up
export SHOP_DATABASE_URL=postgresql+psycopg://shop:shop@localhost:5432/shop
make migrate                            # alembic upgrade head
make run                                # the API
make worker                             # the outbox worker, in a second terminal
```

The API writes the order and the events it owes in **one transaction**. The worker reads the outbox and
sends the email and the Slack alert. If the mail service is down the message stays in the outbox and is
retried with exponential backoff (10 s, 20 s, 40 s, ... up to one hour) until it succeeds or the maximum
number of attempts is reached, after which it is marked `dead` and left for an operator.

- Delivery is tracked **per subscriber**: if the email went out and Slack failed, only Slack is retried.
- Several workers can run at once: messages are claimed with `FOR UPDATE SKIP LOCKED` and a lease, and a
  crashed worker's messages become available again when its lease expires.
- Delivery is **at least once**. If a worker dies between sending an email and recording it, the email is
  sent again on the next attempt.

Inspect the queue with SQL: `SELECT id, event_type, status, attempts, next_attempt_at, last_error FROM outbox;`

## Reliability and observability

- **Circuit breaker.** After five consecutive payment-provider outages the circuit opens and card checkouts
  fail immediately with `502 payment_unavailable` instead of waiting for a timeout on every request. After
  30 seconds one probe call decides whether to close it. Declines do not count as failures. It is a
  decorator over the `PaymentGateway` port, per process, with no third-party library.
- **Structured logs.** Every log record is a single JSON line with a `correlation_id`. Each request gets an
  id (an incoming `X-Request-ID` is reused if it is short and made of safe characters, otherwise a new one
  is generated), returned in the `X-Request-ID` response header and attached to every log line the request
  produces, including those from notification handlers. Emails are masked (`b***@example.com`) in
  messages, extra fields and tracebacks, and the access log omits the query string.

```json
{"timestamp": "2026-11-17T09:02:08.752+00:00", "level": "INFO", "logger": "shop.access", "message": "POST /checkout -> 201", "correlation_id": "6f1c0e9a...", "duration_ms": 12.4}
```

## Development

```bash
make check       # everything CI runs
make format      # ruff fix + format
make test        # pytest only (PostgreSQL tests start a throwaway local cluster, or use TEST_DATABASE_URL, or are skipped)
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
| PostgreSQL | `tests/postgres` | Migrations vs table definitions, repository round trips, atomicity, outbox claiming under concurrency, relay retries end to end, the worker loop. Runs against a real PostgreSQL. |

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
  infrastructure/    adapters: HTTP payment gateway, circuit breaker, notifiers, clock,
                     in-memory repository, sql/ (PostgreSQL repository and outbox store)
  api/               FastAPI app, schemas, error handlers
  composition.py     the composition root
  main.py            application factory for uvicorn
  worker.py          outbox worker (python -m shop.worker)
  observability.py   JSON logging, correlation id, email masking
migrations/          Alembic migrations
legacy/checkout.py   the original function, untouched
tests/
docs/CODE_REVIEW.md  review of the legacy code
ARCHITECTURE.md      layers, patterns, decisions, fixed and kept defects
```

## Optional tasks

| Task | Status | Where |
|---|---|---|
| A. PostgreSQL repository, Alembic, docker compose, atomic writes | Done | `infrastructure/sql/`, `migrations/`, `docker-compose.yml`, `tests/postgres/` |
| B. Transactional outbox with retries and backoff | Done | `application/outbox.py`, `infrastructure/sql/outbox.py`, `worker.py` |
| C. Circuit breaker for the payment adapter | Done | `infrastructure/circuit_breaker.py` |
| D. Architecture checks in CI (`import-linter` + GitHub Actions) | Done | `pyproject.toml`, `.github/workflows/ci.yml` |
| E. Mutation testing (`mutmut`) | Done: 199 of 202 mutants killed | `[tool.mutmut]` in `pyproject.toml`, see below |
| F. Structured logs with correlation ids | Done | `observability.py`, `api/middleware.py` |
| G. `/arch-review` command for Claude Code | Done | `.claude/commands/` |

Adding the PostgreSQL repository changed no service and no strategy; the only edit outside the new adapter
and the composition root is a read-only `Order.pending_events` property that lets an adapter persist events
without consuming them.

## Mutation testing

`mutmut` mutates the domain layer (`src/shop/domain`, 202 mutants) and runs the unit tests against each
mutant: a mutant that survives is a change to the code that no test notices.

```bash
uv run mutmut run
uv run mutmut results     # survivors
uv run mutmut show <name> # the diff of one mutant
```

| Run | Killed | Survived | No tests | Score |
|---|---|---|---|---|
| First (existing suite) | 184 | 15 | 2 | 91% |
| After the new tests | 199 | 3 | 0 | 98.5% |

What the survivors of the first run were, and what was done:

- **Card token masking** (4 survivors): `CardToken.__repr__` and `__str__` could return any text and every test
  still passed, although masking is the whole point of the class. New `test_payment.py` asserts the exact
  output and that the number survives no formatting.
- **`Money` error messages** (7 survivors) and **the `Order` timestamp message** (1): messages were replaced by
  `None` or garbled without a test noticing. New tests pin the messages that make a rejected amount
  diagnosable.
- **`Money.is_zero`** had no test at all.
- Once the scope was widened to all unit tests, three more gaps appeared: **`Order.place` attributes** (9
  survivors: the placed order's fields were never asserted), **the city reaching the shipping method** (2: the
  calculator tests did not show that `city` is forwarded) and **`DomainError`'s fallback message** (1). New
  tests added for each.

The three remaining survivors are **equivalent mutants**: `if x` became `if x or True` in
`CustomerType.parse` and in the two `.get(...)` guards of `PricingCalculator`. For a falsy `x` the original
and the mutant behave identically (`dict.get(None)` is `None`, and `CustomerType(None)` raises the
`ValueError` that is already caught), so no test can tell them apart.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md): layers, patterns and the problem each solves, where patterns
  were deliberately not used, defects fixed and kept, known limitations.
- [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md): the review of the legacy code that drove the work.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): architecture rules and workflow.
- [`CLAUDE.md`](CLAUDE.md): the rules AI-assisted work follows here.
- [`AI_LOG.md`](AI_LOG.md): how AI was used, where it went wrong, what was rejected.
