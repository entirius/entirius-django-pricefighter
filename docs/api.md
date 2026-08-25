# API Surface

Prefix: `/api/pricefighter/v2/admin/` (JWT + IsAdminUser, explicit on every ViewSet).

| Method | Path | Description |
|--------|------|-------------|
| GET | `channels/` | List channels (paginated) |
| POST | `channels/sync/` | Sync channels from PIM, idempotent, `{"synced": N}` |
| GET | `decisions/` | Decision view list. Filters: `channel`, `recommendation`, `competitor_only` (default `true`). Sort: `sort=gap\|sku\|name\|current_price\|competitor_price\|margin`, prefix `-` for descending (default `-gap`) |
| GET | `decisions/{sku}/` | Decision detail for one sku×market. Required query params: `channel`, `country`, `currency`. Includes the full observation list (filtered entries included, flagged) |
| GET | `bounds/` | Floor/ceiling/baseline for one sku×market. Required query params: `sku`, `channel`, `country` |
| GET | `history/` | Paginated `PriceDecision` audit log. Filters: `sku`, `channel`, `country`, `currency`, `strategy` |
| POST | `apply/` | Apply priced decisions — single is a 1-item batch. Body: `{"items": [{"sku", "market": {"channel","country","currency"}, "expected_new_price"}]}`, cap 1000 items. Response: `{"applied", "clamped", "skipped", "failed", "stale"}` (report passes through `apply_service.apply_batch()` 1:1). Throttled: `pricefighter_apply` scope, per-user, 30/hour class-level fallback |
| GET | `rules/` | List pricing rules (paginated) |
| POST | `rules/` | Create a rule. Body: `strategy`, `mode` (default `suggestion`), `price_war` (default `false`), exactly one of `sku`/`category_idx`/`channel` |
| GET | `rules/{id}/` | Retrieve a rule |
| PATCH | `rules/{id}/` | Update a rule (partial — only provided fields change) |
| DELETE | `rules/{id}/` | Delete a rule |

`decisions/`, `bounds/`, `history/` never write (render-only, verified by
`test_decision_view_integration.py` and `test_api.py`). `channel` on a rule create/update is
resolved by idx (never a raw FK PK) and validated to exist — unknown idx raises `ValueError`
-> 400. `pricing_rule_service._EDITABLE_FIELDS` is the entire mass-assignment defense (no
parallel field checks) — a caller outside the API (management command, integration bridge)
that passes an unlisted field gets `ValueError`, same as an API caller would via a future
schema change.

---
