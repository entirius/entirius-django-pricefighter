# AGENTS.md

Competitive pricing engine for Volkanos — distribution `entirius-django-pricefighter`,
Django app `django_pricefighter`.

## Quick Reference

Mirrors PIM products per channel (Pattern 2 scoping channel + synced
`ProductRepresentation`), resolves a pricing strategy per sku×market (`PricingRule`,
most-specific-wins), computes a per-request decision view (`quote_engine` + `engine_inputs`
+ `decision_view_service`) that joins our price, cost, pricemanager bounds, and atlas
competitor observations into gap+recommendation+suggested price, and applies an approved
decision (`apply_service`) through pricemanager's `edit_price()`, logging a `PriceDecision`
snapshot. The full engine/apply flow is wrapped in an admin v2 API — decision view
(list/detail), bounds, decision history, apply (single==batch), and PricingRule CRUD, on
top of the channels endpoints.

**Tech:** Python >=3.11, Django >=5.0, DRF, Pydantic, drf-spectacular, Celery,
entirius-django-utils (BaseModel), entirius-django-regional (Language),
entirius-django-pricemanager (bounds, `edit_price()`). `django_pim` is a soft dependency
(try/except ImportError, extra `pim`) — sync no-ops without it. `django_atlas`
(entirius-django-atlas) is a hard runtime dependency of the engine services
(`engine_inputs`, `market_service`); its dependency declaration lands in `pyproject.toml`
with the first entirius-django-atlas release — until then install it alongside.

## Commands

| Command | Meaning |
|---|---|
| `make install` | sync dependencies (uv, incl. extras) |
| `make check` | lint + format-check (ruff) |
| `make fix` | auto-fix lint + format |
| `make test` | test suite (pytest + pytest-django; postgres via `DATABASE_URL`) |

## Conventions

- English only: code, docs, commits, branches, PRs.
- MPL-2.0: every non-trivial source file carries the license header (pre-commit inserts it).
- Toolchain: uv + ruff + hatchling + pytest; all config in `pyproject.toml`; `uv.lock` committed.
- Git flow: `master` (production) + `develop` (integration); changes land via PR; semver tag on `master`.
- Never rename the package / Django app_label / DB table prefix `django_pricefighter` — it is a schema contract.
- Migrations are part of the public contract — never edit an already released migration.
- Default: do not commit — git is the user's call.

## Commit Message Format

**NEVER add `Co-Authored-By: Claude ...` (or any other Claude/Anthropic attribution) to commit messages.**

This overrides the default Claude Code behavior of appending a `Co-Authored-By` trailer. Commit messages MUST contain only the user's authored content — no robot footer, no "Generated with Claude Code" line, no co-author trailer.

Same rule applies to PR descriptions: no `Generated with [Claude Code]` footer.

## Architecture

```
src/django_pricefighter/
├── models/
│   ├── channel.py               # Channel (Pattern 2 scoping channel)
│   ├── product_representation.py #  ProductRepresentation (per-channel PIM mirror)
│   ├── pricing_rule.py          # PricingRule (strategy/scope, exactly-one-scope CheckConstraint)
│   ├── quote_config.py          # QuoteConfig (quoting parameters per currency x price range)
│   └── price_decision.py        # PriceDecision (decision audit log — apply-time only)
│
├── services/
│   ├── channel_sync_service.py         # sync_channels_from_pim(), list_channels()
│   ├── representation_sync_service.py  # sync_pair(sku, channel_idx), full_sync()
│   ├── rule_resolver.py                # resolve() + resolve_bulk() -> ResolvedRule
│   ├── quote_engine.py                 # PURE pipeline: EngineInput -> EngineDecision, zero ORM
│   ├── market_service.py               # get_markets(), get_candidate_skus(), get_all_skus()
│   ├── engine_inputs.py                # bulk-fetch: skus x markets -> list[EngineInput]
│   ├── decision_view_service.py        # enumerate -> fetch -> engine -> sort -> paginate
│   ├── apply_service.py                # apply_single()/apply_batch() -> write + PriceDecision
│   ├── bounds_service.py               # thin: resolve pm Channel/Country by idx/iso2 -> get_price_bounds
│   ├── decision_history_service.py     # thin: PriceDecision query, filters only
│   └── pricing_rule_service.py         # PricingRule CRUD, mass-assignment whitelist (_EDITABLE_FIELDS)
│
├── api/admin/                   # v2 Admin API (JWT + IsAdminUser)
│   ├── views/
│   │   ├── channel_views.py     #   list + sync action
│   │   ├── decision_views.py    #   decision view list + detail (sort allowlist, filters)
│   │   ├── bounds_views.py      #   bounds retrieve
│   │   ├── history_views.py     #   PriceDecision history list
│   │   ├── apply_views.py       #   apply (single == 1-item batch), throttled
│   │   └── rule_views.py        #   PricingRule CRUD
│   ├── throttling.py            #   ApplyThrottle (per-user, scope pricefighter_apply)
│   ├── urls.py, pagination.py, permissions.py
│
├── schemas/
│   ├── responses/                      # channel, decision_view, decision_history, bounds, apply, pricing_rule
│   └── requests/                       # apply, pricing_rule
│
├── tasks.py                     # Celery: pricefighter.flush_pending_sync, pricefighter.full_sync
├── management/commands/
│   ├── sync_pricefighter_channels.py   # channel_sync_service wrapper (seed/entrypoint)
│   └── pricefighter_full_sync.py       # representation_sync_service.full_sync() wrapper
│
├── admin.py                     # Django admin (Channel sync action, QuoteConfig/PricingRule full_clean on save)
└── urls.py                      # api/pricefighter/v2/admin/
```

