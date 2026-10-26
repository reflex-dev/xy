"""Extended-profile dependency, driver, and completion-gate tests."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from scripts.pyplot_gallery.contract import CORPUS_ROOT
from scripts.pyplot_gallery.extended_drivers import (
    ScriptedInputDriver,
    drive_timer_until_close,
)
from scripts.pyplot_gallery.extended_environment import (
    EXAMPLE_REQUIREMENTS,
    PYTHON_PACKAGES,
    REQUIRED_COMMANDS,
    SYSTEM_PACKAGES,
    generated_spec,
    load_spec,
    validate_complete_report,
    validate_spec,
)
from scripts.pyplot_gallery.run_case import _pdf_page_count, run_case


def _capture_metadata(engine: str, index: int) -> dict[str, object]:
    return {
        "file": f"capture-{index:03d}.png",
        "backend": ("module://xy.backends.backend_xy" if engine == "xy" else "Agg"),
        "canvas_type": (
            "xy.backends.backend_xy.FigureCanvasXY"
            if engine == "xy"
            else "matplotlib.backends.backend_agg.FigureCanvasAgg"
        ),
        "fallback_used": False if engine == "xy" else None,
        "figure_facecolor_rgba": [1.0, 1.0, 1.0, 1.0],
        "background_rgb": [255, 255, 255],
    }


def _complete_report() -> dict[str, object]:
    cases = []
    for path, requirements in sorted(EXAMPLE_REQUIREMENTS.items()):
        capture_count = sum(
            output["count"]
            for output in requirements["expected_outputs"]
            if output["kind"] == "figure"
        )
        artifacts = [
            {
                "path": output["path"],
                "page_count": output["page_count"],
            }
            for output in requirements["expected_outputs"]
            if output["kind"] == "pdf"
        ]
        cases.append(
            {
                "path": path,
                "temporary_waivers": [],
                "engines": {
                    "matplotlib": {
                        "status": "passed",
                        "capture_count": capture_count,
                        "captures": [
                            _capture_metadata("matplotlib", index) for index in range(capture_count)
                        ],
                        "capture_errors": [],
                        "output_artifacts": artifacts,
                        "extended_driver": {
                            "driver_contract": {
                                "status": "passed",
                            }
                        },
                    },
                    "xy": {
                        "status": "passed",
                        "capture_count": capture_count,
                        "captures": [
                            _capture_metadata("xy", index) for index in range(capture_count)
                        ],
                        "capture_errors": [],
                        "fallback_used": False,
                        "output_artifacts": artifacts,
                        "extended_driver": {
                            "driver_contract": {
                                "status": "passed",
                            }
                        },
                    },
                },
                "comparison": {
                    "capture_parity": True,
                    "exact_dimension_parity": True,
                    "dimension_gate_passed": True,
                    "visual_gate_passed": True,
                    "semantic_gate_passed": True,
                    "behavior_gate_passed": True,
                },
            }
        )
    return {
        "summary": {
            "profile": "extended",
            "selected_examples": 12,
        },
        "examples": cases,
    }


def _assert_driver_contract(
    result: dict[str, object],
    configured_fields: set[str],
) -> None:
    contract = result["extended_driver"]["driver_contract"]
    assert contract["status"] == "passed"
    assert set(contract["configured_fields"]) == configured_fields
    assert set(contract["consumed_fields"]) == configured_fields
    assert contract["unconsumed_fields"] == []
    assert contract["errors"] == []


def test_checked_in_extended_environment_is_the_exact_generated_contract() -> None:
    spec = load_spec()
    assert validate_spec(spec) == []
    assert spec == generated_spec()
    assert len(spec["examples"]) == len(EXAMPLE_REQUIREMENTS) == 12


def test_extended_environment_dependencies_are_explicit_and_pinned() -> None:
    assert SYSTEM_PACKAGES == (
        "cm-super",
        "dvipng",
        "fonts-dejavu-core",
        "fonts-liberation",
        "fonts-urw-base35",
        "ghostscript",
        "gir1.2-gtk-3.0",
        "gir1.2-gtk-4.0",
        "librsvg2-common",
        "python3-cairo",
        "python3-gi",
        "python3-gi-cairo",
        "python3-venv",
        "texlive-fonts-recommended",
        "texlive-latex-base",
        "texlive-latex-extra",
        "texlive-latex-recommended",
        "xauth",
        "xvfb",
    )
    assert PYTHON_PACKAGES == (
        "colorspacious==1.1.2",
        "matplotlib==3.11.0",
    )
    assert REQUIRED_COMMANDS == (
        "dvipng",
        "dvips",
        "fc-match",
        "gs",
        "kpsewhich",
        "latex",
        "xvfb-run",
        "Xvfb",
    )


def test_every_extended_example_has_clean_argv_backends_driver_and_output() -> None:
    assert all(requirements["argv"] == [] for requirements in EXAMPLE_REQUIREMENTS.values())
    assert all(requirements["driver"] is not None for requirements in EXAMPLE_REQUIREMENTS.values())
    assert all(
        requirements["backends"]["matplotlib"] in {"Agg", "GTK3Agg", "GTK4Agg"}
        for requirements in EXAMPLE_REQUIREMENTS.values()
    )
    assert all(
        requirements["backends"]["xy"] == "module://xy.backends.backend_xy"
        for requirements in EXAMPLE_REQUIREMENTS.values()
    )
    assert all(requirements["expected_outputs"] for requirements in EXAMPLE_REQUIREMENTS.values())
    assert EXAMPLE_REQUIREMENTS["event_handling/ginput_manual_clabel_sgskip.py"]["driver"][
        "waitforbuttonpress"
    ] == [False, True, False]
    assert (
        EXAMPLE_REQUIREMENTS["misc/multiprocess_sgskip.py"]["driver"][
            "multiprocessing_start_method"
        ]
        == "fork"
    )
    assert (
        EXAMPLE_REQUIREMENTS["misc/multiprocess_sgskip.py"]["driver"]["checkpoint_line_count"] == 2
    )
    assert EXAMPLE_REQUIREMENTS["misc/multiprocess_sgskip.py"]["backends"] == {
        "matplotlib": "Agg",
        "xy": "module://xy.backends.backend_xy",
    }
    assert EXAMPLE_REQUIREMENTS["text_labels_and_annotations/font_table.py"]["argv"] == []
    assert EXAMPLE_REQUIREMENTS["user_interfaces/mplcvd.py"]["requirements"] == ["colorspacious"]
    assert EXAMPLE_REQUIREMENTS["user_interfaces/mplcvd.py"]["backends"] == {
        "matplotlib": "Agg",
        "xy": "module://xy.backends.backend_xy",
    }


def test_extended_completion_gate_accepts_only_full_12_case_report() -> None:
    spec = generated_spec()
    report = _complete_report()
    assert validate_complete_report(report, spec=spec) == []
    diagnostic_difference = copy.deepcopy(report)
    diagnostic_difference["examples"][0]["comparison"]["exact_dimension_parity"] = False
    assert validate_complete_report(diagnostic_difference, spec=spec) == []

    missing = copy.deepcopy(report)
    missing["examples"].pop()
    errors = validate_complete_report(missing, spec=spec)
    assert any("report paths differ" in error for error in errors)

    waived = copy.deepcopy(report)
    waived["examples"][0]["temporary_waivers"] = [{"id": "environment"}]
    errors = validate_complete_report(waived, spec=spec)
    assert any("temporary waivers remain" in error for error in errors)

    fallback = copy.deepcopy(report)
    fallback["examples"][0]["engines"]["xy"]["fallback_used"] = True
    errors = validate_complete_report(fallback, spec=spec)
    assert any("fallback state" in error for error in errors)

    incomplete = copy.deepcopy(report)
    incomplete["examples"][0]["engines"]["matplotlib"]["status"] = "error"
    errors = validate_complete_report(incomplete, spec=spec)
    assert any("matplotlib did not complete" in error for error in errors)

    missing_capture = copy.deepcopy(report)
    missing_capture["examples"][0]["engines"]["xy"]["capture_count"] = 0
    errors = validate_complete_report(missing_capture, spec=spec)
    assert any("xy capture count" in error for error in errors)

    missing_driver = copy.deepcopy(report)
    missing_driver["examples"][0]["engines"]["xy"]["extended_driver"] = {}
    errors = validate_complete_report(missing_driver, spec=spec)
    assert any("extended driver evidence" in error for error in errors)


def test_runner_uses_engine_specific_backend_and_clean_argv(tmp_path: Path) -> None:
    requirements = copy.deepcopy(
        EXAMPLE_REQUIREMENTS["event_handling/ginput_manual_clabel_sgskip.py"]
    )
    requirements["driver"] = {}
    mplconfig_dir = tmp_path / "mplconfig"
    for engine in ("matplotlib", "xy"):
        expected_backend = requirements["backends"][engine]
        source = tmp_path / f"{engine}_extended_case.py"
        source.write_text(
            "import os\n"
            "import sys\n"
            f"assert os.environ['MPLBACKEND'] == {expected_backend!r}\n"
            "assert len(sys.argv) == 1\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([0, 1], [1, 0])\n",
            encoding="utf-8",
        )
        result = run_case(
            engine=engine,
            source_path=source,
            output_dir=tmp_path / engine,
            timeout=30,
            python=Path(sys.executable),
            mplconfig_dir=mplconfig_dir,
            extended_requirements=requirements,
        )
        assert result["status"] == "passed", (tmp_path / engine / "stderr.txt").read_text()
        assert result["requested_matplotlib_backend"] == expected_backend
        assert result["extended_requirements"] == requirements
        _assert_driver_contract(result, set())


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_extended_motion_and_toolbar_actions_use_live_callbacks(
    tmp_path: Path,
    engine: str,
) -> None:
    source = tmp_path / "motion_toolbar.py"
    source.write_text(
        "import matplotlib.pyplot as plt\n"
        "class Label:\n"
        "    def __init__(self): self.text = 'move here'\n"
        "    def set_markup(self, value): self.text = value\n"
        "    def get_text(self): return self.text\n"
        "class Button:\n"
        "    def __init__(self): self.handlers = {}; self.next_id = 0\n"
        "    def get_label(self): return 'Click me'\n"
        "    def connect(self, signal, callback):\n"
        "        self.next_id += 1\n"
        "        self.handlers[self.next_id] = (signal, callback)\n"
        "        return self.next_id\n"
        "    def disconnect(self, handler_id): self.handlers.pop(handler_id)\n"
        "    def emit(self, signal):\n"
        "        for expected, callback in list(self.handlers.values()):\n"
        "            if expected == signal: callback(self)\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "label = Label()\n"
        "button = Button()\n"
        "clicked = []\n"
        "button.connect('clicked', lambda source: clicked.append(source))\n"
        "def update(event):\n"
        "    label.set_markup(f'x,y=({event.xdata}, {event.ydata})')\n"
        "fig.canvas.mpl_connect('motion_notify_event', update)\n"
        "plt.show()\n",
        encoding="utf-8",
    )
    requirements = {
        "argv": [],
        "backends": {"matplotlib": "Agg", "xy": "module://xy.backends.backend_xy"},
        "driver": {
            "motion": [[320, 240]],
            "toolbar_action": "Click me",
        },
        "expected_outputs": [{"kind": "figure", "count": 1}],
    }
    result = run_case(
        engine=engine,
        source_path=source,
        output_dir=tmp_path / engine,
        timeout=30,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        behavior_requirements=("interactive",),
        extended_requirements=requirements,
    )
    assert result["status"] == "passed", (tmp_path / engine / "stderr.txt").read_text()
    _assert_driver_contract(result, {"motion", "toolbar_action"})
    actions = result["extended_driver"]["actions"]["drivers"]
    assert actions["motion"]["probe_deliveries"] == 1
    assert actions["motion"]["events"][0]["inaxes"] is True
    assert actions["motion"]["final_label"].startswith("x,y=(")
    assert actions["toolbar_action"]["probe_deliveries"] == 1
    if engine == "xy":
        assert result["fallback_used"] is False


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_extended_color_filters_execute_in_the_active_renderer(
    tmp_path: Path,
    engine: str,
) -> None:
    source = tmp_path / "color_filters.py"
    source.write_text(
        "import matplotlib.pyplot as plt\n"
        "def identity_filter(image, dpi): return image, 0, 0\n"
        "def _set_menu_entry(toolbar, name):\n"
        "    toolbar.canvas.figure.set_agg_filter(identity_filter)\n"
        "    toolbar.canvas.draw_idle()\n"
        "fig, ax = plt.subplots()\n"
        "ax.fill_between([0, 1], [0, 1], color='tab:orange')\n"
        "plt.show()\n",
        encoding="utf-8",
    )
    requirements = {
        "argv": [],
        "backends": {"matplotlib": "Agg", "xy": "module://xy.backends.backend_xy"},
        "driver": {"color_filters": ["Greyscale", "Deuteranopia"]},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    }
    result = run_case(
        engine=engine,
        source_path=source,
        output_dir=tmp_path / engine,
        timeout=30,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        extended_requirements=requirements,
    )
    assert result["status"] == "passed", (tmp_path / engine / "stderr.txt").read_text()
    _assert_driver_contract(result, {"color_filters"})
    actions = result["extended_driver"]["actions"]["drivers"]["color_filters"]
    assert [action["name"] for action in actions["actions"]] == [
        "Greyscale",
        "Deuteranopia",
    ]
    assert all(action["filter_calls"] >= 1 for action in actions["actions"])
    assert actions["restored"] is True
    if engine == "xy":
        assert result["fallback_used"] is False


def test_unknown_extended_driver_field_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "unknown_driver.py"
    source.write_text(
        "import matplotlib.pyplot as plt\nplt.plot([0, 1], [1, 0])\n",
        encoding="utf-8",
    )
    requirements = {
        "argv": [],
        "backends": {"matplotlib": "Agg", "xy": "module://xy.backends.backend_xy"},
        "driver": {"mystery_action": True},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    }
    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=tmp_path / "result",
        timeout=30,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        extended_requirements=requirements,
    )
    assert result["status"] == "harness_error"
    assert result["exception_type"] == "ExtendedDriverContractError"
    contract = result["extended_driver"]["driver_contract"]
    assert contract["status"] == "failed"
    assert contract["unconsumed_fields"] == ["mystery_action"]
    assert any("unknown driver field" in error for error in contract["errors"])


def test_scripted_input_driver_consumes_the_manual_example_protocol() -> None:
    settings = EXAMPLE_REQUIREMENTS["event_handling/ginput_manual_clabel_sgskip.py"]["driver"]
    driver = ScriptedInputDriver(settings)
    assert driver.waitforbuttonpress() is False
    assert driver.ginput(3) == [(0.2, 0.2), (0.8, 0.2), (0.5, 0.8)]
    assert driver.waitforbuttonpress() is True

    received: dict[str, object] = {}

    def clabel(_contour: object, **kwargs: object) -> str:
        received.update(kwargs)
        return "labels"

    assert driver.clabel(clabel, object(), manual=True) == "labels"
    assert received["manual"] == [(0.0, 0.0)]
    assert driver.waitforbuttonpress() is False
    assert driver.ginput(2) == []
    assert driver.evidence()["remaining"] == {
        "waitforbuttonpress": 0,
        "ginput": 0,
        "manual_clabel": 0,
    }
    with pytest.raises(RuntimeError, match="exhausted"):
        driver.ginput(1)


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_exact_manual_input_example_passes_deterministically(
    tmp_path: Path,
    engine: str,
) -> None:
    relative = "event_handling/ginput_manual_clabel_sgskip.py"
    result = run_case(
        engine=engine,
        source_path=CORPUS_ROOT / "examples" / relative,
        output_dir=tmp_path / engine,
        timeout=120,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        behavior_requirements=("interactive",),
        extended_requirements=EXAMPLE_REQUIREMENTS[relative],
    )
    assert result["status"] == "passed", (tmp_path / engine / "stderr.txt").read_text()
    assert result["capture_count"] == 1
    assert result["capture_errors"] == []
    assert result["behavior"]["status"] == "passed"
    assert result["extended_driver"]["input"]["status"] == "passed"
    assert result["extended_driver"]["input"]["remaining"] == {
        "waitforbuttonpress": 0,
        "ginput": 0,
        "manual_clabel": 0,
    }
    if engine == "xy":
        assert result["fallback_used"] is False
    _assert_driver_contract(result, set(EXAMPLE_REQUIREMENTS[relative]["driver"]))


def test_timer_show_driver_services_callbacks_until_close() -> None:
    figures = [object()]
    checkpoints: list[int] = []

    class Timer:
        turns = 0

        def _on_timer(self) -> None:
            self.turns += 1
            if self.turns == 3:
                figures.clear()

    timer = Timer()
    result = drive_timer_until_close(
        timers=[timer],
        live_figures=lambda: list(figures),
        checkpoint=lambda: checkpoints.append(timer.turns),
        settings={
            "poll_interval_seconds": 0.0001,
            "checkpoint_after_seconds": 0,
        },
        timeout_seconds=1,
    )
    assert checkpoints == [1]
    assert result["status"] == "passed"
    assert result["turns"] == result["callback_dispatches"] == 3


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_exact_multiprocess_example_captures_the_child_process(
    tmp_path: Path,
    engine: str,
) -> None:
    relative = "misc/multiprocess_sgskip.py"
    result = run_case(
        engine=engine,
        source_path=CORPUS_ROOT / "examples" / relative,
        output_dir=tmp_path / engine,
        timeout=120,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        behavior_requirements=("interactive",),
        extended_requirements=EXAMPLE_REQUIREMENTS[relative],
    )
    assert result["status"] == "passed", (tmp_path / engine / "stderr.txt").read_text()
    assert result["returncode"] == 0
    assert result["capture_count"] == 1
    assert result["captures"][0]["process"] == "child"
    assert result["capture_errors"] == []
    assert result["behavior"]["status"] == "passed"
    assert result["child_processes"][0]["complete"] is True
    assert result["extended_driver"]["timer_show"]["status"] == "passed"
    assert result["extended_driver"]["timer_show"]["checkpoint_line_count"] == 2
    assert result["extended_driver"]["child_join"]["status"] == "passed"
    assert result["captures"][0]["semantic"]["axes"][0]["artist_families"]["line"] == 2
    if engine == "xy":
        assert result["fallback_used"] is False
    _assert_driver_contract(result, set(EXAMPLE_REQUIREMENTS[relative]["driver"]))


def test_pdf_page_count_uses_the_page_tree_not_pages_substrings() -> None:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Count 3 /Kids [2 0 R 3 0 R 4 0 R] /Type /Pages >> endobj\n"
        b"2 0 obj << /Type /Page /Parent 1 0 R >> endobj\n"
        b"3 0 obj << /Parent 1 0 R /Type /Page >> endobj\n"
        b"4 0 obj << /Type /Page /Parent 1 0 R >> endobj\n"
        b"%%EOF\n"
    )
    assert _pdf_page_count(pdf) == 3
    assert _pdf_page_count(b"/Type /Pages /Type /Page /Type /Page") == 2


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_runner_captures_pdf_pages_and_records_the_page_tree_count(
    tmp_path: Path,
    engine: str,
) -> None:
    source = tmp_path / "three_page_pdf.py"
    source.write_text(
        "from matplotlib.backends.backend_pdf import PdfPages\n"
        "import matplotlib.pyplot as plt\n"
        "with PdfPages('three.pdf') as pdf:\n"
        "    for index in range(3):\n"
        "        fig, ax = plt.subplots()\n"
        "        ax.set_title(str(index))\n"
        "        pdf.savefig(fig)\n"
        "        plt.close(fig)\n",
        encoding="utf-8",
    )
    requirements = {
        "argv": [],
        "backends": {"matplotlib": "Agg", "xy": "module://xy.backends.backend_xy"},
        "driver": {},
        "expected_outputs": [
            {"kind": "figure", "count": 3},
            {"kind": "pdf", "path": "three.pdf", "page_count": 3},
        ],
    }
    result = run_case(
        engine=engine,
        source_path=source,
        output_dir=tmp_path / engine,
        timeout=30,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        extended_requirements=requirements,
    )
    assert result["status"] == "passed", (tmp_path / engine / "stderr.txt").read_text()
    assert result["capture_count"] == 3
    assert [capture["stage"] for capture in result["captures"]] == [
        "pdf-page-1",
        "pdf-page-2",
        "pdf-page-3",
    ]
    assert [capture["pdf_page_index"] for capture in result["captures"]] == [0, 1, 2]
    assert result["capture_errors"] == []
    if engine == "xy":
        assert result["fallback_used"] is False
    _assert_driver_contract(result, set())
    assert result["output_artifacts"] == [
        {
            "kind": "pdf",
            "path": "three.pdf",
            "byte_count": result["output_artifacts"][0]["byte_count"],
            "sha256": result["output_artifacts"][0]["sha256"],
            "page_count": 3,
        }
    ]


def test_toolmanager_exact_source_passes_with_xy_manager(tmp_path: Path) -> None:
    relative = "user_interfaces/toolmanager_sgskip.py"
    requirements = EXAMPLE_REQUIREMENTS[relative]
    result = run_case(
        engine="xy",
        source_path=CORPUS_ROOT / "examples" / relative,
        output_dir=tmp_path / "xy",
        timeout=30,
        python=Path(sys.executable),
        mplconfig_dir=tmp_path / "mplconfig",
        behavior_requirements=("interactive",),
        extended_requirements=requirements,
    )
    assert result["status"] == "passed", (tmp_path / "xy" / "stderr.txt").read_text()
    assert result["requested_matplotlib_backend"] == "module://xy.backends.backend_xy"
    assert result["capture_count"] == 1
    assert result["fallback_used"] is False
    assert result["capture_errors"] == []
    capture = result["captures"][0]
    assert capture["backend"] == "module://xy.backends.backend_xy"
    assert capture["canvas_type"] == "xy.backends.backend_xy.FigureCanvasXY"
    assert capture["fallback_used"] is False
    assert capture["figure_facecolor_rgba"] == [1.0, 1.0, 1.0, 1.0]
    assert capture["background_rgb"] == [255, 255, 255]
    assert result["behavior"]["status"] == "passed"
    assert result["behavior"]["canvases"][0]["canvas_type"] == (
        "xy.backends.backend_xy.FigureCanvasXY"
    )
    _assert_driver_contract(result, {"tool_triggers"})
    actions = result["extended_driver"]["actions"]["drivers"]["tool_triggers"]["actions"]
    assert [action["name"] for action in actions] == ["List", "Show", "Show"]
    assert [action["toggled"] for action in actions[1:]] == [False, True]
