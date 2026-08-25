# Gotchas

- `ProductRepresentation` follows the **matrix** idiom (channel-scoped, unique
  `Lower(sku)+channel`, synced) — the pricemanager PR idiom (lazy auto-create with a
  mandatory TaxClass on first touch) is a different pattern from a different module; do not
  copy it here.
- The PIM signal tor is gated by `PimSettings.pricefighter_signals_enabled`, default
  **False** — a deployment must enable it explicitly, or rely entirely on the daily
  cron full-sync (04:30 UTC) for freshness.
- `sync_pair`/`full_sync` resolve the PIM channel via `product.shop.idx` — in PIM's own
  code the FK is still named `shop` (historical), not `channel`.
- `full_sync()`'s stale-detection excludes on **exact-case** `sku__in=seen_skus`, matching
  the case PIM returned — do not lowercase one side and not the other, or every product
  looks "gone" and gets deactivated.
- `QuoteConfig.clean()` and `PricingRule.clean()` are **not** called by `ModelAdmin` by
  default — both admin classes override `save_model` to call `full_clean()`. Bulk paths
  (`loaddata`, `bulk_create`) bypass `clean()` entirely; `PricingRule`'s exactly-one-scope
  invariant is also enforced by a DB `CheckConstraint` as a second line of defense.
- `PricingRule.sku` / `category_idx` are `null=True` (not just `blank=True`/`""`) on
  purpose — the CheckConstraint needs a real NULL to distinguish "unset" from "set to empty
  string" for the exactly-one-scope check.
- `QuoteConfig` range contiguity (`_validate_range_contiguity`) requires **exact** touching
  boundaries per currency (`next.range_from == prev.range_to`) — a gap or overlap raises
  `ValidationError`; at most one row per currency may have `range_to=None` (open-ended top).
- `mode=authoritative` on `PricingRule` only bites in batch-run/autopilot contexts — a
  manual operator apply always writes regardless of `mode`.
- **Two distinct `Channel`/`ProductRepresentation` pairs exist** — this module's own (used by
  `PricingRule`/`QuoteConfig` scope and the decision view row identity) and pricemanager's
  (used by every bulk pricing service and `edit_price`). `engine_inputs`/`apply_service`
  import both under aliases (`PmChannel`/`PfChannel`) — never mix them up; passing this
  module's `Channel` into a pricemanager bulk function is a silent type error at the ORM
  boundary (wrong table), not a clean exception.
- `quote_engine.py` has **zero Django/ORM imports on purpose** (dataclasses + `Decimal` only)
  — `now` is always an explicit parameter, never `timezone.now()` internally, so its unit
  tests stay deterministic without freezegun. Don't be tempted to import `django.utils.timezone`
  in there for "convenience".
- `edit_price()`'s `_AUTOMATED_SOURCES` check (pricemanager) means an apply on a sku with no
  `ProductRepresentation` in pricemanager raises `ValueError` instead of auto-creating one —
  `apply_service` catches this and reports `failed`, it never lets the exception propagate.
- The decision view's `margin` field is `(CurrentPrice.net_value - PurchaseCost.net_cost) /
  CurrentPrice.net_value * 100`, **not** `(gross - cost) / gross` — matches pricemanager's own
  margin definition (its AGENTS.md).

---
