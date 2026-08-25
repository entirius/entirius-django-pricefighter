# Strategy Resolution

`rule_resolver.resolve(sku, category_idx, channel) -> ResolvedRule` — most-specific-wins:
**sku > category > channel**. Within a level, ties break deterministically by `pk`
(`order_by("pk").first()`). No matching rule at any level -> `DEFAULT_RESOLVED_RULE`
(`hold` + `suggestion` + `price_war=False`). Lives in `services/`, not a model method —
`PricingRule` itself carries no resolution logic. `resolve_bulk(items)` is the batch twin
(one query for every `PricingRule` row, resolved in RAM per item) — `engine_inputs` uses this,
never the per-item `resolve()` in a loop.

**`PricingRule.strategy` is a directional permission, not an engine on/off switch.** The
gap+band math (below) always computes a `raw_side` from the numbers alone; `strategy` then
filters which side is allowed to fire: `hold` -> always HOLD; `compete` -> COMPETE or HOLD
(RAISE is suppressed back to HOLD); `raise` -> RAISE or HOLD (COMPETE suppressed). This is why
the *default* (`DEFAULT_RESOLVED_RULE.strategy = hold`) is safe — an unmatched sku never
moves — and why a sku with `strategy=raise` will never chase a competitor downward even if the
gap says it should.

---
