"""Contract, import-rewrite, and real-script runner tests."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

from scripts.pyplot_gallery import HARNESS_VERSION, extended_environment
from scripts.pyplot_gallery import contract as gallery_contract
from scripts.pyplot_gallery.contract import (
    BASELINE_PATH,
    CORPUS_ROOT,
    MANIFEST_PATH,
    _accepted_report_case,
    _ast_dump_show_empty_fallback,
    _classify_source,
    _normalized_script_ast,
    _stable_ast_dump,
    promote_reports,
    verify_contract,
    verify_monotonic_baseline,
)
from scripts.pyplot_gallery.provenance import current_python_interpreter
from scripts.pyplot_gallery.rewrite import PyplotRewriteError, rewrite_pyplot_imports
from scripts.pyplot_gallery.run_case import run_case
from scripts.pyplot_gallery.run_gallery import _resumable_result

AUDIT_COMMIT = "a" * 40
PYTHON_INTERPRETER = current_python_interpreter()


def test_stable_ast_dump_includes_empty_fields_and_canonical_type_params() -> None:
    tree = ast.parse("def function():\n    pass\n\nclass Example:\n    pass\n")

    dumped = _stable_ast_dump(tree)

    assert "posonlyargs=[]" in dumped
    assert "kw_defaults=[]" in dumped
    assert "decorator_list=[]" in dumped
    assert dumped.count("type_params=[]") == 2
    assert dumped.endswith("type_ignores=[])")
    assert _ast_dump_show_empty_fallback(tree) == dumped


def test_stable_ast_dump_ignores_redundant_empty_fstring_literals() -> None:
    tree = ast.parse('text = f"{value:>{width}}"\n')
    parser_variant = copy.deepcopy(tree)
    format_spec = next(
        node.format_spec
        for node in ast.walk(parser_variant)
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None
    )
    assert isinstance(format_spec, ast.JoinedStr)
    format_spec.values.append(ast.Constant(value=""))

    assert _stable_ast_dump(parser_variant) == _stable_ast_dump(tree)
    assert isinstance(format_spec.values[-1], ast.Constant)
    assert format_spec.values[-1].value == ""


def test_normalized_script_ast_matches_equivalent_notebook_code() -> None:
    script = '"""Gallery prose."""\nvalue = call()\n'
    notebook_code = "value = call()\n"

    assert _normalized_script_ast(script, "example.py") == _stable_ast_dump(
        ast.parse(notebook_code, filename="example.ipynb")
    )


def test_vendored_gallery_contract_is_complete_and_immutable() -> None:
    assert verify_contract() == []
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["source_count"] == manifest["notebook_count"] == 507
    assert manifest["pyplot_eligible_count"] == 485
    assert manifest["profile_counts"] == {
        "extended": 13,
        "non_pyplot": 22,
        "standard": 472,
    }
    assert all(example["notebook_ast_matches"] for example in manifest["examples"])


def test_pyplot_pause_loop_is_classified_as_animation() -> None:
    render_class, behavior = _classify_source(
        ast.parse("import matplotlib.pyplot as plt\nfor _ in range(3):\n    plt.pause(0.1)\n")
    )

    assert render_class == "text_thin_line"
    assert behavior == ["interactive", "animation"]


def test_browser_behavior_classification_covers_semantic_interactions() -> None:
    _render_class, draggable = _classify_source(ast.parse("annotation.draggable()\n"))
    assert draggable == ["interactive"]

    _render_class, coordinates = _classify_source(
        ast.parse("axes.format_coord = lambda x, y: f'{x}, {y}'\n")
    )
    assert coordinates == ["interactive", "coordinates"]

    _render_class, navigation = _classify_source(
        ast.parse("import matplotlib.pyplot as plt\n"),
        "showcase/pan_zoom_overlap.py",
    )
    assert navigation == ["interactive", "navigation"]


def test_resume_rejects_reports_from_before_the_current_visual_gate(tmp_path: Path) -> None:
    entry = {"path": "category/example.py", "sha256": "source-hash", "behavior": []}
    artifact_dir = tmp_path / "runs" / "category" / "example" / "xy"
    artifact_dir.mkdir(parents=True)
    result = {
        "engine": "xy",
        "harness_version": HARNESS_VERSION - 1,
        "python_interpreter": PYTHON_INTERPRETER,
        "source_sha256": entry["sha256"],
        "status": "passed",
        "requested_pyplot_mode": "compat",
        "behavior_requirements": [],
        "extended_requirements": None,
        "requested_matplotlib_backend": "Agg",
        "captures": [],
    }
    (artifact_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")

    assert (
        _resumable_result(
            output_root=tmp_path,
            entry=entry,
            engine="xy",
            python_interpreter=PYTHON_INTERPRETER,
        )
        is None
    )

    result["harness_version"] = HARNESS_VERSION
    (artifact_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    assert (
        _resumable_result(
            output_root=tmp_path,
            entry=entry,
            engine="xy",
            python_interpreter=PYTHON_INTERPRETER,
        )
        == result
    )
    assert (
        _resumable_result(
            output_root=tmp_path,
            entry=entry,
            engine="xy",
            python_interpreter={"implementation": "cpython", "version": "0.0.0"},
        )
        is None
    )


def test_baseline_records_all_four_material_formatting_issues() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    issues = {
        example["issue"]["number"]
        for example in manifest["examples"]
        if example["issue"] is not None
    }
    assert issues == {354, 409, 410, 411}


def test_import_rewrite_changes_only_the_direct_import_ast() -> None:
    source = '''\
"""import matplotlib.pyplot as plt in a string."""
# import matplotlib.pyplot as plt in a comment.
import matplotlib.pyplot as plt
from matplotlib import colors

plt.plot([1, 2])
'''
    result = rewrite_pyplot_imports(source, filename="example.py")
    assert "import xy.pyplot as plt" in result.source
    assert '"""import matplotlib.pyplot as plt in a string."""' in result.source
    assert "# import matplotlib.pyplot as plt in a comment." in result.source
    assert "from matplotlib import colors" in result.source
    assert result.import_count == 1
    assert result.original_ast != result.rewritten_ast


def test_from_import_rewrite_preserves_binding() -> None:
    source = "from matplotlib import pyplot as plt\nplt.plot([1])\n"
    result = rewrite_pyplot_imports(source)
    assert result.source == "from xy import pyplot as plt\nplt.plot([1])\n"


def test_import_rewrite_preserves_every_non_target_character() -> None:
    source = (
        "# π and CRLF stay byte-for-byte stable\r\n"
        "if True:\r\n"
        "\timport matplotlib.pyplot as plt  # exact spacing\r\n"
        "\tlabel = f'{value:>{width}}'\r\n"
    )
    target_start = source.index("matplotlib")
    expected = source[:target_start] + "xy" + source[target_start + len("matplotlib") :]

    result = rewrite_pyplot_imports(source)

    assert result.source == expected


def test_version_sensitive_gallery_rewrites_have_portable_hashes() -> None:
    expected = {
        "statistics/confidence_ellipse.py": (
            "57669f2fe7b56b11661f6e7819407cc2f21d294953bb26755a23e3e0eee3f1d4"
        ),
        "text_labels_and_annotations/angle_annotation.py": (
            "4c791aaa6c21e12bc2e89e2d5abc85c3554ca615e9fdb50f77359250a6c83468"
        ),
        "misc/custom_projection.py": (
            "d608d99a389ec6aa3487bc96c3cf892350f435ec246534d0663d99e2d49b73ab"
        ),
        "misc/packed_bubbles.py": (
            "7a1db0eecd2d7ddbfaaabcc2ea1b1b7cbb9234479184a8af64e9b14f75b6d9e6"
        ),
        "user_interfaces/svg_histogram_sgskip.py": (
            "713a856b1d60cd1ad3f36ef94fbe00bce519165d8098a016e9c8bf318dbccebe"
        ),
        "images_contours_and_fields/plot_streamplot.py": (
            "d5d3946742793da9c8133b16aac238ade56fb313937b59364aa6e1b867397e85"
        ),
    }

    for relative, expected_sha256 in expected.items():
        source = (CORPUS_ROOT / "examples" / relative).read_bytes().decode("utf-8")
        rewritten = rewrite_pyplot_imports(source, filename=relative)
        assert hashlib.sha256(rewritten.source.encode("utf-8")).hexdigest() == expected_sha256


def test_import_rewrite_fails_closed_for_ambiguous_forms() -> None:
    for source in (
        "from matplotlib import pyplot as plt, colors\n",
        "import matplotlib.pyplot\n",
        "text = 'import matplotlib.pyplot as plt'\n",
    ):
        try:
            rewrite_pyplot_imports(source)
        except PyplotRewriteError:
            pass
        else:
            raise AssertionError(f"ambiguous source unexpectedly rewrote: {source!r}")


def test_baseline_ratchet_allows_only_forward_progress() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert verify_monotonic_baseline(baseline, copy.deepcopy(baseline)) == []

    passing_path = next(
        path
        for path, entry in baseline["examples"].items()
        if entry["xy"]["status"] == "passed"
        and entry["capture_parity"]
        and entry["dimension_parity"]
    )
    regressed = copy.deepcopy(baseline)
    regressed["examples"][passing_path]["xy"]["status"] = "error"
    regressed["examples"][passing_path]["capture_parity"] = False
    regressed["examples"][passing_path]["dimension_parity"] = False
    regressed["examples"][passing_path]["dimension_gate_passed"] = False
    errors = verify_monotonic_baseline(baseline, regressed)
    assert any("execution regressed" in error for error in errors)
    assert any("capture parity regressed" in error for error in errors)
    assert any("dimension acceptance gate regressed" in error for error in errors)

    added_waiver = copy.deepcopy(baseline)
    added_waiver["examples"][passing_path]["temporary_waivers"].append(
        {"id": "new-excuse", "temporary": True, "reason": "must be rejected"}
    )
    assert any(
        "added temporary waivers" in error
        for error in verify_monotonic_baseline(baseline, added_waiver)
    )

    previous_with_waiver = copy.deepcopy(baseline)
    previous_with_waiver["examples"][passing_path]["temporary_waivers"].append(
        {"id": "resolved-debt", "temporary": True, "reason": "old temporary failure"}
    )
    improved = copy.deepcopy(previous_with_waiver)
    improved["examples"][passing_path]["temporary_waivers"].clear()
    assert verify_monotonic_baseline(previous_with_waiver, improved) == []


def _promotion_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "contract"
    root.mkdir()
    examples = root / "examples"
    examples.mkdir()
    source = "import matplotlib.pyplot as plt\nplt.plot([0, 1])\n"
    source_bytes = source.encode()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    rewritten = rewrite_pyplot_imports(source, filename="plot.py")
    transformed_sha256 = hashlib.sha256(rewritten.source.encode()).hexdigest()
    (examples / "plot.py").write_bytes(source_bytes)
    (examples / "backend.py").write_text("print('backend')\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "matplotlib_version": "3.11.0",
        "source_count": 2,
        "pyplot_eligible_count": 1,
        "profile_counts": {"standard": 1, "extended": 0, "non_pyplot": 1},
        "gallery_adapters": {},
        "examples": [
            {
                "path": "plot.py",
                "profile": "standard",
                "render_class": "text_thin_line",
                "behavior": ["static"],
                "pyplot_eligible": True,
                "pyplot_imports": [{"alias": "plt", "kind": "import", "line": 1}],
                "sha256": source_sha256,
                "temporary_waivers": [
                    {"id": "xy-execution", "temporary": True, "reason": "old failure"}
                ],
            },
            {
                "path": "backend.py",
                "pyplot_eligible": False,
                "temporary_waivers": [],
            },
        ],
    }
    baseline = {
        "schema_version": 1,
        "examples": {
            "plot.py": {
                "reference": {"status": "passed", "capture_count": 1, "duration_seconds": 1},
                "xy": {"status": "error", "capture_count": 0, "duration_seconds": 1},
                "capture_parity": False,
                "dimension_parity": False,
                "visual_gate_passed": None,
                "temporary_waivers": manifest["examples"][0]["temporary_waivers"],
            },
            "backend.py": {
                "reference": {"status": "not_applicable"},
                "xy": {"status": "not_applicable"},
                "capture_parity": False,
                "dimension_parity": False,
                "visual_gate_passed": None,
                "temporary_waivers": [],
            },
        },
        "summary": {},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    extended_spec = {"examples": []}
    (root / "extended-environment.json").write_text(
        json.dumps(extended_spec),
        encoding="utf-8",
    )
    manifest_sha256 = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    extended_spec_sha256 = hashlib.sha256(
        (root / "extended-environment.json").read_bytes()
    ).hexdigest()
    report = {
        "schema_version": 2,
        "harness_version": HARNESS_VERSION,
        "implementation_commit": AUDIT_COMMIT,
        "implementation_dirty": False,
        "python_interpreter": PYTHON_INTERPRETER,
        "manifest_sha256": manifest_sha256,
        "extended_spec_sha256": extended_spec_sha256,
        "environment_profile": "standard",
        "matplotlib_version": "3.11.0",
        "summary": {"profile": "standard", "selected_examples": 1},
        "examples": [
            {
                "path": "plot.py",
                "profile": "standard",
                "render_class": "text_thin_line",
                "behavior": ["static"],
                "temporary_waivers": [],
                "extended_environment": None,
                "engines": {
                    "matplotlib": {
                        "schema_version": 2,
                        "harness_version": HARNESS_VERSION,
                        "engine": "matplotlib",
                        "source_sha256": source_sha256,
                        "transformed_sha256": source_sha256,
                        "rewrite_count": 0,
                        "ast_rewrite_verified": True,
                        "python_interpreter": PYTHON_INTERPRETER,
                        "requested_pyplot_mode": None,
                        "resolved_pyplot_mode": None,
                        "requested_matplotlib_backend": "Agg",
                        "behavior_requirements": ["static"],
                        "extended_requirements": None,
                        "status": "passed",
                        "capture_count": 1,
                        "captures": [
                            {
                                "file": "reference.png",
                                "backend": "Agg",
                                "canvas_type": ("matplotlib.backends.backend_agg.FigureCanvasAgg"),
                                "fallback_used": None,
                                "figure_facecolor_rgba": [1.0, 1.0, 1.0, 1.0],
                                "background_rgb": [255, 255, 255],
                            }
                        ],
                        "capture_errors": [],
                        "behavior": {
                            "required": [],
                            "status": "not_required",
                            "gallery_adapters": [],
                        },
                        "wall_duration_seconds": 0.5,
                    },
                    "xy": {
                        "schema_version": 2,
                        "harness_version": HARNESS_VERSION,
                        "engine": "xy",
                        "source_sha256": source_sha256,
                        "transformed_sha256": transformed_sha256,
                        "rewrite_count": 1,
                        "ast_rewrite_verified": True,
                        "python_interpreter": PYTHON_INTERPRETER,
                        "requested_pyplot_mode": "compat",
                        "resolved_pyplot_mode": "compat",
                        "requested_matplotlib_backend": "Agg",
                        "behavior_requirements": ["static"],
                        "extended_requirements": None,
                        "status": "passed",
                        "capture_count": 1,
                        "captures": [
                            {
                                "file": "xy.png",
                                "backend": "module://xy.backends.backend_xy",
                                "canvas_type": "xy.backends.backend_xy.FigureCanvasXY",
                                "fallback_used": False,
                                "figure_facecolor_rgba": [1.0, 1.0, 1.0, 1.0],
                                "background_rgb": [255, 255, 255],
                            }
                        ],
                        "capture_errors": [],
                        "fallback_used": False,
                        "behavior": {
                            "required": [],
                            "status": "not_required",
                            "gallery_adapters": [],
                        },
                        "wall_duration_seconds": 0.75,
                    },
                },
                "comparison": {
                    "capture_parity": True,
                    "dimension_gate_passed": True,
                    "exact_dimension_parity": False,
                    "visual_gate_passed": True,
                    "semantic_gate_passed": True,
                    "behavior_gate_passed": True,
                    "figure_pairs": [
                        {
                            "dimension_gate": {"decision": "pass", "reasons": []},
                            "metrics": {"normalized_rgb_mae": 0.0},
                            "semantic_differences": [],
                            "visual_gate": {"decision": "pass", "reasons": []},
                        }
                    ],
                },
                "ratchet_errors": [],
            }
        ],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return root, report_path


def test_complete_report_promotion_removes_waivers_and_records_tolerant_dimensions(
    tmp_path: Path,
) -> None:
    root, report_path = _promotion_fixture(tmp_path)
    manifest, baseline = promote_reports(
        [report_path],
        audit_commit=AUDIT_COMMIT,
        root=root,
        verify_repository=False,
    )

    assert baseline["schema_version"] == 3
    assert baseline["audit_commit"] == AUDIT_COMMIT
    assert baseline["harness_version"] == HARNESS_VERSION
    assert baseline["summary"]["acceptance_complete"] is True
    assert baseline["summary"]["accepted_examples"] == 1
    assert baseline["summary"]["dimension_parity_passed"] == 1
    assert baseline["summary"]["exact_dimension_parity_passed"] == 0
    assert baseline["summary"]["temporary_waiver_count"] == 0
    assert baseline["examples"]["plot.py"]["dimension_gate_passed"] is True
    assert baseline["examples"]["plot.py"]["exact_dimension_parity"] is False
    assert baseline["examples"]["plot.py"]["temporary_waivers"] == []
    assert baseline["acceptance_reports"] == [
        {
            "profile": "standard",
            "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "harness_version": HARNESS_VERSION,
            "python_interpreter": PYTHON_INTERPRETER,
        }
    ]
    assert manifest["examples"][0]["temporary_waivers"] == []


def test_promotion_records_emitted_manifest_hash_and_immediately_verifies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "contract"
    shutil.copytree(CORPUS_ROOT, root)
    manifest_path = root / "manifest.json"
    extended_spec_path = root / "extended-environment.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    examples = manifest.pop("examples")
    deliberately_noncanonical = {"examples": examples, **manifest}
    manifest_path.write_text(
        json.dumps(deliberately_noncanonical, indent=2) + "\n",
        encoding="utf-8",
    )
    report_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    extended_spec_sha256 = hashlib.sha256(extended_spec_path.read_bytes()).hexdigest()

    # This regression is about the promotion write/provenance boundary.  The
    # ordinary fixture tests above exercise detailed report acceptance; use
    # compact accepted cases here so the real 507-source contract can be
    # promoted and then passed through the complete verifier.
    monkeypatch.setattr(gallery_contract, "_case_provenance_errors", lambda **_kwargs: [])
    monkeypatch.setattr(
        gallery_contract,
        "_accepted_report_case",
        lambda _case, *, expected_behavior=(): [],
    )
    monkeypatch.setattr(
        extended_environment,
        "validate_complete_report",
        lambda _report, *, spec: [],
    )

    report_paths: list[Path] = []
    for profile in ("standard", "extended"):
        cases = []
        for entry in deliberately_noncanonical["examples"]:
            if not entry["pyplot_eligible"] or entry["profile"] != profile:
                continue
            cases.append(
                {
                    "path": entry["path"],
                    "engines": {
                        engine: {
                            "status": "passed",
                            "capture_count": 1,
                            "wall_duration_seconds": 0.1,
                        }
                        for engine in ("matplotlib", "xy")
                    },
                    "comparison": {
                        "exact_dimension_parity": True,
                        "figure_pairs": [{"visual_gate": {"decision": "pass"}}],
                    },
                }
            )
        report = {
            "schema_version": 2,
            "harness_version": HARNESS_VERSION,
            "implementation_commit": AUDIT_COMMIT,
            "implementation_dirty": False,
            "python_interpreter": PYTHON_INTERPRETER,
            "manifest_sha256": report_manifest_sha256,
            "extended_spec_sha256": extended_spec_sha256,
            "environment_profile": profile,
            "matplotlib_version": deliberately_noncanonical["matplotlib_version"],
            "summary": {"profile": profile},
            "examples": cases,
        }
        report_path = tmp_path / f"{profile}-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        report_paths.append(report_path)

    _manifest, baseline = promote_reports(
        report_paths,
        audit_commit=AUDIT_COMMIT,
        root=root,
        verify_repository=False,
    )

    emitted_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert emitted_manifest_sha256 != report_manifest_sha256
    assert baseline["manifest_sha256"] == emitted_manifest_sha256
    assert all(
        record["python_interpreter"] == PYTHON_INTERPRETER
        for record in baseline["acceptance_reports"]
    )
    assert verify_contract(root) == []


def test_report_promotion_is_fail_closed(tmp_path: Path) -> None:
    root, report_path = _promotion_fixture(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["examples"][0]["comparison"]["dimension_gate_passed"] = False
    report_path.write_text(json.dumps(report), encoding="utf-8")
    before_manifest = (root / "manifest.json").read_bytes()
    before_baseline = (root / "baseline.json").read_bytes()

    try:
        promote_reports(
            [report_path],
            audit_commit=AUDIT_COMMIT,
            root=root,
            verify_repository=False,
        )
    except ValueError as exc:
        assert "dimension_gate_passed did not pass" in str(exc)
    else:
        raise AssertionError("a failed acceptance report was promoted")

    assert (root / "manifest.json").read_bytes() == before_manifest
    assert (root / "baseline.json").read_bytes() == before_baseline


def test_report_promotion_rejects_stale_or_fabricated_provenance(tmp_path: Path) -> None:
    root, report_path = _promotion_fixture(tmp_path)
    original = json.loads(report_path.read_text(encoding="utf-8"))
    mutations = [
        (
            lambda report: report.__setitem__("harness_version", HARNESS_VERSION - 1),
            "harness_version",
        ),
        (
            lambda report: report.__setitem__("implementation_dirty", True),
            "implementation_dirty",
        ),
        (
            lambda report: report.__setitem__(
                "python_interpreter", {"implementation": "cpython", "version": "3.12"}
            ),
            "python_interpreter",
        ),
        (
            lambda report: report["examples"][0]["engines"]["xy"].__setitem__(
                "source_sha256", "0" * 64
            ),
            "source_sha256",
        ),
        (
            lambda report: report["examples"][0]["engines"]["xy"].__setitem__(
                "python_interpreter",
                {"implementation": "cpython", "version": "0.0.0"},
            ),
            "python_interpreter",
        ),
        (
            lambda report: report["examples"][0]["engines"]["xy"].__setitem__(
                "resolved_pyplot_mode", "native"
            ),
            "resolved_pyplot_mode",
        ),
        (
            lambda report: report["examples"][0]["engines"]["matplotlib"]["behavior"].__setitem__(
                "gallery_adapters", [{"id": "unreviewed-adapter"}]
            ),
            "gallery adapters",
        ),
    ]
    for mutate, expected_message in mutations:
        report = copy.deepcopy(original)
        mutate(report)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        try:
            promote_reports(
                [report_path],
                audit_commit=AUDIT_COMMIT,
                root=root,
                verify_repository=False,
            )
        except ValueError as exc:
            assert expected_message in str(exc)
        else:
            raise AssertionError(f"promotion accepted invalid {expected_message}")


def test_report_acceptance_rejects_inconsistent_capture_and_pair_details(
    tmp_path: Path,
) -> None:
    _root, report_path = _promotion_fixture(tmp_path)
    case = json.loads(report_path.read_text(encoding="utf-8"))["examples"][0]

    wrong_count = copy.deepcopy(case)
    wrong_count["engines"]["xy"]["capture_count"] = 2
    assert any("capture_count" in error for error in _accepted_report_case(wrong_count))

    unequal_counts = copy.deepcopy(case)
    unequal_counts["engines"]["xy"]["captures"].append(
        copy.deepcopy(unequal_counts["engines"]["xy"]["captures"][0])
    )
    unequal_counts["engines"]["xy"]["capture_count"] = 2
    assert any("capture counts differ" in error for error in _accepted_report_case(unequal_counts))

    no_pairs = copy.deepcopy(case)
    no_pairs["comparison"]["figure_pairs"] = []
    assert any("figure_pairs" in error for error in _accepted_report_case(no_pairs))

    semantic_difference = copy.deepcopy(case)
    semantic_difference["comparison"]["figure_pairs"][0]["semantic_differences"] = ["zlim"]
    assert any(
        "semantic differences" in error for error in _accepted_report_case(semantic_difference)
    )

    missing_behavior = copy.deepcopy(case)
    assert any(
        "behavior evidence did not pass" in error
        for error in _accepted_report_case(
            missing_behavior,
            expected_behavior=["interactive"],
        )
    )


def test_report_acceptance_rejects_capture_provenance_failures(tmp_path: Path) -> None:
    _root, report_path = _promotion_fixture(tmp_path)
    case = json.loads(report_path.read_text(encoding="utf-8"))["examples"][0]

    capture_error = copy.deepcopy(case)
    capture_error["engines"]["xy"]["capture_errors"] = ["capture failed"]
    assert any("xy has capture errors" in error for error in _accepted_report_case(capture_error))

    missing_fallback = copy.deepcopy(case)
    del missing_fallback["engines"]["xy"]["captures"][0]["fallback_used"]
    assert any(
        "fallback metadata is missing" in error for error in _accepted_report_case(missing_fallback)
    )

    wrong_canvas = copy.deepcopy(case)
    wrong_canvas["engines"]["xy"]["captures"][0]["canvas_type"] = (
        "matplotlib.backends.backend_agg.FigureCanvasAgg"
    )
    assert any(
        "did not use FigureCanvasXY" in error for error in _accepted_report_case(wrong_canvas)
    )

    missing_backend = copy.deepcopy(case)
    del missing_backend["engines"]["matplotlib"]["captures"][0]["backend"]
    assert any(
        "backend identity is missing" in error for error in _accepted_report_case(missing_backend)
    )


def test_runner_uses_a_real_clean_script_and_supports_spawn(
    tmp_path: Path,
) -> None:
    source = tmp_path / "spawn_case.py"
    source.write_text(
        """\
