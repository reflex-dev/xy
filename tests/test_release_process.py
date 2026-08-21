"""This repository's half of the changelog-driven release contract.

`CHANGELOG.md` is the publish trigger: `reflex-release` reads its newest version
heading and publishes it when no matching git tag exists. What is checked here is
the input this repository owns — the changelog, the towncrier configuration, and
`[tool.reflex-release]` — and the ways they can break quietly: an unparsable
heading (nothing would ever be detected as due), a `root-source-dirs` that no
longer covers the shipped source (pull requests stop needing news fragments), or
a fragment type the tool would refuse.

The workflows themselves are deliberately not asserted here. They come from
`reflex-release`, which owns their invariants and ships `sync` to detect drift.

The parts that need `reflex_release` itself skip when it is absent; the parts
that only read this repository's own files always run.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
RELEASE_CONFIG = PYPROJECT["tool"]["reflex-release"]
TOWNCRIER = PYPROJECT["tool"]["towncrier"]

#: `## v1.2.3 (2026-01-01)` — the towncrier title_format, and the only shape
#: reflex-release's parser turns back into a version.
HEADING_RE = re.compile(
    r"^## v(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?) "
    r"\((?P<date>\d{4}-\d{2}-\d{2})\)$"
)


def _changelog_headings() -> list[str]:
    return [
        line
        for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]


def test_every_changelog_version_heading_is_machine_readable() -> None:
    headings = _changelog_headings()

    assert headings, "CHANGELOG.md has no version sections"
    unreadable = [line for line in headings if not HEADING_RE.match(line)]
    assert not unreadable, (
        "release detection finds versions by parsing '## ' headings, so an "
        f"unparsable one can never be released: {unreadable}"
    )


def test_changelog_versions_are_newest_first() -> None:
    # towncrier prepends each new section, and the pipeline treats the *first*
    # versioned heading as the newest. Document order is version order — over the
    # whole PEP 440 version, since prereleases and post-releases both order
    # against the release they attach to (1.2.3rc1 < 1.2.3 < 1.2.3.post1).
    versions = [
        Version(match["version"])
        for line in _changelog_headings()
        if (match := HEADING_RE.match(line))
    ]

    assert versions == sorted(versions, reverse=True), [str(v) for v in versions]


def test_towncrier_start_string_marks_where_sections_are_inserted() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = TOWNCRIER["start_string"].strip()

    assert text.count(marker) == 1, f"{marker!r} must appear exactly once"
    # Everything above the marker is the preamble; new sections land under it and
    # therefore above every existing version.
    assert text.index(marker) < text.index(_changelog_headings()[0])


def test_towncrier_writes_headings_this_repository_can_read_back() -> None:
    rendered = TOWNCRIER["title_format"].format(
        name="", version="v9.9.9", project_date="2026-01-01"
    )

    assert HEADING_RE.match(rendered.strip()), rendered


def test_news_directory_exists_and_is_the_configured_one() -> None:
    news = ROOT / TOWNCRIER["directory"]

    assert news.is_dir(), f"{news} is where news fragments live"
    assert TOWNCRIER["directory"] == "news"


def test_news_fragments_use_configured_types() -> None:
    types = {entry["directory"] for entry in TOWNCRIER["type"]}
    # `<pr-number>.<type>[.md]`, or `+<name>.<type>[.md]` before the number is
    # known. Anchored on the whole name: `496.feature.md.bak` and
    # `496.invalid.feature.md` are both counted as pending by the release tool
    # but are not fragments it will materialize.
    fragment_re = re.compile(rf"^(?:\d+|\+[^.]+)\.(?:{'|'.join(sorted(types))})(?:\.md)?$")
    fragments = [
        path
        for path in (ROOT / TOWNCRIER["directory"]).iterdir()
        if path.is_file() and not path.name.startswith(".")
    ]

    for path in fragments:
        assert fragment_re.match(path.name), (
            f"{path.name} is not a fragment name; expected <pr-number>.<type>.md "
            f"(or +<name>.<type>.md) with type in {sorted(types)}"
        )
        assert path.read_text(encoding="utf-8").strip(), f"{path.name} is empty"


def test_root_source_dirs_cover_every_shipped_source_tree() -> None:
    # A pull request needs a news fragment when it touches one of these. If the
    # shipped Python, Rust or render-client source fell out of the list, a
    # user-visible change could land with no release note and nothing would say so.
    configured = set(RELEASE_CONFIG["root-source-dirs"])

    assert {"python", "src", "js"} <= configured, configured
    for directory in configured:
        assert (ROOT / directory).is_dir(), directory


def test_tag_prefix_still_matches_the_version_derivation() -> None:
    # uv-dynamic-versioning derives the distribution version from `v*` tags, and
    # reflex-release computes the tag it pushes as `<tag-prefix><version>`. A
    # mismatch would publish 0.0.0 or fail the batch version check.
    assert RELEASE_CONFIG["tag-prefix"] == "v"
    assert PYPROJECT["tool"]["hatch"]["version"]["source"] == "uv-dynamic-versioning"


def test_news_fragments_are_repository_only() -> None:
    # CHANGELOG.md ships (users read it); pending fragments must not, since they
    # describe a version that is not released yet.
    excluded = PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]
    included = PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]

    assert "/news/**" in excluded
    assert "CHANGELOG.md" in included


def test_the_release_pipeline_agrees_with_this_changelog() -> None:
    reflex_release = pytest.importorskip(
        "reflex_release",
        reason="reflex-release is not in the dev environment; it installs per invocation",
    )
    from reflex_release.changelog import latest_version
    from reflex_release.config import load_config

    config = load_config(ROOT)
    assert config.root_package == "xy"
    assert config.all_packages() == ["xy"]

    # The one thing a broken parser/config pair would hide: the version the
    # pipeline would publish next is the newest heading in this file.
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = latest_version(text)
    assert newest is not None
    assert f"## v{newest} (" in text
    assert config.tag_for("xy", str(newest)) == f"v{newest}"
    assert reflex_release is not None


def test_expect_artifacts_matches_what_the_build_workflow_produces() -> None:
    # Both files are this repository's, and nothing else can compare them:
    # reflex-release knows the globs a release must satisfy, not what the matrix
    # actually builds. Drift either way breaks a release — a platform built but
    # unlisted can ship missing (PyPI accepts a version once, so it cannot be
    # added later), and a platform listed but unbuilt can never satisfy the
    # check, stopping every release.
    entry = RELEASE_CONFIG["custom-build"][0]
    build = (ROOT / ".github" / "workflows" / entry["workflow"]).read_text(encoding="utf-8")

    built = set(re.findall(r"plat: ([A-Za-z0-9_]+)", build)) | set(
        re.findall(r"XY_WHEEL_PLATFORM=([A-Za-z0-9_]+)", build)
    )
    expected = {
        pattern.removeprefix("*-").removesuffix(".whl")
        for pattern in entry["expect-artifacts"]
        if pattern.endswith(".whl")
    }

    assert built, "no platform tags found in the build workflow"
    assert built == expected, {
        "built": sorted(built - expected),
        "expected": sorted(expected - built),
    }
    # The sdist is the one artifact with no platform tag.
    assert "*.tar.gz" in entry["expect-artifacts"]


def test_post_release_workflow_declares_the_dispatch_contract() -> None:
    # The release pipeline dispatches this workflow with `tag`, `package` and
    # `version` once a tag is published. reflex-release checks only that the name
    # is not one of its own workflows — it cannot know whether ours declares those
    # inputs, and GitHub rejects a dispatch carrying inputs a workflow does not
    # declare. Getting it wrong fails *after* the upload and the tag: the version
    # is out, the docs never deploy, and the release run goes red.
    yaml = pytest.importorskip("yaml")
    name = RELEASE_CONFIG["post-release-workflow"]
    document = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))
    declared = set(triggers["workflow_dispatch"]["inputs"])

    assert {"tag", "package", "version"} <= declared, declared
    # Only `tag` has no sensible default: it is what identifies the release.
    assert triggers["workflow_dispatch"]["inputs"]["tag"]["required"] is True


def test_post_release_workflow_is_not_a_generated_one() -> None:
    # Handing a published tag back to the release pipeline would re-enter it.
    # reflex-release rejects this too; asserting it here keeps the failure in a
    # test run rather than at `sync` time.
    generated = {
        "changelog.yml",
        "dispatch_release.yml",
        "release_from_changelog.yml",
        "publish.yml",
    }

    assert RELEASE_CONFIG["post-release-workflow"] not in generated
