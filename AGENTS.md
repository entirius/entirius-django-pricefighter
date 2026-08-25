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
(entirius-django-atlas) is a **hard** runtime dependency of the engine services
(`engine_inputs`, `market_service`), declared in `dependencies`. Atlas is private and not on
PyPI, so `[tool.uv.sources]` resolves it from git and CI authenticates with the
`ATLAS_READ_TOKEN` secret — delete both at atlas's first PyPI release.

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

All models inherit `django_utils.models.base_model.BaseModel` (`created_at`/`modified_at`):
`Channel`, `ProductRepresentation`, `PricingRule`, `QuoteConfig`, `PriceDecision`.
Field-by-field reference and constraints: `docs/data-model.md`.

## Sync (PIM -> PriceFighter)

Two independent feeds into `ProductRepresentation` — signal-driven (default **off**) and a
daily cron full-sync — both funnelling through `representation_sync_service`. Channels sync
separately via `channel_sync_service`. See `docs/sync.md`.

## Strategy Resolution

`rule_resolver.resolve()` is most-specific-wins: **sku > category > channel**, ties broken by
`pk`, falling back to `DEFAULT_RESOLVED_RULE` (`hold`). `strategy` is a *directional
permission*, not an engine on/off switch. See `docs/strategy-resolution.md`.

## Decision Engine — read path, side-effect-free

`decision_view_service.build_decision_rows()` enumerates markets, bulk-fetches through
`engine_inputs` (constant query count), runs each sku×market through the pure
`quote_engine.compute_decision()`, then sorts/paginates in RAM. Zero writes.
Full 10-step pipeline, observation flags and invariants: `docs/decision-engine.md`.

## Apply Flow — write path

`apply_service.apply_single()` **recomputes** the decision live, rejects a stale preview,
writes through pricemanager's `edit_price()` and logs a `PriceDecision` snapshot.
`PriceDecision` (decision-level) and pricemanager's `PriceHistory` (write-level) are two
distinct logs. Full 8-step flow, buckets and retention: `docs/apply-flow.md`.

## API Surface

Prefix `/api/pricefighter/v2/admin/` (JWT + `IsAdminUser`, explicit on every ViewSet):
channels, decisions (list/detail), bounds, history, apply, and PricingRule CRUD.
Endpoint table with filters, sorts and payloads: `docs/api.md`.

## Testing

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test make test   # postgres required
```

Per-file scope map: `docs/testing.md`.

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

Full list: `docs/gotchas.md`. The ones that bite hardest:

- **Two distinct `Channel`/`ProductRepresentation` pairs exist** — this module's own and
  pricemanager's. `engine_inputs`/`apply_service` import both under aliases
  (`PmChannel`/`PfChannel`); passing the wrong one into a pricemanager bulk function is a
  silent wrong-table error at the ORM boundary, not a clean exception.
- `quote_engine.py` has **zero Django/ORM imports on purpose** — `now` is always a parameter,
  never `timezone.now()`, so its unit tests stay deterministic without freezegun.
- `ProductRepresentation` follows the **matrix** idiom (channel-scoped, synced), not
  pricemanager's lazy auto-create idiom — do not copy that pattern here.
- `full_sync()` excludes on **exact-case** `sku__in=seen_skus`; lowercase one side only and
  every product looks "gone" and gets deactivated.
- `QuoteConfig.clean()` / `PricingRule.clean()` are **not** called by `ModelAdmin` by default —
  both admin classes override `save_model` to call `full_clean()`; bulk paths bypass it entirely.
- The decision view's `margin` is net-based (`(net_value - net_cost) / net_value * 100`),
  matching pricemanager's definition — **not** `(gross - cost) / gross`.

## Reference Docs

| File | Content |
|------|---------|
| `docs/data-model.md` | Model-by-model field reference and constraints |
| `docs/sync.md` | PIM -> PriceFighter sync (signal tor + cron full-sync) |
| `docs/strategy-resolution.md` | `rule_resolver` precedence and the strategy permission table |
| `docs/decision-engine.md` | The 10-step read pipeline, observation flags, invariants |
| `docs/apply-flow.md` | Apply/write path, result buckets, retention |
| `docs/api.md` | Admin v2 endpoint table |
| `docs/gotchas.md` | Full gotcha list |
| `docs/testing.md` | Per-test-file scope map |
| `docs/erd-config.yaml` | ERD diagram config |
