# `xy.pyplot` execution modes

`xy.pyplot` has a staged compatibility switch:

| Mode | Behavior |
|---|---|
| `native` | The existing dependency-free XY 2-D pyplot shim. Select it explicitly to pin the lightweight implementation. |
| `compat` | Matplotlib 3.11 supplies Figure, Axes, Artist, layout, units, toolkit, and projection semantics; `module://xy.backends.backend_xy` supplies the canvas and renderer. Install it with `pip install "xy[matplotlib]"`. |
| `auto` | The configured default. It resolves to `compat` when supported Matplotlib 3.11 is installed and to `native` otherwise. |

Configure a process before creating figures:

```python
import xy.pyplot as plt

plt.set_mode("compat")
fig, ax = plt.subplots()
```

The equivalent process-level setting is:

```console
XY_PYPLOT_MODE=compat python example.py
```

In compat mode, every public attribute exported by `matplotlib.pyplot` is
available lazily, including names outside xy's native `__all__`. Direct
from-imports use the same resolver. Figure, Axes, GridSpec, locator, formatter,
artist, and colormap constructors are mode-aware: they retain xy's native
classes in native mode and construct genuine Matplotlib classes in compat
mode. They also support attribute lookup, `isinstance`/`issubclass`, and use as
a class base.

`plt.get_mode()` reports the configured value, including `auto`. Importing
`xy.pyplot`, reading the mode, and explicitly selecting a mode do not import
Matplotlib. The first compat-routed pyplot call validates Matplotlib
`>=3.11,<3.12`, activates the XY backend, and then imports
`matplotlib.pyplot`.

Selecting `compat` also sets Matplotlib's lightweight `MPLBACKEND` environment
hint to `module://xy.backends.backend_xy` without importing Matplotlib. This
matters when a toolkit helper creates the first figure before the first routed
`xy.pyplot` call. If that figure already owns an XY canvas, the lazy resolver
adopts it; a pre-existing figure from another backend is still rejected.

The two frontends have separate figure registries. Changing the configured
mode while either registry contains an open figure raises an error; call
`plt.close("all")` first. Mode switching changes future `xy.pyplot` calls. It
does not restore a different global backend previously selected by external
Matplotlib code.