Layer rule: `API → Services → Models → DB`. No ORM in views.

---

## Data Model

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

## Sync (PIM -> PriceFighter)

Two independent mechanisms feed `ProductRepresentation`, both funnelling through
`representation_sync_service`:

1. **Signal-driven** (near-real-time): django-pim's THIRD signal tor
   (`PimSettings.pricefighter_signals_enabled`, default **off**) enqueues
   `sku:channel_idx` pairs into Redis (`pim:pricefighter:pending`, debounced) on
   Product/ProductAttribute/ProductInCategory save+delete. `pricefighter.flush_pending_sync`
   drains the set and calls `sync_pair()` per pair.
2. **Cron full-sync** (`pricefighter.full_sync`, `CELERY_BEAT_SCHEDULE` entry
   `pricefighter.full_sync_daily`, 04:30 UTC): walks every local `Channel`, upserts every
   PIM product via `sync_pair()`, deactivates representations whose sku didn't come back.
   Covers initial population and drift when the signal tor is off (the default).

`sync_pair(sku, channel_idx)`:
- No local `Channel` for that idx -> skip (log + `None`), no representation touched.
- `django_pim` not importable, or the PIM product no longer exists -> deactivate the
  existing representation (`is_active=False`), never delete it.
- Otherwise upsert: `name` via `product.name_lang(channel.default_language.iso2)`, `category`
  via the first `ProductInCategory` ordered by `position`.

Channels are synced separately via `channel_sync_service.sync_channels_from_pim()` —
`admin/channels/sync/` (idempotent, `update_or_create` by idx) or
`manage.py sync_pricefighter_channels`.

---

## Strategy Resolution

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

## Decision Engine — read path, side-effect-free

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

## Apply Flow — write path

**Two logs, two purposes.** `PriceDecision` (this module) is the *decision*-level audit —
strategy, mode, and a full input snapshot, written **only** at an explicit apply action
(never at render). `PriceHistory` (pricemanager) is the *write*-level audit of the resulting
`CurrentPrice` row, written by `edit_price()` for every price change regardless of who wrote
it. A `PriceDecision` row always has a matching `PriceHistory` row; the reverse isn't true
(admin edits, CSV imports, etc. only touch `PriceHistory`).

`apply_service.apply_single(ApplyItem, *, user=None, policy_map=None) -> ApplyResult`:
1. **Recompute** the decision live for exactly this `(sku, market)` — never trust the
   preview the operator is looking at; the DB may have moved since.
2. Not one of `{compete, raise, revert_baseline, hold_at_floor}` -> `skipped`
   (`not_actionable:<reason>`), zero writes.
3. Freshly-recomputed `suggested_price` (quantized to cents) != `ApplyItem.expected_new_price`
   -> `stale`, zero writes — the operator must refresh their preview and retry.
4. Resolve pricemanager `Channel`/`Country`/`Currency` + this module's `Channel` +
   `ProductRepresentation` for the sku. Any missing -> `failed`.
5. Convert the GROSS target to whatever `edit_price()` expects via
   `Channel.calculate_direction`: `FROM_GROSS_TO_NET` -> pass the target as-is;
   `FROM_NET_TO_GROSS` (the default) -> pass `tax_rate.net_price(target)` so the gross side
   `edit_price` computes lands back on the target exactly.
