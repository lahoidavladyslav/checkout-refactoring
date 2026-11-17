# AI log

How Claude Code was used on this project, written from the session itself. All production code, tests and
documentation in this repository were produced by Claude Code (Sonnet 5.5) in one working session; the author
set the requirements and rules, reviewed the output and made the decisions listed below.

## Key prompts

| # | Prompt (translated from Ukrainian) | Effect |
|---|---|---|
| 1 | "Write a CLAUDE.md with rules: do not add yourself to the repository history or to git at all; create a public repo under my name; split commits sensibly; code without traces of AI." | Created the first `CLAUDE.md` (git and style rules). Set the commit discipline and the author identity for the whole history. |
| 2 | "Handle the project professionally, detailed and well written, as if a senior wrote it for a serious project, not just an assignment." | Raised the bar: layered architecture, import contracts, CI, golden-master suite, full documentation, explicit rationale for rejected patterns. |
| 3 | "Where the task needs AI, use AI." | Lifted the "no traces" rule for the artefacts the task requires: `CLAUDE.md` with architecture rules, `AI_LOG.md`, the AI section of `CODE_REVIEW.md` and the `/arch-review` command. Commit trailers and code comments stay free of attribution. |

The task statement itself (`test-task-2-checkout-refactoring`) was the working specification and was read in
full before any code was written.

## Where Claude went wrong, and what happened

1. **Test expectations computed by hand were wrong three times.** The Slack boundary cases used cash on
   delivery, which the legacy code refuses above 5000, so the "expected success" was a failure; a VIP
   notification test expected `235.00` instead of `140.00`; the `BUY3` table expected `140` for a cart that
   costs `120`. Each was found by running the suite against the real code and the expectation was corrected
   after re-deriving it from the legacy source, not by bending the implementation. This is also why the
   characterization table is run against the legacy function first: it is the check on the checker.
2. **A test claimed more than it proved.** `test_scale_rounds_once_not_per_step` asserted two equal values
   under a name that implied a difference. It was replaced by `test_chained_scaling_rounds_after_every_step`,
   with an input (`0.55` with 0.9 then 0.95) where the stepwise and single-step results actually differ.
3. **A speculative error class.** `InvalidPriceError` was added to the error hierarchy and then removed
   once it was clear that `Money` already rejects negatives and the HTTP schema rejects them at the boundary.
   An error type nothing raises is noise.
4. **Hacks in tests.** A `command()` helper with `# type: ignore` and a `_raise_for` trick to reach a private
   method were rewritten with `dataclasses.replace` and a plain `order.ship()` assertion.
5. **A wrong number in a commit message** ("70 cases"; the table had 62). Noticed on review, corrected by
   rewriting the local history before anything was pushed.
6. **Tooling friction.** `# noqa` directives were added for rules that were not enabled and had to be
   removed; the `float` JSON amount in the payment adapter initially lacked a comment explaining why a
   `float` is acceptable at that one edge.

## The optional tasks (A, B, C, E, F)

A second round of work added the circuit breaker, JSON logging, the PostgreSQL repository, the outbox and
mutation testing. Mistakes made and caught on the way:

1. **A silent no-op edit.** A scripted string replacement meant to wire the breaker settings into
   `Settings.from_env` did not match (the formatter had reflowed the line) and failed silently, so the
   environment variables were not wired. Found while rewriting `composition.py` for the outbox, not by a test.
   The class of problem is "a patch script that does not check it applied"; later edits assert on the result.
2. **The same hand-calculation error as before.** New end-to-end tests placed 10000+ UAH orders with cash on
   delivery, which the 5000 limit refuses. Fixed by using card payment; the lesson in item 1 of the first list
   was not applied until the tests failed.
3. **Backoff overflow.** `RetryPolicy.delay_after` raised `OverflowError` for large attempt numbers
   (`2.0 ** 5000`). A parametrised test with extreme inputs found it; the fix caps before converting.
