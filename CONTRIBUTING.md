# Contributing to xy

The full contributor guide — PR checklist, local gate commands, and the
chart-type contribution walkthrough — lives at
[`spec/process/contributing.md`](spec/process/contributing.md).

Quick start:

```bash
git clone https://github.com/reflex-dev/xy.git
cd xy
make setup        # dev environment + native core (needs Rust)
make check        # fast gate
make check-full   # full production gate (also needs Node 18+ and clippy)
```

## Release notes

`CHANGELOG.md` is generated and is the release trigger, so don't edit it by
hand. Add a [towncrier](https://towncrier.readthedocs.io/) news fragment for
every user-visible change instead:

```bash
make news NAME=1234.feature.md   # breaking, deprecation, feature, bugfix,
                                 # performance, docs, misc
make news-check                  # the same check your pull request runs
```

Write it for someone reading release notes. Before you know the PR number, name
it `+something.feature.md` and rename it later.

## Check the active backend

`import xy` is intentionally lightweight: it does not import NumPy or load the
native core. Import `xy.kernels` to initialize the compute backend:

```bash
python -c "import xy.kernels as k; print(k.BACKEND)"
```

`BACKEND` is always `native`; an unavailable native core raises `ImportError`
with remediation instead of silently degrading.

Design questions are settled by [`spec/design-dossier.md`](spec/design-dossier.md)
— code comments cite its §-numbers. Read the relevant section before changing
behavior, and don't regress the invariants listed in `CLAUDE.md`.
