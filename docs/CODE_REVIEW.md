# Code review: `legacy/checkout.py`

A review of the legacy checkout module, written before any refactoring started.
Every finding has an ID so that tests, commits and `ARCHITECTURE.md` can refer to it.

Severity: **High** (money, security or data loss), **Medium** (wrong or surprising
behaviour, reliability), **Low** (maintainability).

The "Resolution" column is filled in as the refactoring progresses; see
[`ARCHITECTURE.md`](../ARCHITECTURE.md#legacy-defects-fixed-and-kept) for the full rationale.

## 1. Correctness and money

| ID | Sev. | Finding | Resolution |
|----|------|---------|------------|
| C1 | High | **Floats are used for money.** `SALE10` on `99.99` yields `89.991`, VIP `* 0.95` adds more fractional kopiyky. The unrounded value is sent to the payment provider and stored in the order. | Fixed: `Money` stores integer kopiyky, one explicit rounding rule (`ROUND_HALF_UP`). |
| C2 | High | **Charge happens before the order is persisted.** If anything after the charge fails (file write, memory), the customer has paid and there is no order. | Kept, documented as a residual risk. Needs idempotency keys / outbox, out of scope for the in-memory repository. |
| C3 | High | **Notification failures break a finished checkout.** `requests.post` to the mail or Slack hook raises; the caller sees a 500 although the order exists and is paid. A client retry then charges the card twice. | Fixed: notifications are event subscribers whose failures are logged and swallowed. |
| C4 | Medium | **Unknown payment method silently succeeds** (`"crypto"`, `None`, a typo): the order is created as `new` without any payment step. | Fixed: unsupported methods are rejected. |
| C5 | Medium | **Input is not validated.** `price` is never checked (a negative price lowers the total), `qty` may be `1.5`, a missing `qty` or `price` raises `KeyError`, `items` may contain anything. | Fixed: shape is validated at the HTTP boundary, business rules in the domain. |
| C6 | Medium | **`change_status` accepts any value.** `delivered -> new`, `"banana"`, and so on. | Fixed: `Order` is a state machine, transitions are explicit. |
| C7 | Medium | **Unknown promo code or customer type is ignored silently.** The customer gets no feedback that a code was not applied. | Kept, documented: ignoring is a legitimate product decision, but it is now explicit and tested. |
| C8 | Medium | **The free-shipping threshold is evaluated on the discounted total** (after promo and VIP discount). It is a business ambiguity, not necessarily a bug. | Kept as is, documented. Changing it is a product decision. |
| C9 | Medium | **`FREESHIP` and the injected `free_ship` flag skip delivery validation.** With free shipping an unknown `delivery` value is accepted. | Kept for `FREESHIP`, documented. |
| C10 | Low | **`datetime.now()` is naive.** The timestamp depends on the server timezone and cannot be compared across hosts. | Fixed: timezone-aware UTC, produced by an injectable `Clock`. |

## 2. Security

| ID | Sev. | Finding | Resolution |
|----|------|---------|------------|
| S1 | High | **Free shipping can be claimed by the client.** `data["free_ship"]` is read from the same dictionary the caller controls, so `{"free_ship": true}` waives shipping without any promo code. | Fixed by construction: the flag does not exist in the input schema, only a promotion can grant free shipping. |
| S2 | High | **Input mutation.** `data["free_ship"] = True` modifies the caller's dictionary, a side effect on shared state and the mechanism behind S1. | Fixed: the input is immutable, pricing returns a new value. |
| S3 | Medium | **PII in a plain-text log.** `orders.log` stores the customer's email and the full item list, unrotated, in the working directory. | Fixed: no file log; structured application logging contains the order id only. |
| S4 | Medium | **Card data is forwarded verbatim** from an untyped field and is one `print(data)` away from a log. | Fixed: the card is a `SecretStr` at the boundary, is never part of the order and never logged. |
| S5 | Low | **Outbound requests have no `timeout`.** A hung provider blocks the worker forever (and the request-handling thread with it). | Fixed: all HTTP clients have explicit timeouts. |

## 3. Reliability and operations

| ID | Sev. | Finding | Resolution |
|----|------|---------|------------|
| R1 | High | **The payment response is not validated.** `r.json()["status"]` raises on an HTML 502 page, on a non-JSON body and on a missing key. | Fixed: `raise_for_status`, defensive parsing, a dedicated "gateway unavailable" error. |
| R2 | Medium | **Process-local global state.** `orders` and `last_id` are module globals: lost on restart, separate per uvicorn worker (ids collide, `change_status` finds nothing), not thread-safe (`last_id += 1`). | Fixed: repository port with an explicit adapter, id allocation under a lock. |
| R3 | Low | **`print` instead of logging.** | Fixed: `logging`. |
| R4 | Low | **Blocking file I/O with no `flush` / error handling** on the request path. | Fixed: removed together with S3. |

## 4. Design (SOLID and smells)

| ID | Principle | Finding |
|----|-----------|---------|
| D1 | SRP | `checkout()` validates, prices, applies discounts, calculates shipping, charges, persists, logs, sends email and posts to Slack. Seven reasons to change in one function. |
| D2 | OCP | Every new promo code, delivery method or payment method means editing the same `if/elif` chains. Adding `BUY3` requires touching the pricing block and risks the others. |
| D3 | DIP | Business logic calls `requests.post` and `open()` directly. It cannot be tested without monkeypatching the world. |
| D4 | Smell | Primitive obsession: money is `float`, statuses and customer types are free strings, items and the result are `dict`. |
| D5 | Smell | Error handling by magic strings (`{"ok": False, "msg": "bad qty"}`). The caller cannot distinguish a validation error from a payment decline except by string comparison. |
| D6 | Smell | The same notification block is duplicated for VIP and regular customers; only the template name differs. The `10000` Slack threshold and the template names are hard-coded. |
| D7 | Smell | Temporal coupling: the order of the discount, shipping and payment blocks is semantically significant but implicit. |
| D8 | LSP/ISP | Not applicable: there are no abstractions to violate. That is itself the problem. |

## 5. Observations that shaped the refactoring

1. **Pricing order is the contract:** `subtotal -> promo -> VIP -> shipping`. The free-shipping
   threshold (C8) and the `MINUS50` threshold (`> 500`, strict) depend on it.
2. **Boundaries are strict:** `MINUS50` applies above `500` (not at exactly `500`), Nova Poshta
   shipping is free above `1000`, cash on delivery is refused above `5000`, the Slack alert fires
   above `10000`. All four are covered by boundary tests.
3. **Courier outside Kyiv** costs `170` (`120 + 50`); a missing city counts as "not Kyiv".
4. **The legacy module has to remain the oracle.** The characterization suite runs the same cases
   against the legacy function and against the new service and compares the observable effects
   (result, and every outbound HTTP call), not internal structure.
