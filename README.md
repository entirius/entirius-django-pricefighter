# entirius-django-pricefighter

A Django module for competitive pricing in Entirius, the open-source modular ecommerce platform.
It compares each product's price with competitor observations per market, recommends a new price under a pricing
strategy, and applies approved decisions through the price module with a full audit snapshot.

[![PyPI](https://img.shields.io/pypi/v/entirius-django-pricefighter.svg)](https://pypi.org/project/entirius-django-pricefighter/)
[![Python](https://img.shields.io/pypi/pyversions/entirius-django-pricefighter.svg)](https://pypi.org/project/entirius-django-pricefighter/)
[![License: MPL-2.0](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](https://github.com/entirius/entirius-django-pricefighter/blob/develop/LICENSE)

## What it does

- Mirrors catalog products per sales channel and keeps the mirror in sync (signals and a daily full sync).
- Resolves a pricing strategy per product and market (`hold`, `compete`, `raise`), most specific rule first.
- Computes a decision view: gap to the competitor reference price, a recommendation and a suggested price,
  within floor, ceiling and step limits.
- Applies an approved decision through the price module and logs a `PriceDecision` snapshot of every input.
- Exposes an admin API (JWT, Pydantic schemas, OpenAPI): channels, decisions, bounds, history, apply, rules.

## Installation

```shell
uv add entirius-django-pricefighter
pip install entirius-django-pricefighter
```

Optional extras: `entirius-django-pricefighter[pim]` (product sync from the catalog module; without it the sync
does nothing).

```python
INSTALLED_APPS = [
    ...
    "django_utils",
    "django_regional",
    "django_pricemanager",
    "django_atlas",
    "django_pricefighter",
]

# urls.py
urlpatterns = [
    path("", include("django_pricefighter.urls")),
]
```

Optional settings: `PRICEFIGHTER_REF_ESTIMATOR`, `PRICEFIGHTER_STALENESS_DAYS`,
`PRICEFIGHTER_DECISION_RETENTION_DAYS`; reference with defaults in
https://github.com/entirius/entirius-django-pricefighter/blob/develop/AGENTS.md (section Settings).

## Quick start

```python
from django_pricefighter.services.decision_view_service import build_decision_rows

# decision rows for every product with a fresh competitor observation, largest gap first
rows, total = build_decision_rows(sort="-gap_baseline", limit=50)
```

```shell
python manage.py sync_pricefighter_channels
python manage.py pricefighter_full_sync
```

## Requirements

- Python 3.11 or newer, Django 5.0 or newer, PostgreSQL, a Celery worker for the sync and retention tasks.
- Entirius packages pulled in: `entirius-django-utils`, `entirius-django-regional`,
  `entirius-django-pricemanager`, `entirius-django-atlas`.

## Documentation

- Data model: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/data-model.md
- Sync from the catalog: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/sync.md
- Strategy resolution: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/strategy-resolution.md
- Decision engine: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/decision-engine.md
- Apply flow: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/apply-flow.md
- Admin API: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/api.md
- Gotchas: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/gotchas.md
- Testing: https://github.com/entirius/entirius-django-pricefighter/blob/develop/docs/testing.md
- Entirius documentation: https://docs.entirius.com/
- Changelog: https://github.com/entirius/entirius-django-pricefighter/blob/develop/CHANGELOG.md

## Part of Entirius

This module runs inside the Entirius backend service (Volkanos); it reads competitor observations from the
external product data engine and writes prices through the price module.

- Backend service: https://github.com/entirius/entirius-service-volkanos
- Docker harness: https://github.com/entirius/entirius-zeno
- Sibling modules: https://github.com/entirius/entirius-django-atlas, https://github.com/entirius/entirius-django-pricemanager,
  https://github.com/entirius/entirius-django-pim

## Development

```shell
make install     # sync dependencies (uv, incl. extras)
make check       # lint + format check (ruff)
make test        # test suite (pytest + pytest-django, needs PostgreSQL via DATABASE_URL)
```

Development and agent instructions: https://github.com/entirius/entirius-django-pricefighter/blob/develop/AGENTS.md

## License

Mozilla Public License 2.0 (MPL-2.0) — see https://github.com/entirius/entirius-django-pricefighter/blob/develop/LICENSE.
