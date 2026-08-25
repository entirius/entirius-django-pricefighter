# Decision Engine — read path, side-effect-free

**Contract**: `decision_view_service.build_decision_rows(skus=None, *, sort="-gap_baseline",
offset=0, limit=None) -> (list[DecisionRow], total)`. `skus=None` defaults to
`market_service.get_candidate_skus()` — only skus with >=1 non-stale `kind=monitoring`
observation (no competitor signal = nothing to rank against; the full catalog is reachable by
passing `skus` explicitly). Enumerates every `market_service.get_markets()` result (distinct
pricemanager `(channel, country, currency)` triples that actually have a `CurrentPrice` row),
bulk-fetches every input in `engine_inputs.build_engine_inputs()` (constant query count
regardless of sku count — verified by `test_decision_view_integration.py`), runs each
`(sku, market)` pair through `quote_engine.compute_decision()` (pure function, zero ORM,
zero Django imports — every fetch happens in `engine_inputs`), then sorts/paginates **in
RAM**. Adding a new sortable field is a `decision_view_service._sort_value()` allowlist
entry, never a DB migration.

**Pipeline** (`quote_engine.compute_decision`):
1. Flag every observation for this market: silently drop sources scoped to a *different*
   non-null country (they belong to another market's row, never shown here); then flag
   `stale` (older than `PRICEFIGHTER_STALENESS_DAYS`) / `untrusted` (`Source.is_trusted`) /
   `currency_mismatch` (`value["currency"] != market.currency` — **zero currency
   conversions**, ever) / `oos` (`value["stock"] == 0`; a missing `stock` key counts as
   valid — we don't guess). The full flagged list always ships in the row (panel grays out
   filtered entries); only `valid` ones feed the estimator.
2. Zero valid observations -> **NO_COMP**: `CurrentPrice.source == "pricefighter"` and a
   baseline exists -> `revert_baseline` (T = baseline, unclamped — see the apply-time clamp
   note below); `pricefighter` source but no baseline -> `hold` reason `no_baseline`; any
   other source -> `hold` reason = the dominant flag among the (filtered-out) observations,
   or `no_competitor` if there were none at all.
3. `R` = `estimate_reference_price()` — `PRICEFIGHTER_REF_ESTIMATOR` (`min` default /
   `second_best`, falls back to the single value when only one observation exists /
   `median`, lower-middle on an even count — deterministic, never invents a price nobody
   observed).
4. No `PurchaseCost` -> no `baseline` -> `no_recommendation` reason `no_cost` (R and the
   observation list still populate the row; only the recommendation is withheld).
5. `gap = R - baseline` (anchor is baseline, not current price — stable, doesn't drift with
   our own price moves; `gap_current` ships too, informational only).
6. No `QuoteConfig` row for `(market.currency, R)` -> `hold` reason `no_quote_config` (T = P,
   not a 500).
7. `raw_side` from `gap` vs the matched row's `band_up`/`band_dn` (RAISE / COMPETE / HOLD —
   in-band).
8. `price_war=True` on the resolved rule and `raw_side == COMPETE` -> `hold_at_floor`,
   T = floor (no floor -> `hold` reason `price_war_no_floor`) — takes priority over the
   strategy permission step below; this is the only regime-style override in v1 (no auto
   war-detection, an operator sets the flag).
9. Strategy permission (see above) narrows `raw_side` to `side`.
10. `side in (COMPETE, RAISE)` -> `T = R - undercut` (COMPETE) / `R - headroom` (RAISE) ->
    round (`none`/`.99`/`.95`/`int`) -> clamp to floor (`clamped_floor` flag) -> clamp to
    `max_step` from current price (`clamped_step` flag) -> quantize to cents.

**Invariant**: `revert_baseline`'s target is the baseline **as-is, not floor-clamped** — the
floor gate in step 10 only runs for COMPETE/RAISE. If baseline sits below MAP, the clamp
happens for real at apply time (pricemanager's guard), not at render time — see
`test_apply_service.py::test_revert_below_map_is_clamped_at_write_time`.

**N+1 note**: `atlas.observation_service.get_observations_bulk()` only
`select_related("source")`, not `source__country` — `engine_inputs._observation_inputs_by_sku`
resolves every distinct `source.country_id` via one extra bulk `Country` query instead of
touching `.country.iso2` per observation.

---
