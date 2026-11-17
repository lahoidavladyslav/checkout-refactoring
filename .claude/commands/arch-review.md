---
description: Review the current diff against the architecture rules in CLAUDE.md and ARCHITECTURE.md
argument-hint: "[base ref, default: HEAD]"
allowed-tools: Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(uv run lint-imports:*), Bash(uv run mypy:*), Bash(uv run ruff:*), Read, Grep, Glob
---

Review the changes between `$ARGUMENTS` (default `HEAD`) and the working tree against the rules in
`CLAUDE.md` and `ARCHITECTURE.md`. Read both first.

1. Run `git diff $ARGUMENTS --stat` and `git diff $ARGUMENTS`. Read every changed file in full when
   the diff alone is not enough to judge it.
2. Run `uv run lint-imports`, `uv run mypy` and `uv run ruff check .` and report anything they flag.
3. Check each rule below on the changed code and report a violation with `file:line`:
   - Layering: does anything in `shop/domain` or `shop/application` import an outer layer or a
     framework? Does anything outside `shop/composition.py` construct an adapter?
   - Money: `float`, `round()` or `Decimal` arithmetic on amounts outside `Money`?
   - Order status assigned directly instead of through `pay/ship/deliver/cancel`?
   - Global or module-level mutable state, `print`, `datetime.now` outside the clock adapter?
   - Card data or email in a log line, an event, an order or an exception message?
   - A new promo code, delivery or payment method that edits `PricingCalculator`, `CheckoutService` or an
     existing strategy instead of adding a class and a registry entry?
   - A new abstraction or pattern without a paragraph in `ARCHITECTURE.md`; a DI container, single-method
     abstract base class, Builder, Specification, `Result` type or message broker?
   - A changed expectation in `tests/characterization` that is not in a `fix:` or `feat:` commit, or a
     test edited so that new code passes without a stated reason? Any edit under `legacy/`?
   - `# type: ignore` without a reason; a missing test for new behaviour.
4. Report findings ordered by severity, each with the rule it breaks and a concrete fix.
   If nothing is wrong, say so and list what was checked. Do not modify any file.
