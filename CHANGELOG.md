# Changelog

## [Unreleased]

- Access: the module declares its own access areas on its AppConfig and its admin views (copied from the
  entirius-django-access defaults; behaviour unchanged).

## 1.0.0 — 2026-08-09

- Initial public release: channel registry and per-channel product representations
  synced from PIM, pricing-rule strategy resolution, quote configuration, the
  decision-view engine (gap + recommendation + suggested price from competitor
  observations), and the apply flow writing through pricemanager with a
  `PriceDecision` audit log.
- Migrations squashed into a single initial migration for the Entirius epoch.
