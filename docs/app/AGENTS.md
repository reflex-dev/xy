<!-- reflex managed begin (do not edit inside this block; add custom content outside the markers) -->
# Agents

This project uses the **Reflex agent skills** — up-to-date knowledge for building full-stack Python web apps with [Reflex](https://reflex.dev). Install them first, then use them as described below.

## Installing the Skills

Before working on this project, make sure the Reflex skills are available to you.

### Claude Code

If the skills are not already available, install them yourself by running these shell commands:

```bash
claude plugin marketplace add reflex-dev/agent-skills
claude plugin install reflex@reflex-agent-skills
```

Newly installed plugins load on the next session. After installing, tell the user to restart the session so the skills auto-load; until then, read the skill files directly from `~/.claude/plugins/` when you need them.

### Other agents (Cursor, OpenCode, Codex, Pi)

```
npx skills add reflex-dev/agent-skills
```

Or clone https://github.com/reflex-dev/agent-skills and copy the `skills/` folders into your agent's skill directory (see the repo README for paths).

### Verifying

Before writing or editing any Reflex code, confirm these three skills are available: `reflex-docs`, `setup-python-env`, and `reflex-process-management`. If they are not, STOP and run the install step above — do not proceed without them.

## Using the Skills

### Reflex documentation

For anything about Reflex APIs — components, state management, events, styling, database, routing, authentication — use the **reflex-docs** skill rather than relying on memory. It carries current, version-accurate docs.

### Initializing a new Reflex project

When starting a new Reflex project or setting up a development environment, you **must** follow the **setup-python-env** skill before doing anything else.

Do not skip any steps. Do not assume a virtual environment or Reflex is already available — always verify first by following the skill's instructions in order.

After the environment is ready and Reflex is installed, run:

```bash
reflex init
```

Then proceed with the user's request.

### Managing a Reflex process

When you need to compile, run, reload, or debug a Reflex application, follow the **reflex-process-management** skill for the correct sequence and error investigation steps.
<!-- reflex managed end -->

# XY Documentation App

This nested project is the public XY documentation site. It is a Reflex app
mounted at `/docs/xy` and intentionally follows the official Reflex docs
structure and presentation.

## Project layout

```text
xy_docs/                 # App entry point and XY-specific site composition
  config.py              # Public Markdown discovery and navigation order
  navbar.py              # XY branding using the shared docs shell
  sidebar.py             # Memoized XY navigation
  footer.py              # XY wrapper around the shared Reflex footer
scripts/                 # Post-build sitemap, Markdown, and HTML validators
tests/                   # Docs, links, live-preview, and integration tests
../                      # Public Markdown sources
../../spec/              # Internal project docs; never published
```

## Commands

Run app commands from `docs/app` unless a command explicitly uses
`--project docs/app`:

```bash
uv sync --frozen --group dev
uv run --no-sync reflex run
uv run --no-sync reflex run --env prod
uv run --no-sync pytest tests
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync codespell .
```

See `README.md` for the post-build validators and commands that run from the
repository root.

## Conventions

- Render documentation through Python and Reflex. Do not introduce generated
  HTML pages or iframe-based examples.
- Public pages are Markdown files discovered through `DocsSiteConfig`. Add
  routes and sidebar order to `DOCS_NAVIGATION`; do not add ordering
  frontmatter to individual files.
- Leaf pages that own public callable APIs declare them in ordered
  `components:` frontmatter, using exported `xy.*` or `reflex_xy.*` names. The
  docs app appends the same generated API Reference to HTML, per-page Markdown,
  and `llms-full.txt`; do not author that section manually. Invalid, duplicate,
  private, or non-callable entries fail docs compilation. Overview and general
  guide pages should omit this key when a focused component or reference page
  already owns the API.
- Use `python demo exec` fences for code with a live preview, matching the
  official Reflex docs. Reserve `python demo-only exec` for intentionally
  hidden duplicate code. Demos must compile into real `reflex_xy.chart`
  components and static `.xyf` payloads.
- Preserve `/docs/xy` in internal links, canonical URLs, generated Markdown
  aliases, and sitemap entries.
- Reuse `reflex-site-shared` for the docs shell, Markdown renderer, styles,
  Inkeep search, breadcrumbs, footer, and responsive drawers. Keep XY branding,
  navigation data, `rxconfig.py`, and small consumer-specific wrappers local.
- Preserve `rx.memo` boundaries on the shared and XY sidebar components so
  large navigation trees compile once.
- Generated `.web/`, `assets/external/`, and `assets/xy/` content is local
  build output and must not be committed.
- Prefer a little consumer-side duplication when a shared API would otherwise
  become complex or couple unrelated sites.

## Verification

For Markdown-only changes, run the docs tests and Ruff. For changes to routing,
components, plugins, shared packages, or live previews, also start the
production app and run every validator documented in `README.md`. Run the
adapter tests under `tests/reflex_adapter/` when changing `reflex_xy` behavior.
