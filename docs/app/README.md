# XY Docs

This Reflex app renders the public Markdown files in the parent `docs/`
directory with the same `reflex-site-shared` shell, Markdown pipeline, and
styles used by the official Reflex documentation.

## Getting Started

Run these commands from `docs/app`:

1. Install the locked dependencies:

   ```bash
   uv sync --frozen --group dev
   ```

2. Start the development server:

   ```bash
   uv run --no-sync reflex run
   ```

3. Open [http://localhost:3000/docs/xy/](http://localhost:3000/docs/xy/).

Restart the server after changing Python components, configuration, plugins,
or packaged frontend assets. Markdown-only edits are picked up during normal
development.

## Editing Docs

Public pages live in the parent `docs/` directory. Page routes and sidebar
order are declared centrally in `xy_docs/config.py`; do not add ordering
frontmatter to individual Markdown files. The `spec/` tree is
internal project documentation and is intentionally excluded from the public
site.

Executable fences marked `python demo exec` render in shared Preview/Code
tabs. Add `# --- chart ---` after a hardcoded data section only when that
section exceeds 10 nonblank lines; it then renders in a separate Data tab. Use
`python demo-only exec` only when the code is intentionally shown elsewhere.
Keep examples deterministic, small, and valid without external services.
Static XY payloads generated during compilation are written below `assets/xy/`
and must not be committed.

## Checks

From the repository root:

```bash
uv sync --project docs/app --frozen --group dev
uv run --project docs/app --no-sync pytest docs/app/tests
uv run --project docs/app --no-sync pre-commit run --all-files
```

Run the production app from `docs/app` when changing routing, rendering,
plugins, shared components, or live examples:

```bash
REFLEX_TELEMETRY_ENABLED=false uv run --no-sync reflex run --env prod
```

After the production frontend is generated, run:

```bash
uv run --no-sync pytest --runxfail \
  tests/test_docs_site.py::test_xy_markdown_docs_links_match_exported_sitemap
uv run --no-sync python scripts/check_sitemap.py
uv run --no-sync python scripts/check_markdown_assets.py
uv run --no-sync python scripts/check_html_routes.py
```

The frontend is mounted at `/docs/xy`; preserve that prefix in canonical URLs,
the sitemap, Markdown aliases, and internal documentation links.

## Working on the shared Reflex theme

The base theme, button and search assets, navbar frame, announcement, sidebar
shell, and footer primitives come directly from `reflex-site-shared`. Do not
copy those implementations into XY. XY owns its wordmark, navigation
destinations, page actions, footer links, and docs-specific brand layer.

The three `assets/docs-*-theme.css` / `assets/docs-theme.css` stylesheets are
the local marketing brand contract. They load after the shared base theme and
replace the earlier warm palette, capsule controls, and opal artwork. Use the
marketing light canvas (#FDFCFC), ink (#0A0A0A), neutral gray surfaces and
borders, and charcoal primary actions. Dark mode remains available with neutral
dark counterparts. Chart colors and syntax themes retain their own contracts.
Geist 400 supplies article text and headings. Inter remains the compact
navigation and internal UI font. Actions use Geist 525 with 8px corners. The docs
radius token keeps live example settings isolated. Feedback fields use 12px
corners, a 2px `--ring` halo for keyboard focus, and a system-color outline in
forced-colors mode. Preserve the docs' 64px navigation and
compact reading, sidebar, and table of contents layout.

The shared announcement keeps its native link and close event, with a flat black
background and white text in both modes. Its visible contribution is 40px at
every width, with no decorative artwork or overlap. The header has 12px top
corners against black backing while the announcement is visible; opening the
mobile menu or dismissing the announcement returns the header to square corners.
The head script in `xy_docs/announcement.py` restores marketing's
release-scoped local-storage dismissal before paint so dismissal survives reloads
and same-origin navigation without a flash or reserved gap. Announcement title,
destination, and release follow marketing and must be updated together when its
copy changes. Fonts are bundled from pinned Fontsource frontend packages.

Editorial styles target shared `docs-*` hooks and the hooks added by
`xy_docs_layout`, preserving live chart typography, data colors, and interactions.
The shared Markdown layout owns navigation destinations; XY adds a two-column
Back/Next treatment. Keep native links, labelled inputs, selected states,
visible keyboard focus, reduced motion, and both color modes when editing the
brand layer. Check desktop, 390px and 320px reading layouts, drawers, search,
feedback, copy actions, announcement dismissal, and long tables/code.

To preview unpublished edits from a Reflex checkout, first install the locked
XY docs environment, then install just the shared package editably (run from
`docs/app`; replace the checkout path as needed):

```bash
HATCH_BUILD_NO_HOOKS=true uv pip install --python .venv/bin/python --no-deps \
  --editable ~/Drive/reflex-work/reflex/reflex/packages/reflex-site-shared
uv run --no-sync reflex run --env prod
```

`--no-deps` retains XY's locked framework environment; disabling build hooks
avoids generating upstream stubs just to preview the site. Use `--no-sync` for
subsequent commands, and restart after shared Python or theme asset changes.
`uv sync --frozen --group dev` restores the published Git dependency. The local
editable installation is intentionally not a machine-specific lockfile change.
The committed Git lock includes the shared docs styling hooks and named mobile
drawer from the merged design PR. Refresh all Reflex monorepo packages together
when updating that revision, then run the production checks above.
