# Contributing

## Architecture rules

These are enforced by `import-linter` in CI where a tool can enforce them, and by review otherwise.

1. **Dependencies point inwards.** `shop.domain` imports only the standard library. `shop.application`
   imports `shop.domain`. Adapters live in `shop.infrastructure`. Nothing outside `shop.composition`
   and `shop.main` constructs adapters.
2. **No frameworks in the domain.** No `fastapi`, `pydantic`, `httpx` or `requests` below
   `shop.api` and `shop.infrastructure`. Domain objects are frozen dataclasses or plain classes.
3. **Money is `Money`.** Never `float` for an amount, never `round()` for money. Rates go through
   `Money.scale`, which is the only place that rounds.
4. **State changes through behaviour.** `Order.status` is changed by `pay`, `ship`, `deliver` and
   `cancel`, never assigned.
5. **No global state.** No module-level mutable state, no `global`.
6. **External effects go through ports.** The application layer never calls HTTP, the filesystem or
   the clock directly. Tests use fakes of the ports, not `mock.patch` of libraries.
7. **Errors are `DomainError` subclasses with a stable `code`.** Callers never match on messages.
   Add the HTTP status in `shop/api/errors.py`.
8. **Secrets and personal data stay out of logs.** Card tokens only travel inside `CardToken`; log order
   ids, not emails.
9. **No `# type: ignore` without a comment saying why.** `mypy --strict` is the baseline.
10. **`legacy/` is read-only.** It is the oracle for the characterization tests.
11. **A new pattern needs a paragraph in `ARCHITECTURE.md`**: the problem it solves, and what was
    considered instead.

## Adding a rule

The design is meant to make these additions small.

**A promo code.** Create a class with `evaluate(self, cart: Cart) -> PromoEffect` (see
`pricing/promotions.py` and `pricing/cheapest_free.py`), then register it in `PROMOTIONS` in
`pricing/registry.py`.

**A delivery method.** Implement `cost(self, order_total, city) -> Money` or reuse `FlatRate`,
`FreeAboveThreshold` or `LocalOrRemoteRate`, then add it to `SHIPPING_METHODS`.

**A customer discount.** Implement `apply(self, total) -> Money` and add it to `CUSTOMER_DISCOUNTS`.

**A payment method.** Implement `settle(self, context) -> bool` in `application/payment_methods.py`
(return `True` when money was collected, `False` when payment is deferred, raise a `CheckoutError`
to refuse) and register it in `build_container`.

**A notification.** Write a class with `notify(self, event: OrderPlaced) -> None` and subscribe it
in `build_container`.

In every case: add tests next to the rule, and do not edit the existing strategies, `PricingCalculator`
or `CheckoutService`. If you find you must, the design needs discussing first.

## Workflow

```bash
make check    # must pass before every commit: ruff, mypy --strict, import-linter, pytest
```

### Commits

- One logical change per commit, and every commit builds and passes `make check`.
- Conventional Commits, in English, imperative mood: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
  `chore:`, `ci:`. Subject up to 72 characters, no trailing period; the body explains why.
- Tests that pin existing behaviour come before the refactoring that relies on them.
- A change in behaviour is its own `fix:` or `feat:` commit, with the test expectations changed in that
  commit and a note on why they changed. Never adjust an expected value inside a refactoring commit.
- Refactor in small steps; behaviour must not change between steps.