4. **Time zone leak.** The repository returned `timestamptz` values in the database session's zone
   (`Europe/Kiev`), found by a round-trip test against a real PostgreSQL. Normalised to UTC on read.
5. **Test fixture bug.** The log-capturing fixture filled its result list in the teardown, after the test had
   already read it; two tests failed for that reason, not because of the code.
6. **Tooling.** `ruff` was pointed at the generated `mutants/` directory and linted generated code; `mutmut`
   needed three configuration attempts (missing `legacy/`, missing sibling packages, then Postgres tests
   collected in the stats run). The first mutation run was therefore on a narrower test selection than the
   last, which changed which mutants survived; the README reports both runs.

What mutation testing added that the author's own test design had not: it found that nothing verified the
masking of `CardToken`, the single most security-relevant `__repr__` in the project, and that the placed
`Order`'s fields were never asserted in the domain tests.

Decisions kept from over-engineering here: no `UnitOfWork` class (the transaction is inside the adapter), no
message broker, no circuit-breaker library, a lease-based claim instead of long transactions that hold locks
across network calls, and an ordinary `logging.Formatter` instead of a structured-logging dependency.

## Where Claude over-engineered, or was kept from it

The design work deliberately declined the patterns a model reaches for by default. Each is recorded with
its reason in `ARCHITECTURE.md`:

- a DI container (`dependency-injector`, `punq`): the wiring is about forty lines in one file;
- a `Result` type instead of exceptions;
- abstract base classes for every port and strategy: `Protocol` was used instead;
- Builder for `Order`, Specification pattern for validation, Chain of Responsibility for the pricing steps;
- Unit of Work and Repository machinery over an in-memory store;
- pydantic models as domain entities.

Two places where the simple option won: pickup delivery is the existing `FlatRate` with a zero price, with no
new class; and `OrderService.change_status` keeps a `match` over a closed `Enum` instead of a Strategy.

## Deliberate staging that looks like a mistake

The first refactoring commit kept the legacy "unknown payment method creates an unpaid order" behaviour with
a `Deferred` fallback, so that the golden master stayed green. A separate `fix:` commit then removed it and
moved the two cases into the table of intentional divergences. Fixing it inside the refactoring commit would
have changed behaviour silently.

## Decisions that were the author's, not the model's

- Publishing under the author's GitHub account and the commit identity.
- Excluding AI attribution from git (trailers, messages) while documenting AI use in the dedicated files.
- Accepting the loosely-validated legacy rules that are business decisions (ignored unknown promo codes, the
  free-shipping threshold evaluated after discounts) as "keep and document" rather than "fix".
- Honest scope: optional tasks A, B, C, E and F were not done and are listed as such in the README.

## The architecture-review command

`/arch-review` (`.claude/commands/arch-review.md`) checks a diff against `CLAUDE.md` and
`ARCHITECTURE.md`: layering, money handling, state changes, globals, secrets in logs, edits to existing
strategies, undocumented patterns, rewritten test expectations and edits under `legacy/`. It runs the
mechanical tools first (`lint-imports`, `mypy`, `ruff`) and then applies the checks the tools cannot.

Example, reproduced by hand with the command's own steps on a deliberately bad change: a `float`-returning
helper using `round(total * 0.9, 2)` and `import httpx` appended to `shop/application/checkout.py`.

- `uv run lint-imports` reported the contract "Application does not depend on infrastructure or HTTP layer"
  as **BROKEN**, naming `shop.application.checkout -> httpx (l.88)`.
- The money check (`git grep` for `float` and `round(`) found the `round(...)` call at line 92, which no tool in
  CI flags: the import contract covers imports, not arithmetic on amounts. That gap is what the command's
  checklist, not the linter, is for.

The change was reverted; it was a demonstration, not a defect that reached the repository. A run of the same
checklist over the final code found no violations; the only `datetime.now` is in the clock adapter.
