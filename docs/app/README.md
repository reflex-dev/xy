# xy docs app

The xy documentation site is a small, self-contained Reflex app. Its shell is
adapted from the Reflex documentation site: a fixed top navigation, grouped
left navigation, breadcrumbs, an on-page table of contents, search, responsive
mobile navigation, and previous/next links.

Markdown remains the source of truth. Pages live in `docs/`, one level above
this app, and the navigation order is declared in `xy_docs/navigation.py`.

## Run locally

```bash
cd docs/app
uv sync
uv run reflex run
```

Open <http://localhost:3000/>. Changes to Python files require a restart;
Markdown changes are picked up when the app recompiles.

## Verify

```bash
cd docs/app
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run reflex export --frontend-only --no-zip
```

When adding a Markdown page, add it to `SECTIONS` in
`xy_docs/navigation.py`. The tests ensure every declared source exists, every
route is unique, and every public Markdown document is represented in the
sidebar.
