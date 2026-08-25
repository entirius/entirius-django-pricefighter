# Sync (PIM -> PriceFighter)

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
