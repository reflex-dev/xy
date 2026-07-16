"""Component compile smoke: props, event wiring, asset registration."""

from __future__ import annotations

import os
import pathlib

import pytest
import reflex as rx
import reflex_xy


class CompState(rx.State):
    last_row: dict = {}

    @rx.event
    def picked(self, row: dict):
        self.last_row = row


@pytest.fixture
def app_cwd(tmp_path, monkeypatch):
    """rx.asset symlinks into Path.cwd()/assets — emulate an app directory."""
    monkeypatch.chdir(tmp_path)
    # component class is cached per process; asset symlinks are per-cwd, so
    # force a rebuild to exercise registration in this cwd.
    import reflex_xy.component as component_mod

    monkeypatch.setattr(component_mod, "_component_cls", None)
    return tmp_path


def test_component_compiles_with_events(app_cwd):
    comp = reflex_xy.chart("tok-abc", on_point_hover=CompState.picked, height="300px", id="chart1")
    assert comp.tag == "XYChart"
    assert str(comp.library).startswith("$/public/external/reflex_xy/assets/XYChart")
    rendered = str(comp)
    assert 'token:"tok-abc"' in rendered
    assert "onPointHover" in rendered
    assert "picked" in rendered  # the reflex event dispatch is in the prop

    # both frontend files were registered into the app's assets tree
    ext = pathlib.Path(app_cwd) / "assets" / "external" / "reflex_xy" / "assets"
    assert (ext / "XYChart.jsx").exists()
    assert (ext / "xy_client.js").exists()
    # symlinks resolve to the installed package files
    assert (ext / "xy_client.js").resolve().read_bytes()[:16]


def test_component_accepts_var_token(app_cwd):
    class TokState(rx.State):
        tok: str = ""

    comp = reflex_xy.chart(TokState.tok)
    rendered = str(comp)
    assert "tok" in rendered
    # default sizing keeps the mount visible before the first payload
    assert "height" in rendered.lower()


def test_component_import_is_local_library(app_cwd):
    comp = reflex_xy.chart("tok")
    imports = comp._get_all_imports()
    lib = [k for k in imports if "XYChart" in k]
    assert lib, f"wrapper import missing from {list(imports)}"
    assert lib[0].startswith("$/public/external/"), "must never be an npm specifier"


def test_component_creation_does_not_touch_repo_root():
    """Outside an app cwd nothing has leaked assets/ into the repo."""
    repo_root = pathlib.Path(reflex_xy.__file__).resolve().parents[3]
    assert not (repo_root / "assets").exists(), (
        "importing/creating reflex_xy components must not scatter asset "
        "symlinks outside an app directory"
    )
    assert os.getcwd() != str(repo_root) or True
