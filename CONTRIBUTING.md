# Contributing to xy

The full contributor guide — PR checklist, local gate commands, and the
chart-type contribution walkthrough — lives at
[`docs/engineering/contributing.md`](docs/engineering/contributing.md).

Quick start:

```bash
git clone https://github.com/reflex-dev/xy.git
cd xy
make setup        # dev environment + native core (needs Rust)
make check        # fast gate
make check-full   # full production gate (also needs Node 18+ and clippy)
```

## Check the active backend

`import xy` is intentionally lightweight: it does not import NumPy or load the
native core. Import `xy.kernels` to initialize the compute backend:

```bash
python -c "import xy.kernels as k; print(k.BACKEND)"
```

`BACKEND` is always `native`; an unavailable native core raises `ImportError`
with remediation instead of silently degrading.

Design questions are settled by [`docs/engineering/design-dossier.md`](docs/engineering/design-dossier.md)
— code comments cite its §-numbers. Read the relevant section before changing
behavior, and don't regress the invariants listed in `CLAUDE.md`.
