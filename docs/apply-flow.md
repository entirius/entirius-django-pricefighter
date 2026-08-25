# Apply Flow — write path

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