import multiprocessing as mp
from pathlib import Path
import sys

import matplotlib.pyplot as plt


class Worker:
    def __call__(self, queue):
        queue.put("spawned")


if __name__ == "__main__":
    assert Path(__file__).name == "spawn_case.py"
    assert len(sys.argv) == 1
    context = mp.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=Worker(), args=(queue,))
    process.start()
    process.join(10)
    assert process.exitcode == 0
    assert queue.get(timeout=2) == "spawned"
    plt.plot([0, 1], [0, 1])
    plt.show()
""",
        encoding="utf-8",
    )
    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=tmp_path / "output",
        timeout=30,
        python=Path(sys.executable),
    )
    assert result["status"] == "passed", (tmp_path / "output" / "stderr.txt").read_text()
    assert result["python_interpreter"] == PYTHON_INTERPRETER
    assert result["capture_count"] == 1
    assert result["captures"][0]["dimensions"] == [640, 480]
    assert (tmp_path / "output" / "_execution" / "spawn_case.py").is_file()


def test_runner_reports_child_exit_when_runtime_cannot_write_result(tmp_path: Path) -> None:
    source = tmp_path / "abrupt_exit.py"
    source.write_text("import os\nos._exit(3)\n", encoding="utf-8")
    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=tmp_path / "output",
        timeout=10,
        python=Path(sys.executable),
    )
    assert result["status"] == "error"
    assert result["exception_type"] == "MissingResult"
    assert result["returncode"] == 3


def test_runner_captures_figures_without_explicit_show(tmp_path: Path) -> None:
    source = tmp_path / "implicit_final_capture.py"
    source.write_text(
        """\
