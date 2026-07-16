"""Frontend assets for the Reflex component.

One file ships in this package:

- ``XYChart.jsx`` — the React wrapper (multiplexes the `/_xy` namespace onto
  the app's existing websocket and drives ChartView).

The render client itself (``xy_client.js``) is deliberately NOT packaged
here: `register()` links it out of the **installed ``xy`` distribution**
(``xy/static/index.js``, the same ESM bundle notebooks load), landing it
beside the wrapper so the wrapper's relative ``./xy_client.js`` import
resolves. Sourcing from the install makes client/kernel drift structurally
impossible — the JS that renders a payload is always the build that shipped
with the Python that produced it.

`register()` is deliberately lazy (called from the component factory, not at
import): ``rx.asset(shared=True)`` symlinks into ``Path.cwd()/assets``, which
only makes sense while compiling an actual Reflex app.
"""

from __future__ import annotations

from pathlib import Path

WRAPPER_TAG = "XYChart"

#: Destination directory under the app's assets/ tree — must match where
#: rx.asset(shared=True) puts this module's files, because the wrapper
#: imports the client by relative path.
_EXTERNAL_SUBDIR = Path("external") / "reflex_xy" / "assets"
_CLIENT_NAME = "xy_client.js"


def _client_source() -> Path:
    """The canonical render client inside the installed xy package."""
    import xy

    source = Path(xy.__file__).resolve().parent / "static" / "index.js"
    if not source.exists():
        msg = (
            f"{source} missing — the xy install has no bundled JS client. "
            "Dev checkout: run `node js/build.mjs`; otherwise reinstall xy."
        )
        raise FileNotFoundError(msg)
    return source


def _link_client(asset_root: Path) -> None:
    """Symlink the installed client beside the wrapper (repairing stale links).

    Unlike rx.asset's shared files (which live at a fixed path next to their
    module), the client's location moves whenever the ``xy`` install
    does — so an existing link pointing at the wrong target is replaced, not
    trusted.
    """
    source = _client_source()
    dst_dir = asset_root / _EXTERNAL_SUBDIR
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / _CLIENT_NAME
    if dst.is_symlink() or dst.exists():
        try:
            if dst.resolve() == source:
                return
        except OSError:
            pass
        dst.unlink()
    dst.symlink_to(source)


def register() -> str:
    """Wire both frontend files into the compiling app; return the wrapper's
    importable module path (``$/public/external/reflex_xy/assets/...``)."""
    import reflex as rx
    from reflex.assets import EnvironmentVariables

    wrapper = rx.asset("XYChart.jsx", shared=True)
    if not EnvironmentVariables.REFLEX_BACKEND_ONLY.get():
        _link_client(Path.cwd() / "assets")
    return wrapper.importable_path
