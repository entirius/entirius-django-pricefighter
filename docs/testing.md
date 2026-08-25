# Test suite map

| File | Scope |
|------|-------|
| `test_models.py` | Constraints (unique sku+channel, PricingRule exactly-one-scope), `QuoteConfig.clean()` validations, seed-fixture `full_clean()` sanity |
| `test_services.py` | Channel sync (create/update/idempotent/no-pim), representation sync (upsert/idempotent/deactivate-on-delete/denorm/full_sync), rule_resolver (most-specific-wins/default/tie-break) |
| `test_admin_api.py` | Channels list/sync — 401/403/200, idempotent sync |
| `test_quote_engine.py` | Pure pipeline, no DB: estimators, every observation filter, gap+hysteresis, strategy permission, rounding, floor/max_step clamps, NO_COMP branches, price_war |
| `test_decision_view_integration.py` | market_service + engine_inputs + decision_view_service against a real DB: pre-filter, sort, pagination, constant query count across batch sizes, zero writes on render |
| `test_apply_service.py` | Single apply (write + PriceDecision snapshot), country-scoped write, stale-preview rejection, admin_edit precedence lock, apply-time floor clamp on revert, batch best-effort mix, retention prune |
| `test_api.py` | Admin API: decisions list/detail (auth, sort allowlist, channel/recommendation filter validation, competitor_only switch, zero side-effects), bounds (auth, missing params, unknown channel/sku), history (auth, filters), apply (auth, cap 1000/1001, actionable write + PriceDecision, stale mismatch, not-actionable skip, throttling 31st request -> 429), rule CRUD (auth, exactly-one-scope, unknown channel, whitelist defense unit test) |