import matplotlib.pyplot as plt

plt.plot([0, 1], [1, 0])
""",
        encoding="utf-8",
    )
    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=tmp_path / "output",
        timeout=20,
        python=Path(sys.executable),
    )
    assert result["status"] == "passed", (tmp_path / "output" / "stderr.txt").read_text()
    assert result["show_count"] == 0
    assert result["capture_count"] == 1
    capture = result["captures"][0]
    assert capture["stage"] == "final"
    assert capture["backend"].lower() == "agg"
    assert capture["canvas_type"] == "matplotlib.backends.backend_agg.FigureCanvasAgg"
    assert capture["fallback_used"] is None
    assert capture["figure_facecolor_rgba"] == [1.0, 1.0, 1.0, 1.0]
    assert capture["background_rgb"] == [255, 255, 255]


def test_gallery_sibling_cannot_shadow_stdlib_during_startup(tmp_path: Path) -> None:
    source_dir = tmp_path / "shapes_and_collections"
    source_dir.mkdir()
    (source_dir / "collections.py").write_text(
        "raise RuntimeError('gallery collections shadowed stdlib')\n",
        encoding="utf-8",
    )
    (source_dir / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    source = source_dir / "plot_case.py"
    source.write_text(
        """\
import helper
import matplotlib.pyplot as plt

