# Contributing to fastcharts

The full contributor guide — PR checklist, local gate commands, and the
chart-type contribution walkthrough — lives at
[`docs/contributing.md`](docs/contributing.md).

Quick start:

```bash
git clone https://github.com/reflex-dev/reviz.git
cd reviz
uv venv && uv pip install -e ".[dev]"
make check        # fast gate
make check-full   # full production gate (needs Rust + Node 18+)
```

Design questions are settled by [`docs/design-dossier.md`](docs/design-dossier.md)
— code comments cite its §-numbers. Read the relevant section before changing
behavior, and don't regress the invariants listed in `CLAUDE.md`.
