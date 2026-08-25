# Data Model

All models inherit `django_utils.models.base_model.BaseModel` (`created_at`/`modified_at`).

```
Channel (Pattern 2 — own model, no FK to django_pim)
    idx (unique): matches PIM Channel.idx (shared key)
    name
    default_language (FK -> django_regional.Language)
    languages (M2M -> django_regional.Language)

ProductRepresentation (per-channel mirror, matrix-style — NOT the pricemanager lazy idiom)
    sku, channel (FK -> Channel, CASCADE)
    UniqueConstraint(Lower(sku), channel)
    name (denorm, product.name_lang(channel.default_language))
    category (denorm, idx of the product's first category by position)
    is_active (deleted-in-PIM product -> False, never hard-deleted)

PricingRule (strategy resolution — scope: exactly ONE of sku / category_idx / channel)
    strategy: hold | compete | raise (default hold)
    mode: suggestion | authoritative (default suggestion) — gates only batch-run/autopilot,
        never a manual operator apply (that always writes)
    price_war: bool — True means the engine holds HOLD_AT_FLOOR; no auto-detection, an
        operator declares the war by setting this flag
    sku / category_idx (CharField, nullable) / channel (FK -> Channel, CASCADE, nullable)
    CheckConstraint: exactly one of the three scope fields is non-null

QuoteConfig (quoting parameters — one row per currency x contiguous price range)
    currency (CharField, iso3 — no FK, the engine picks a row by market currency string)
    range_from (Decimal), range_to (Decimal, null = open-ended "N+")
    band_dn, band_up, undercut, headroom, max_step (Decimal)
    rounding: none | .99 | .95 | int

PriceDecision (decision audit log — OWN pricefighter, distinct from pricemanager's PriceHistory)
    representation (FK -> ProductRepresentation, CASCADE), channel (FK -> Channel, CASCADE)
    country (CharField iso2), currency (CharField iso3)
    old_price, new_price (Decimal 10,2)
    strategy: compete | raise | revert_baseline | hold_at_floor (OWN TextChoices — NOT
        PricingRule.Strategy; "hold" is never actionable so it never reaches this log)
    mode (CharField — copied from the resolved PricingRule at apply time)
    applied_by (FK -> AUTH_USER_MODEL, SET_NULL, nullable)
    reason (JSONField — full snapshot: R, B, floor, P, gaps, estimator, observations w/ flags)
    Indexes: (representation), (created_at), (channel, country, currency)
```

---