assert helper.VALUE == 42
plt.plot([0, 1], [1, 0])
plt.show()
""",
        encoding="utf-8",
    )
    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=tmp_path / "output",
        timeout=20,
        python=Path(sys.executable),
    )
    assert result["status"] == "passed", (tmp_path / "output" / "stderr.txt").read_text()
    assert result["capture_count"] == 1


def test_actual_collections_example_cannot_shadow_stdlib(tmp_path: Path) -> None:
    source = CORPUS_ROOT / "examples" / "shapes_and_collections" / "collections.py"
    mplconfig_dir = tmp_path / "mplconfig"
    for engine in ("matplotlib", "xy"):
        result = run_case(
            engine=engine,
            source_path=source,
            output_dir=tmp_path / engine,
            timeout=30,
            python=Path(sys.executable),
            mplconfig_dir=mplconfig_dir,
        )
        assert result.get("exception_type") != "MissingResult"
        assert "partially initialized module 'collections'" not in (
            tmp_path / engine / "stderr.txt"
        ).read_text(encoding="utf-8")
    assert json.loads((tmp_path / "matplotlib" / "result.json").read_text())["status"] == "passed"


def test_corpus_root_is_outside_pytest_collection() -> None:
    # The sources are executable third-party fixtures, not tests to import in
    # the main process. Keeping them outside tests/ also preserves their bytes.
    assert CORPUS_ROOT.parent.name == "gallery"
