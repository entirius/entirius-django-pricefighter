# entirius-django-pricefighter

Competitive pricing engine for Volkanos. Mirrors PIM products per channel, resolves a
pricing strategy per SKU/market, computes a decision view (gap vs. competitor
observations, recommendation, suggested price), and applies approved decisions through
pricemanager's price-edit path with a full audit snapshot.

## Features

- Channel registry (Pattern 2 scoping channel), synced from PIM
- `ProductRepresentation` per-channel mirror (sku/name/category), synced from PIM
- `PricingRule` — strategy resolution (hold/compete/raise), most-specific-wins scoping
- `QuoteConfig` — quoting parameters per currency × price range
- Decision engine — pure quote pipeline joining prices, costs, bounds, and atlas
  competitor observations into gap + recommendation + suggested price
- Apply flow — writes through pricemanager's `edit_price()`, logs a `PriceDecision`
  audit snapshot per applied decision
- Admin API (v2, JWT protected) — channels, decision view, bounds, history, apply,
  pricing-rule CRUD

## License

MPL-2.0 — see `LICENSE`.