6. `edit_price(channel=..., sku=..., value=..., country=<this market only>,
   source=PriceSource.PRICEFIGHTER, stored_source=PriceSource.BASELINE if reverting else None,
   policy_map=...)`. `country` scopes the write to exactly the market the operator
   previewed — other countries on the same channel are untouched. `stored_source` labels a
   revert honestly: it writes with `writer=pricefighter` (so it may overwrite its own prior
   row) but the *persisted label* is `baseline` (so the layer picture shows pricefighter
   backed off).
7. Map pricemanager's `EditPriceReport` to a bucket: guard rejected -> `skipped`
   (guard's reason); guard clamped -> `clamped`; wrote cleanly -> `applied`; `ValueError`
   (e.g. unknown sku) -> `failed`.
8. `applied`/`clamped` only -> write `PriceDecision` (old/new price, strategy, mode, the full
   input snapshot, `applied_by`) and call `record_strategy_outcome()` — a **v2 no-op hook**,
   wired now so `StrategyOutcome` (source x price-range x strategy x market memory) doesn't
   need another pass through this file later.

`apply_batch(items, *, user=None) -> {"applied": [...], "clamped": [...], "skipped": [...],
"failed": [...], "stale": [...]}` — best-effort, `load_policy_map()` once for the whole
batch, each item still recomputes its own decision independently (correctness over batch
query-count optimization; apply is an infrequent operator action, not the 10-30k-row render
path).

**Retention**: `pricefighter.prune_decisions` (Celery, `PRICEFIGHTER_DECISION_RETENTION_DAYS`
default 365, purge-only) — register it in the deployment's `CELERY_BEAT_SCHEDULE`
(e.g. daily, right after `pricefighter.full_sync_daily`).

**Escalation ladder (documented, NOT built in v1)** — the render path is on-the-fly, no cache,
no read-model (2-3 internal users, not a storefront). If/when that stops being true:
1. Cache the rendered rows with a short TTL per `(channel, filter-set)`.
2. A read-model table that a feed writes and the view reads, keeping the exact same output
   shape — `decision_view_service`'s row shape is the seam either escalation step slots
   behind without changing callers.

---

## API Surface

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

## Testing

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test make test   # postgres required
```

| File | Scope |
|------|-------|
| `test_models.py` | Constraints (unique sku+channel, PricingRule exactly-one-scope), `QuoteConfig.clean()` validations, seed-fixture `full_clean()` sanity |
| `test_services.py` | Channel sync (create/update/idempotent/no-pim), representation sync (upsert/idempotent/deactivate-on-delete/denorm/full_sync), rule_resolver (most-specific-wins/default/tie-break) |
| `test_admin_api.py` | Channels list/sync — 401/403/200, idempotent sync |
| `test_quote_engine.py` | Pure pipeline, no DB: estimators, every observation filter, gap+hysteresis, strategy permission, rounding, floor/max_step clamps, NO_COMP branches, price_war |
| `test_decision_view_integration.py` | market_service + engine_inputs + decision_view_service against a real DB: pre-filter, sort, pagination, constant query count across batch sizes, zero writes on render |
| `test_apply_service.py` | Single apply (write + PriceDecision snapshot), country-scoped write, stale-preview rejection, admin_edit precedence lock, apply-time floor clamp on revert, batch best-effort mix, retention prune |
| `test_api.py` | Admin API: decisions list/detail (auth, sort allowlist, channel/recommendation filter validation, competitor_only switch, zero side-effects), bounds (auth, missing params, unknown channel/sku), history (auth, filters), apply (auth, cap 1000/1001, actionable write + PriceDecision, stale mismatch, not-actionable skip, throttling 31st request -> 429), rule CRUD (auth, exactly-one-scope, unknown channel, whitelist defense unit test) |

Factories live in `tests/conftest.py`: `pim_channel_factory`, `pf_channel_factory`,
`pim_product_factory`, `pim_category_factory` build the minimal PIM object graph
(RealProduct + FeatureSet + Product) needed to exercise the sync services without a full
PIM fixture. `decision_fixture` builds the full cross-module graph the engine/apply tests
need (pricemanager Channel/TaxRate/CurrentPrice/PurchaseCost/BaselineConfig, an atlas
monitoring `Source`, this module's `Channel`/`ProductRepresentation`/`QuoteConfig`) — one
market (`ch1`/DE/USD), `SKU-A` with a valid observation, `SKU-B` without.

Celery tasks: `pricefighter.flush_pending_sync`, `pricefighter.full_sync`,
`pricefighter.prune_decisions` (PriceDecision retention).

---

## Gotchas

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

## Reference Docs

| File | Content |
|------|---------|
| `docs/erd-config.yaml` | ERD diagram config |
