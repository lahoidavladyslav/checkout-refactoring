# CLAUDE.md

Rules for AI-assisted work in this repository. Human contributors follow the same rules, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Project

Refactoring of a legacy checkout function (`legacy/checkout.py`) into a layered FastAPI service.
Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `import-linter`. Run `make check` before every commit.

## Architecture rules

1. `shop.domain` imports the standard library only: no `application`, `infrastructure`, `api`,
   `fastapi`, `pydantic`, `httpx` or `requests`. `shop.application` imports only `shop.domain`.
   `import-linter` enforces this; do not weaken the contracts to make a change pass.
2. Money is the `Money` value object (integer kopiyky). No `float` for amounts, no `round()` for money.
   Rates go through `Money.scale`, the only place that rounds (`ROUND_HALF_UP`).
3. `Order.status` changes only through `pay`, `ship`, `deliver`, `cancel`.
4. No global state, no `global`, no `print` (use `logging`).
5. Side effects go through ports (`PaymentGateway`, `OrderRepository`, `Notifier`, `Clock`). Adapters are
   created only in `shop/composition.py`. Tests use fakes, not `mock.patch` of `requests` or `httpx`.
6. Errors are `DomainError` subclasses with a stable `code`; the HTTP status is mapped in `shop/api/errors.py`.
7. Card tokens exist only as `CardToken` and are never logged or stored. Do not log emails.
8. New promo codes, delivery methods and payment methods are new classes plus a registry entry. Do not edit
   existing strategies, `PricingCalculator` or `CheckoutService` to add one.
9. A new pattern needs a paragraph in `ARCHITECTURE.md`: the problem it solves and what was rejected.
   Do not add DI containers, abstract base classes with a single method, Builders, Specifications,
   a `Result` type, CQRS or message brokers: they were considered and rejected, see `ARCHITECTURE.md`.
10. `legacy/` is read-only. It is the oracle for `tests/characterization`.
11. `# type: ignore` only with a comment that says why.

## Refactoring discipline

- Tests first: pin behaviour with characterization tests before changing code.
- Behaviour does not change silently. A deliberate change is its own `fix:` or `feat:` commit, and the
  expected values in tests change in that commit, never inside a refactoring commit.
- Never edit a test's expectation to make new code pass without a documented reason.
- Small steps; every commit passes `make check`.

## Git

- Author and committer is the repository owner. Local config only:
  `git config user.email "lahoidav@gmail.com"` and `git config user.name "lahoidavladyslav"`.
- Do not add AI attribution to git: no `Co-Authored-By` trailers, no "Generated with" lines in commit
  messages, pull requests, issues, tags or code comments.
- Conventional Commits in English, imperative mood, subject up to 72 characters. One logical change per commit.
- Do not force-push or rewrite published history.

## Code style

- Code and comments read like ordinary hand-written code: comments explain a non-obvious "why", never the
  obvious "what". No emoji, no decorative separators, no AI markers in code.
- Follow the existing style and naming. Do not introduce abstractions without a present need.

## Where AI use is documented

AI collaboration is described openly, and only, in `AI_LOG.md` and in the second section of
`docs/CODE_REVIEW.md`. The `/arch-review` command in `.claude/commands/` checks a diff against the rules above.
