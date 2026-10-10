# AGENTS.md

`entirius-django-pricefighter` (Django app `django_pricefighter`) — competitive pricing engine of Entirius.

Mirrors PIM products per channel (Pattern 2 scoping channel + synced
`ProductRepresentation`), resolves a pricing strategy per sku×market (`PricingRule`,
most-specific-wins), computes a per-request decision view (`quote_engine` + `engine_inputs`
+ `decision_view_service`) that joins our price, cost, pricemanager bounds, and atlas
competitor observations into gap+recommendation+suggested price, and applies an approved
decision (`apply_service`) through pricemanager's `edit_price()`, logging a `PriceDecision`
snapshot. The full engine/apply flow is wrapped in an admin v2 API — decision view
(list/detail), bounds, decision history, apply (single==batch), and PricingRule CRUD, on
top of the channels endpoints.

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
- Access: areas live on the AppConfig (`access_areas`, `access_route_rules`), every admin view carries
  `access_area`; a new admin route without one fails `tests/test_access_ownership.py`.
- Default: do not commit — git is the user's call.

### Commit Message Format

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
├── tasks.py                     # Celery: pricefighter.flush_pending_sync, .full_sync, .prune_decisions
├── management/commands/
│   ├── sync_pricefighter_channels.py   # channel_sync_service wrapper (seed/entrypoint)
│   └── pricefighter_full_sync.py       # representation_sync_service.full_sync() wrapper
│
├── admin.py                     # Django admin (Channel sync action, QuoteConfig/PricingRule full_clean on save)
└── urls.py                      # api/pricefighter/v2/admin/
```

Layer rule: `API → Services → Models → DB`. No ORM in views.

Dependencies: `django_utils` (BaseModel), `django_regional` (Language), `django_pricemanager` (bounds,
`edit_price()`) and `django_atlas` (observations — a hard runtime dependency of `engine_inputs` and
`market_service`). `django_pim` is a soft dependency (try/except ImportError, extra `pim`) — sync no-ops without it.

| Topic | Where |
|---|---|
| Model-by-model field reference and constraints | `docs/data-model.md` |
| PIM -> PriceFighter sync: signal-driven feed (default off), daily cron full-sync, channel sync | `docs/sync.md` |
| `rule_resolver` precedence (sku > category > channel) and the strategy permission table | `docs/strategy-resolution.md` |
| Read path: the decision pipeline, observation flags, invariants | `docs/decision-engine.md` |
| Write path: recompute, stale-preview rejection, result buckets, `PriceDecision` retention | `docs/apply-flow.md` |
| Admin v2 endpoint table with filters, sorts and payloads | `docs/api.md` |
| Per-test-file scope map, run command, fixtures | `docs/testing.md` |
| Full gotcha list | `docs/gotchas.md` |
| ERD diagram config | `docs/erd-config.yaml` |


## Settings

| Setting | Default | Purpose |
|---|---|---|
| `PRICEFIGHTER_REF_ESTIMATOR` | `"min"` | reference price estimator: `min` / `second_best` / `median` |
| `PRICEFIGHTER_STALENESS_DAYS` | `3` | observations older than this are flagged `stale` |
| `PRICEFIGHTER_DECISION_RETENTION_DAYS` | `365` | `PriceDecision` retention for `pricefighter.prune_decisions` |

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
