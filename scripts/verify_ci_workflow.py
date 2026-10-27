#!/usr/bin/env python3
"""Verify workflow invariants that protect production-facing gates.

The workflows are YAML, but this checker intentionally stays stdlib-only so it
can run before the dev environment is installed. It does not try to be a full
YAML parser; it checks stable, high-value invariants that are easy to lose when
editing `.github/workflows/ci.yml` or `.github/workflows/codspeed.yml`.

The release pipeline is deliberately out of scope: those workflows come from
`reflex-release`, which owns their invariants (tested where the tool lives) and
ships `sync` to detect drift. Asserting their contents here as well duplicated
that and went stale the moment the tool changed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEFAULT_CODSPEED_WORKFLOW = ROOT / ".github" / "workflows" / "codspeed.yml"
DEFAULT_WORKFLOW = DEFAULT_CI_WORKFLOW
REQUIRED_CI_JOBS = {
    "result",
    "changes",
    "build",
    "browser_conformance",
    "matplotlib_reference",
    "pyplot_gallery",
    "pyplot_gallery_extended",
    "test",
    "rust_checks",
    "browser_smokes",
    "regression_checks",
    "python_floor",
    "benchmark_vs",
    "benchmark_methodology",
    "benchmark",
    "sdist",
    "wheels",
    "install_without_rust",
}
REQUIRED_CODSPEED_JOBS = {"benchmarks"}

CI_SUMMARY_DEPENDENCIES = (
    "changes",
    "build",
    "test",
    "rust_checks",
    "browser_smokes",
    "regression_checks",
    "python_floor",
    "matplotlib_reference",
    "matplotlib_patch_smoke",
    "pyplot_gallery",
    "pyplot_gallery_extended",
    "browser_conformance",
    "sdist",
    "wheels",
    "install_without_rust",
)
CI_SUMMARY_COMMANDS = [
    "python3 - <<'PY'",
    "import json, os",
    "results = json.loads(os.environ['RESULTS'])",
    "failed = [name for name, job in results.items() if job['result'] not in ('success', 'skipped')]",
    'assert not failed, f"CI jobs failed or cancelled: {failed}"',
    "assert results['changes']['result'] == 'success', 'CI selection must succeed'",
    "PY",
]


# Versions observed in passing CI runs; update these inputs and their spec together.
CI_BOOTSTRAP_INPUTS = {
    "actions/checkout": ("persist-credentials", "false"),
    "actions/setup-node": ("node-version", "22.23.3"),
    "astral-sh/setup-uv": ("version", "0.13.5"),
    "dtolnay/rust-toolchain": ("toolchain", "1.99.1"),
    "actions/setup-python": ("python-version", "3.11.17"),
}
CODSPEED_ACTION_COMMIT = "f99becdce5e5d51fd556489ebef684f4ecfd6286"
CONFORMANCE_IMAGE = "mcr.microsoft.com/playwright:v1.61.1-noble@sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48"


def _job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "jobs:")
    except StopIteration:
        return {}

    blocks: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in lines[start + 1 :]:
        if line.strip() and len(line) == len(line.lstrip(" ")):
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = [line]
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(block) for name, block in blocks.items()}


def _matrix_include_entries(job_text: str) -> list[dict[str, str]]:
    """Parse the flat mappings under one job's strategy.matrix.include list."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_include = False
    for line in job_text.splitlines():
        if line == "        include:":
            in_include = True
            continue
        if not in_include:
            continue
        if line.startswith("          - "):
            if current is not None:
                entries.append(current)
            current = {}
            item = line.removeprefix("          - ")
        elif line.startswith("            ") and not line.lstrip().startswith("#"):
            item = line.removeprefix("            ")
        elif line.strip() and len(line) - len(line.lstrip()) <= 8:
            break
        else:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+):\s*(.*?)", item)
        if match and current is not None:
            current[match.group(1)] = match.group(2)
    if current is not None:
        entries.append(current)
    return entries


def _missing_needles(block: str, needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if needle not in block]


_YAML_KEY_TOKEN = r"""(?:"(?:\\.|[^"\\])*"|'(?:''|[^'])*'|[A-Za-z_][A-Za-z0-9_-]*)"""
_DIRECT_YAML_KEY = re.compile(rf"^(?P<key>{_YAML_KEY_TOKEN})\s*:(?=\s|$)(?P<value>.*)$")
_NODE_PROPERTY_MAPPING_KEY = re.compile(
    rf"^(?:(?:![^\s]+|&[^\s]+)\s+)+"
    rf"(?:{_YAML_KEY_TOKEN}|\*[^\s:]+|<<)\s*:(?=\s|$)"
)
_ALIAS_OR_MERGE_MAPPING_KEY = re.compile(r"^(?:\*[^\s:]+|<<)\s*:(?=\s|$)")
_YAML_NODE_PROPERTIES_ONLY = re.compile(r"(?:(?:![^\s]+|&[^\s]+)\s*)+")


def _strip_yaml_comment(line: str) -> str:
    """Remove a YAML comment while preserving ``#`` inside quoted scalars."""
    quote: Optional[str] = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote == '"':
            if char == "\\":
                index += 2
                continue
            if char == '"':
                quote = None
        elif quote == "'":
            if char == "'" and index + 1 < len(line) and line[index + 1] == "'":
                index += 2
                continue
            if char == "'":
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
        index += 1
    return line.rstrip()


def _yaml_code_lines(text: str) -> list[str]:
    """Return comment-free source lines for indentation-scoped checks.

    The protected keys below are checked only at their exact structural
    indentation. More deeply indented scalar content is irrelevant; a rare
    same-indent quoted continuation that resembles a protected structural key
    deliberately fails closed rather than requiring a full YAML parser.
    """
    return [_strip_yaml_comment(line) for line in text.splitlines()]


def _decode_yaml_key(token: str) -> tuple[Optional[str], bool]:
    """Return a simple scalar key and whether its spelling is unsupported.

    JSON decoding covers YAML's common double-quoted escapes, including
    ``\\u`` spellings used to hide ASCII workflow keys. YAML-only escape forms
    (for example ``\\x`` or ``\\U``) fail closed rather than attempting to
    duplicate a complete YAML scalar decoder.
    """
    if token.startswith('"'):
        try:
            decoded = json.loads(token)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, True
        return (decoded, False) if isinstance(decoded, str) else (None, True)
    if token.startswith("'"):
        return token[1:-1].replace("''", "'"), False
    return token, False


def _yaml_mapping_keys(text: str) -> list[tuple[Optional[int], Optional[str], bool]]:
    """Lex block mapping keys as ``(indent, value, unsafe_syntax)``."""
    lines = _yaml_code_lines(text)
    keys: list[tuple[Optional[int], Optional[str], bool]] = []
    explicit = re.compile(rf"^\?\s+(?P<key>{_YAML_KEY_TOKEN})(?:\s*:.*)?\s*$")
    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        body = line[indent:]
        match = _DIRECT_YAML_KEY.match(body)
        if match is not None:
            value, unsafe = _decode_yaml_key(match.group("key"))
            keys.append((indent, value, unsafe))
        elif (match := explicit.match(body)) is not None:
            value, _unsafe = _decode_yaml_key(match.group("key"))
            # Explicit keys are valid YAML but unnecessary in these protected
            # workflow scopes. Treat even a recognized spelling as unsafe so
            # a following value line cannot alter the reviewed structure.
            keys.append((indent, value, True))
        elif body == "?" or body.startswith("? "):
            # Complex/multiline explicit keys are irrelevant to these
            # workflow contracts and hard to normalize without a YAML parser.
            # Treat the explicit key indicator itself as unsafe at this scope.
            keys.append((indent, None, True))
        elif body.startswith('"') and "\\" in body:
            # A double-quoted key can continue onto another source line with a
            # backslash, hiding the decoded key from a line-local lexer.
            keys.append((indent, None, True))
        elif _NODE_PROPERTY_MAPPING_KEY.match(body) or _ALIAS_OR_MERGE_MAPPING_KEY.match(body):
            # YAML node properties, aliases, and merge keys can normalize or
            # import an effective mapping key (for example
            # ``!!str BASH_ENV:``, ``*anchored_key:``, or ``<<: *defaults``).
            # Protected workflow scopes do not need them, so fail closed.
            keys.append((indent, None, True))
    return keys


def _direct_yaml_mapping(
    line: str,
) -> Optional[tuple[int, Optional[str], bool, str]]:
    """Return ``(indent, decoded_key, unsafe, raw_value)`` for a block key."""
    indent = len(line) - len(line.lstrip(" "))
    match = _DIRECT_YAML_KEY.match(line[indent:])
    if match is None:
        return None
    key, unsafe = _decode_yaml_key(match.group("key"))
    return indent, key, unsafe, match.group("value")


def _sequence_item_yaml_mapping(
    line: str,
) -> Optional[tuple[int, Optional[str], bool, str]]:
    """Return the first mapping entry carried by a block sequence item.

    A step written as ``- uses: ...`` has a mapping key two columns deeper
    than the sequence indicator. Decode that key exactly like a regular block
    key so quoted and escape-equivalent spellings cannot disappear from
    structural step checks.
    """
    indent = len(line) - len(line.lstrip(" "))
    item = re.match(r"^-\s+(?P<mapping>.*)$", line[indent:])
    if item is None:
        return None
    match = _DIRECT_YAML_KEY.match(item.group("mapping"))
    if match is None:
        return None
    key, unsafe = _decode_yaml_key(match.group("key"))
    return indent + 2, key, unsafe, match.group("value")


def _step_direct_key_values(step: str, key: str) -> tuple[list[str], bool]:
    """Return direct values for one key in a standard Actions step mapping."""
    values: list[str] = []
    unsafe = False
    for index, line in enumerate(_yaml_code_lines(step)):
        parsed = _sequence_item_yaml_mapping(line) if index == 0 else _direct_yaml_mapping(line)
        if parsed is None or parsed[0] != 8:
            continue
        _indent, candidate, candidate_unsafe, value = parsed
        if candidate_unsafe:
            unsafe = True
        elif candidate == key:
            values.append(value.strip())
    return values, unsafe


def _environment_block_is_unsafe(lines: list[str], index: int, env_indent: int) -> bool:
    """Inspect one reviewed block-style Actions ``env`` mapping."""
    parsed = _direct_yaml_mapping(lines[index])
    if parsed is None or parsed[3].strip():
        # Inline flow maps, aliases, and tagged values are unnecessary in the
        # protected scopes and require full YAML resolution, so fail closed.
        return True

    descendants: list[str] = []
    for line in lines[index + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= env_indent:
            break
        descendants.append(line)
    if not descendants:
        return False

    child_indent = min(len(line) - len(line.lstrip(" ")) for line in descendants)
    quote: Optional[str] = None

    def closes(value: str, delimiter: str, *, starts_here: bool) -> bool:
        cursor = 1 if starts_here else 0
        while cursor < len(value):
            char = value[cursor]
            if delimiter == '"' and char == "\\":
                cursor += 2
                continue
            if (
                delimiter == "'"
                and char == "'"
                and cursor + 1 < len(value)
                and value[cursor + 1] == "'"
            ):
                cursor += 2
                continue
            if char == delimiter:
                return True
            cursor += 1
        return False

    for line in descendants:
        if quote is not None:
            if closes(line, quote, starts_here=False):
                quote = None
            continue
        if len(line) - len(line.lstrip(" ")) != child_indent:
            continue
        child = _direct_yaml_mapping(line)
        if child is None:
            return True
        _indent, key, unsafe, value = child
        if unsafe or key in {"BASH_ENV", "ENV", "PATH"}:
            return True
        scalar = value.lstrip()
        if scalar[:1] in {'"', "'"} and not closes(scalar, scalar[0], starts_here=True):
            quote = scalar[0]
    return quote is not None


def _has_shell_init_environment(text: str) -> bool:
    """Reject shell-init state in workflow/job/step environment scopes.

    Exact indentation plus the enclosing job section distinguishes Actions
    environment mappings from unrelated data keys such as ``matrix.env`` or a
    ``with.env`` action input. Protected hard-gate jobs also have a simple,
    reviewable policy of never referencing GitHub's persistent environment
    file, so earlier steps cannot directly persist shell initialization for a
    later reviewed command.
    """
    lines = _yaml_code_lines(text)
    protected_jobs = _job_blocks(text)
    protected_job_text = "\n".join(
        protected_jobs.get(job, "")
        for job in (
            "matplotlib_reference",
            "test",
            "rust_checks",
            "browser_smokes",
            "regression_checks",
        )
    )
    if any(
        re.search(r"\bGITHUB_(?:ENV|PATH)\b", line)
        for line in _yaml_code_lines(protected_job_text)
        if line.strip()
    ):
        return True

    in_jobs = False
    in_job = False
    job_section: Optional[str] = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        parsed = _direct_yaml_mapping(line)
        indent = len(line) - len(line.lstrip(" "))

        relevant_env = False
        if indent == 0:
            key = None if parsed is None else parsed[1]
            value = "" if parsed is None else parsed[3]
            relevant_env = key == "env"
            in_jobs = key == "jobs" and not value.strip()
            in_job = False
            job_section = None
        elif in_jobs and indent == 2:
            in_job = parsed is not None
            job_section = None
        elif in_jobs and in_job and indent == 4:
            key = None if parsed is None else parsed[1]
            value = "" if parsed is None else parsed[3]
            relevant_env = key == "env"
            stripped_value = value.strip()
            opens_block = not stripped_value or _YAML_NODE_PROPERTIES_ONLY.fullmatch(stripped_value)
            job_section = key if parsed is not None and opens_block else None
        elif in_jobs and in_job and indent == 8 and job_section == "steps":
            relevant_env = parsed is not None and parsed[1] == "env"

        if not relevant_env:
            continue
        if parsed is None or parsed[2] or _environment_block_is_unsafe(lines, index, indent):
            return True
    return False


def _has_yaml_key(text: str, key: str, *, indent: Optional[int] = None) -> bool:
    """Recognize equivalent YAML mapping-key spellings.

    Unrecognized escape-encoded mapping keys fail closed: allowing one in a
    protected scope would let the YAML parser reveal ``run``, ``ENV``, or a
    suppression key only after this stdlib-only verifier had approved it.
    """
    return any(
        (candidate_indent is not None or indent is None)
        and (indent is None or candidate_indent == indent)
        and (unsafe or candidate == key)
        for candidate_indent, candidate, unsafe in _yaml_mapping_keys(text)
    )


def _direct_yaml_key_count(text: str, key: str, *, indent: int) -> int:
    """Count equivalent direct mapping keys at one block indentation."""
    return sum(
        candidate_indent == indent and (unsafe or candidate == key)
        for candidate_indent, candidate, unsafe in _yaml_mapping_keys(text)
    )


def _direct_yaml_key_values(text: str, key: str, *, indent: int) -> tuple[list[str], bool]:
    """Return normalized direct values and whether that scope is ambiguous."""
    values: list[str] = []
    for line in _yaml_code_lines(text):
        parsed = _direct_yaml_mapping(line)
        if parsed is None:
            continue
        candidate_indent, candidate, unsafe, value = parsed
        if candidate_indent == indent and candidate == key and not unsafe:
            values.append(value.strip())
    unsafe = any(
        candidate_indent == indent and candidate_unsafe
        for candidate_indent, _candidate, candidate_unsafe in _yaml_mapping_keys(text)
    )
    return values, unsafe


def _unique_mapping_block(text: str, key: str, *, indent: int) -> Optional[str]:
    """Return one block-style mapping value, bounded by its indentation."""
    # Count all normalized occurrences before selecting the reviewed block.
    # In particular, an inline duplicate (``"on": {}``) or an unsupported
    # equivalent spelling must not be ignored merely because one ordinary
    # block-style occurrence is also present.
    if _direct_yaml_key_count(text, key, indent=indent) != 1:
        return None
    raw_lines = text.splitlines()
    code_lines = _yaml_code_lines(text)
    starts: list[int] = []
    for index, line in enumerate(code_lines):
        parsed = _direct_yaml_mapping(line)
        if parsed is None or parsed[0] != indent or parsed[1] != key or parsed[2]:
            continue
        value = parsed[3].strip()
        if not value or _YAML_NODE_PROPERTIES_ONLY.fullmatch(value):
            starts.append(index)
    if len(starts) != 1:
        return None
    start = starts[0]
    end = len(raw_lines)
    for index in range(start + 1, len(code_lines)):
        line = code_lines[index]
        if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
            end = index
            break
    return "\n".join(raw_lines[start + 1 : end])


def _require_unique_workflow_structure(
    errors: list[str],
    text: str,
    workflow_label: str,
    required_jobs: set[str],
) -> None:
    """Reject duplicate/encoded overrides of protected workflow mappings."""
    top_blocks: dict[str, Optional[str]] = {}
    for key in ("on", "jobs"):
        block = _unique_mapping_block(text, key, indent=0)
        top_blocks[key] = block
        if block is None:
            errors.append(
                f"{workflow_label} workflow must define exactly one unambiguous block-style "
                "top-level "
                f"{key!r} key"
            )

    job_keys: list[tuple[Optional[int], Optional[str], bool]] = []
    if top_blocks["jobs"] is not None:
        job_keys = _yaml_mapping_keys(top_blocks["jobs"] or "")

    unsafe_job_key = any(indent == 2 and unsafe for indent, _key, unsafe in job_keys)
    for job in sorted(required_jobs):
        count = sum(
            indent == 2 and candidate == job and not unsafe
            for indent, candidate, unsafe in job_keys
        )
        if unsafe_job_key or count != 1:
            errors.append(
                f"{workflow_label} workflow must define exactly one unambiguous {job!r} job"
            )


def _steps_block(job_text: str) -> str:
    """Return the unique actual ``steps:`` sequence inside one job."""
    return _unique_mapping_block(job_text, "steps", indent=4) or ""


def _step_sequence_blocks(job_text: str) -> list[str]:
    """Return the actual sequence items under a job's unique ``steps`` key."""
    blocks: list[list[str]] = []
    current: Optional[list[str]] = None
    for line in _steps_block(job_text).splitlines():
        if re.match(r"^      -(?:\s|$)", line):
            current = [line]
            blocks.append(current)
        elif current is not None:
            current.append(line)
    return ["\n".join(block) for block in blocks]


def _named_step_blocks(job_text: str) -> dict[str, str]:
    """Return named blocks from the job's actual ``steps:`` sequence."""
    blocks: dict[str, str] = {}
    for block in _step_sequence_blocks(job_text):
        first = _strip_yaml_comment(block.splitlines()[0])
        match = re.match(r"^      - name:\s*(.+?)\s*$", first)
        if match is not None:
            blocks[match.group(1)] = block
    return blocks


def _require_step_contains(
    errors: list[str], job_text: str, step: str, description: str, *needles: str
) -> None:
    block = _named_step_blocks(job_text).get(step)
    if block is None:
        errors.append(f"missing required CI step {step!r}")
        return
    missing = _missing_needles(block, needles)
    if missing:
        errors.append(f"CI step {step!r} missing {description}: {missing}")


def _step_run_lines(step_block: str) -> list[str]:
    """Return executable lines from one named step's ``run`` value only."""
    lines = step_block.splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(r"        run:\s*(.*?)\s*", line)
        if match is None:
            continue
        value = match.group(1)
        # Folded scalars concatenate adjacent source lines before the shell
        # sees them. That makes a visually separate ``# disabled`` line turn
        # the following command into comment text, so this exact-command gate
        # accepts only a one-line value or a literal block.
        if value.startswith(">"):
            return []
        if value not in {"|", "|-", "|+"}:
            return [value] if value and not value.startswith("#") else []

        commands: list[str] = []
        for command in lines[index + 1 :]:
            if command.strip() and len(command) - len(command.lstrip()) <= 8:
                break
            stripped = command.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)
        return commands
    return []


def _require_step_runs_exactly(
    errors: list[str], job_text: str, step: str, description: str, *commands: str
) -> None:
    """Require the exact active command list in a hard-gate named step."""
    block = _named_step_blocks(job_text).get(step)
    if block is None:
        errors.append(f"missing required CI step {step!r}")
        return
    # Membership is insufficient: a needle could otherwise be heredoc data,
    # an uninvoked function body, or one folded argument to another command.
    forbidden_step_keys = ("if", "continue-on-error", "shell", "working-directory")
    has_forbidden_step_key = any(_has_yaml_key(block, key, indent=8) for key in forbidden_step_keys)
    forbidden_job_keys = (
        "continue-on-error",
        "defaults",
        "container",
        "strategy",
    )
    has_forbidden_job_key = any(
        _has_yaml_key(job_text, key, indent=4) for key in forbidden_job_keys
    )
    # Scope/dependency controls are allowed only in their reviewed form.
    group = "pyplot" if job_text.startswith("  matplotlib_reference:") else "runtime"
    for key, expected in (
        ("if", f"needs.changes.outputs.{group} == 'true'"),
        ("needs", "changes" if job_text.startswith("  rust_checks:") else "[changes, build]"),
    ):
        values, ambiguous = _direct_yaml_key_values(job_text, key, indent=4)
        if ambiguous or values != [expected]:
            has_forbidden_job_key = True
    has_exactly_one_run_key = _direct_yaml_key_count(block, "run", indent=8) == 1
    if (
        not has_exactly_one_run_key
        or _step_run_lines(block) != list(commands)
        or has_forbidden_step_key
        or has_forbidden_job_key
    ):
        errors.append(f"CI step {step!r} missing {description}: {list(commands)!r}")


def _require_job_contains(
    errors: list[str],
    jobs: dict[str, str],
    job: str,
    workflow_label: str,
    description: str,
    *needles: str,
) -> None:
    block = jobs.get(job)
    if block is None:
        errors.append(f"missing required {workflow_label} job {job!r}")
        return
    missing = _missing_needles(block, needles)
    if missing:
        errors.append(f"{workflow_label} {job} job missing {description}: {missing}")


def _step_block(job_text: str, step_needle: str) -> Optional[str]:
    """The indented block of the step whose `uses:`/`run:` line contains
    `step_needle` — the step's own lines only, so a same-level sibling step
    can't mask a missing key.

    The prefix (the step's own `uses:`/`name:`/`run:` line) is matched with
    `[^\\n]*`, not a dot-all `.*` — under re.DOTALL a greedy `.*` would happily
    span past earlier sibling steps and swallow their `if:` lines too, which
    defeats the whole point of scoping this to one step.
    """
    match = re.search(
        rf"( *)- (?:uses|name|run): [^\n]*{re.escape(step_needle)}[^\n]*\n([\s\S]*?)(?=\n\1- |\Z)",
        _steps_block(job_text),
    )
    return None if match is None else match.group(0)


def _step_is_conditioned(job_text: str, step_needle: str) -> bool:
    """True if the step has its own `if:` key — not just any `if:` elsewhere
    in the job (e.g. a sibling step's dry-run summary)."""
    block = _step_block(job_text, step_needle)
    return block is not None and "if:" in block


def _require_workflow_contains(
    errors: list[str],
    text: str,
    workflow_label: str,
    description: str,
    *needles: str,
) -> None:
    missing = _missing_needles(text, needles)
    if missing:
        errors.append(f"{workflow_label} workflow missing {description}: {missing}")


def _require_unshallow_checkouts(errors: list[str], text: str, workflow_label: str) -> None:
    """Every checkout must fetch full history, tags included.

    The distribution version is derived from the latest `v*` tag
    (uv-dynamic-versioning in pyproject), and `actions/checkout` defaults to a
    depth-1 clone carrying no tags at all. Under that default the version
    resolves to the `0.0.0` fallback *silently* — a build succeeds and ships the
    wrong number rather than failing. So a shallow checkout here is a publishing
    bug, not a performance tweak, and it is invisible until someone reads a
    PyPI page. Cheap to require, expensive to notice late.
    """
    checkout_count = 0
    for job in _job_blocks(text).values():
        for step in _step_sequence_blocks(job):
            uses_values, uses_unsafe = _step_direct_key_values(step, "uses")
            uses_checkout = uses_unsafe or any(
                value.startswith("actions/checkout@") for value in uses_values
            )
            if not uses_checkout:
                continue
            checkout_count += 1
            with_block = _unique_mapping_block(step, "with", indent=8)
            if with_block is not None:
                values, unsafe = _direct_yaml_key_values(with_block, "fetch-depth", indent=10)
            else:
                values, unsafe = [], False
            if not unsafe and values == ["0"]:
                continue
            errors.append(
                f"{workflow_label} workflow has an actions/checkout step without a unique "
                "direct `fetch-depth: 0` input — the distribution version is derived from "
                "git tags, which a shallow checkout does not fetch, so the build would "
                "quietly fall back to 0.0.0"
            )
    if checkout_count == 0:
        errors.append(f"{workflow_label} workflow has no structurally recognized checkout step")


def _require_ci_bootstrap_inputs(errors: list[str], text: str, label: str) -> None:
    """Require explicit credential isolation and reviewed tool versions."""
    for job in _job_blocks(text).values():
        for step in _step_sequence_blocks(job):
            uses_values, uses_unsafe = _step_direct_key_values(step, "uses")
            if uses_unsafe or len(uses_values) > 1:
                errors.append(f"{label} bootstrap step has an ambiguous action reference")
                continue
            if not uses_values:
                continue
            uses, decode_unsafe = _decode_yaml_key(uses_values[0])
            if decode_unsafe or uses is None:
                errors.append(f"{label} bootstrap step has an ambiguous action reference")
                continue
            action = uses.split("@", 1)[0]
            if action == "CodSpeedHQ/action" and uses != f"{action}@{CODSPEED_ACTION_COMMIT}":
                errors.append(f"{label} must pin CodSpeed to the reviewed commit SHA")
            if action not in CI_BOOTSTRAP_INPUTS:
                continue
            if not re.fullmatch(r"[^@]+@[0-9a-fA-F]{40}", uses):
                errors.append(f"{label} {action} must use a full 40-hex commit SHA")
            key, expected = CI_BOOTSTRAP_INPUTS[action]
            with_block = _unique_mapping_block(step, "with", indent=8)
            values, unsafe = _direct_yaml_key_values(with_block or "", key, indent=10)
            decoded = [_decode_yaml_key(value) for value in values]
            if (
                unsafe
                or any(ambiguous for _, ambiguous in decoded)
                or [value for value, _ in decoded] != [expected]
            ):
                errors.append(f"{label} {action} must define a unique direct {key}: {expected}")


def _workflow_trigger_block(text: str, trigger: str) -> Optional[str]:
    """Return one trigger mapping from the unique top-level ``on`` block."""
    on_block = _unique_mapping_block(text, "on", indent=0)
    if on_block is None:
        return None
    return _unique_mapping_block(on_block, trigger, indent=2)


def _require_trigger_with_direct_option(
    errors: list[str],
    text: str,
    workflow_label: str,
    trigger: str,
    option: str,
    expected: str,
) -> None:
    """Require one direct trigger option inside the unique ``on`` mapping."""
    block = _workflow_trigger_block(text, trigger)
    if block is None:
        errors.append(f"{workflow_label} workflow missing {trigger} trigger")
        return
    values, unsafe = _direct_yaml_key_values(block, option, indent=4)
    if unsafe or values != [expected]:
        errors.append(
            f"{workflow_label} {trigger} trigger must define exactly one direct "
            f"{option}: {expected} option"
        )


def _require_docs_spec_pr_paths_ignored(errors: list[str], text: str, workflow_label: str) -> None:
    """Require PR-only docs/spec changes in the unique top-level trigger block."""
    pull_request = _workflow_trigger_block(text, "pull_request")
    if pull_request is None:
        errors.append(f"{workflow_label} workflow missing pull_request trigger")
        return
    paths_block = _unique_mapping_block(pull_request, "paths-ignore", indent=4)
    paths_ignore: list[str] = []
    for line in _yaml_code_lines(paths_block or ""):
        if len(line) - len(line.lstrip(" ")) != 6:
            continue
        item = re.fullmatch(r"\s*-\s+(.+?)\s*", line)
        if item is None:
            continue
        value = item.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        paths_ignore.append(value)

    required = {"docs/**", "spec/**"}
    missing = sorted(required - set(paths_ignore))
    if missing:
        errors.append(
            f"{workflow_label} pull_request trigger must skip docs/spec-only changes: {missing}"
        )


def _require_ci_summary(errors: list[str], jobs: dict[str, str]) -> None:
    """Protect the aggregate required check from omitted or weakened gates."""
    summary = jobs.get("result", "")
    for key, expected in (
        ("needs", f"[{', '.join(CI_SUMMARY_DEPENDENCIES)}]"),
        ("if", "always()"),
    ):
        values, ambiguous = _direct_yaml_key_values(summary, key, indent=4)
        if ambiguous or values != [expected]:
            errors.append(f"CI summary must define {key}: {expected}")
    if _has_yaml_key(summary, "continue-on-error", indent=4):
        errors.append("CI summary must be blocking")
    step = _named_step_blocks(summary).get("Require selected checks to succeed", "")
    step_env = _unique_mapping_block(step, "env", indent=8)
    results_values, results_ambiguous = _direct_yaml_key_values(
        step_env or "", "RESULTS", indent=10
    )
    if (
        _direct_yaml_key_count(step, "run", indent=8) != 1
        or _step_run_lines(step) != CI_SUMMARY_COMMANDS
        or any(
            _has_yaml_key(step, key, indent=8)
            for key in (
                "if",
                "continue-on-error",
                "shell",
                "working-directory",
            )
        )
        or results_ambiguous
        or results_values != ["${{ toJSON(needs) }}"]
    ):
        errors.append("CI summary must run the reviewed failure and selection assertions")


def validate_ci_workflow(path: Path = DEFAULT_CI_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CI workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_unique_workflow_structure(errors, text, "CI", REQUIRED_CI_JOBS)
    if _has_yaml_key(text, "defaults", indent=0):
        errors.append("CI workflow must not override the shell for hard-gate run steps")
    if _has_shell_init_environment(text):
        errors.append("CI workflow must not set shell-init environment variables")
    if _workflow_trigger_block(text, "pull_request") is None:
        errors.append("CI workflow missing pull_request trigger")
    _require_job_contains(
        errors,
        jobs,
        "changes",
        "CI",
        "complete diff scope selection",
        'scripts/ci_scope.py --base "$BASE_SHA" --head "$HEAD_SHA"',
        "scripts/ci_scope.py --full",
        "steps.scope.outputs.pyplot",
    )
    scopes = {
        "build": "build",
        "matplotlib_reference": "pyplot",
        "matplotlib_patch_smoke": "pyplot",
        "pyplot_gallery": "pyplot",
        "pyplot_gallery_extended": "pyplot",
        "test": "runtime",
        "rust_checks": "runtime",
        "browser_smokes": "runtime",
        "regression_checks": "runtime",
        "python_floor": "runtime",
        "benchmark_vs": "benchmarks",
        "benchmark_methodology": "benchmarks",
        "browser_conformance": "conformance",
        "sdist": "packaging",
        "wheels": "packaging",
        "install_without_rust": "packaging",
    }
    for job, group in scopes.items():
        values, ambiguous = _direct_yaml_key_values(jobs.get(job, ""), "if", indent=4)
        if ambiguous or values != [f"needs.changes.outputs.{group} == 'true'"]:
            errors.append(f"CI {job} must use the reviewed {group} scope")
    for job in (
        "test",
        "browser_smokes",
        "regression_checks",
        "python_floor",
        "matplotlib_reference",
        "matplotlib_patch_smoke",
        "pyplot_gallery",
        "pyplot_gallery_extended",
        "browser_conformance",
        "benchmark_vs",
        "benchmark_methodology",
    ):
        _require_job_contains(
            errors,
            jobs,
            job,
            "CI",
            "same-run native/client reuse",
            "needs: [changes, build]",
            "uses: ./.github/actions/restore-ci-build",
        )
    _require_job_contains(
        errors,
        jobs,
        "build",
        "CI",
        "verified shared wheel producer",
        "uv build --wheel",
        'XY_REQUIRE_CARGO: "1"',
        "scripts/verify_wheel.py dist/*.whl --expect-native",
        "name: ci-linux-wheel",
        "actions/upload-artifact@",
    )
    _require_ci_summary(errors, jobs)
    _require_step_contains(
        errors,
        jobs.get("python_floor", ""),
        "Install package and compatibility test dependencies for Python 3.11",
        "Python floor pyyaml workflow-test dependency",
        '"pyyaml>=6"',
    )
    _require_unshallow_checkouts(errors, text, "CI")
    _require_ci_bootstrap_inputs(errors, text, "CI")
    missing_jobs = sorted(REQUIRED_CI_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"CI workflow missing required jobs: {missing_jobs}")

    _require_job_contains(
        errors,
        jobs,
        "matplotlib_reference",
        "CI",
        "released Matplotlib compatibility gates",
        "matplotlib==3.11.0",
        "matplotlib.__version__ == '3.11.0'",
        "scripts/generate_pyplot_compat_inventory.py --check",
        "scripts/sync_matplotlib_compat.py --check",
        "scripts.pyplot_gallery.contract check",
        "tests/pyplot/test_gallery_contract.py",
        "tests/pyplot/test_gallery_metrics.py",
        "tests/pyplot/test_launch_compat.py",
        "tests/pyplot/test_reference_corpus.py",
        "tests/pyplot/test_reference_semantics.py",
        "MPLBACKEND: Agg",
    )
    reference = jobs.get("matplotlib_reference", "")
    _require_step_runs_exactly(
        errors,
        reference,
        "Install xy and released reference wheel",
        "released reference installation",
        "uv venv .venv",
        "uv pip install -p .venv/bin/python dist/*.whl --group dev",
        'uv pip install -p .venv/bin/python "matplotlib==3.11.0"',
    )
    _require_step_runs_exactly(
        errors,
        reference,
        "Verify released reference and reviewed snapshot",
        "version and snapshot checks",
        ".venv/bin/python -c \"import matplotlib; assert matplotlib.__version__ == '3.11.0'\"",
        ".venv/bin/python scripts/generate_pyplot_compat_inventory.py --check",
        ".venv/bin/python scripts/sync_matplotlib_compat.py --check",
        ".venv/bin/python -m scripts.pyplot_gallery.contract check",
    )
    _require_step_runs_exactly(
        errors,
        reference,
        "Run optional-interoperability and dual-engine corpus tests",
        "reference test commands",
        ".venv/bin/pytest -q tests/pyplot/test_gallery_contract.py",
        ".venv/bin/pytest -q tests/pyplot/test_gallery_metrics.py",
        ".venv/bin/pytest -q tests/pyplot/test_launch_compat.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_corpus.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_semantics.py",
    )
    _require_job_contains(
        errors,
        jobs,
        "pyplot_gallery",
        "CI",
        "required eight-shard pyplot compatibility ratchet",
        "fail-fast: false",
        "shard: [0, 1, 2, 3, 4, 5, 6, 7]",
        "dtolnay/rust-toolchain@",
        'XY_REQUIRE_CARGO: "1"',
        "matplotlib==3.11.0",
        "scripts.pyplot_gallery.run_gallery",
        "--profile standard",
        '--shard "${{ matrix.shard }}/8"',
        "Upload failure-only gallery evidence",
        "if: always()",
        "actions/upload-artifact@",
        "report.json",
        "junit.xml",
        "/failures",
        "if-no-files-found: warn",
    )
    gallery_job = jobs.get("pyplot_gallery", "")
    if "continue-on-error:" in gallery_job:
        errors.append("CI pyplot_gallery compatibility ratchet must be blocking")

    _require_job_contains(
        errors,
        jobs,
        "pyplot_gallery_extended",
        "CI",
        "strict 12-example extended gallery environment",
        "runs-on: ubuntu-24.04",
        "timeout-minutes: 90",
        "dtolnay/rust-toolchain@",
        "Install TeX, fonts, GTK3/4, and virtual display",
        "Install xy and pinned extended Python dependencies",
        "Verify extended dependency and driver contract",
        "Run all 12 extended differential examples",
        "Require 12/12 extended acceptance with no waivers",
        "Upload extended gallery evidence",
        "if: always()",
        "actions/upload-artifact@",
        "gallery-extended-artifacts/report.json",
        "gallery-extended-artifacts/junit.xml",
        "gallery-extended-artifacts/failures",
        "if-no-files-found: warn",
    )
    extended_gallery = jobs.get("pyplot_gallery_extended", "")
    if "continue-on-error:" in extended_gallery:
        errors.append("CI pyplot_gallery_extended completion gate must be blocking")
    _require_step_contains(
        errors,
        extended_gallery,
        "Install TeX, fonts, GTK3/4, and virtual display",
        "exact TeX, font, GTK, and Xvfb packages",
        "sudo apt-get update",
        "sudo apt-get install --no-install-recommends -y",
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
    _require_step_contains(
        errors,
        extended_gallery,
        "Install xy and pinned extended Python dependencies",
        "system-Python GI bridge and pinned optional dependencies",
        'XY_REQUIRE_CARGO: "1"',
        "uv venv .venv --python /usr/bin/python3 --system-site-packages",
        '"colorspacious==1.1.2"',
        '"matplotlib==3.11.0"',
    )
    _require_step_contains(
        errors,
        extended_gallery,
        "Verify extended dependency and driver contract",
        "metadata and Xvfb preflight commands",
        "scripts.pyplot_gallery.extended_environment check",
        'xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24"',
        "scripts.pyplot_gallery.extended_environment preflight",
    )
    _require_step_contains(
        errors,
        extended_gallery,
        "Run all 12 extended differential examples",
        "unsharded complete extended profile command",
        'xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24"',
        "scripts.pyplot_gallery.run_gallery",
        "--profile extended",
        "--shard 0/1 \\",
        "--workers 2",
        "--timeout 180",
    )
    _require_step_contains(
        errors,
        extended_gallery,
        "Require 12/12 extended acceptance with no waivers",
        "strict post-run completion check",
        "scripts.pyplot_gallery.extended_environment",
        "verify-report gallery-extended-artifacts/report.json",
    )

    _require_job_contains(
        errors,
        jobs,
        "test",
        "CI",
        "hard production gates",
        "scripts/verify_ci_workflow.py",
        "scripts/check_public_api.py",
        "Verify bundled Reflex integration import",
        "importlib.metadata as m, reflex_xy",
        "assert reflex_xy.__version__ == m.version('xy')",
        "ruff check .",
        "scripts/check_typing.py",
    )
    _require_job_contains(
        errors,
        jobs,
        "browser_smokes",
        "CI",
        "hard browser production gates",
        "scripts/abi_smoke.py",
        "scripts/render_smoke_nonumpy.py",
        "scripts/polar_parity_smoke.py",
        "scripts/append_stream_smoke.py",
        "scripts/png_export_smoke.py",
        "JS parses (ESM + IIFE)",
        "scripts/smoke_render.py",
        "Polar phase 6/7 live examples",
        "scripts/polar_phase7_smoke.py",
        "Browser lifecycle smoke",
        "Browser visual regression smoke",
        "Browser interaction stress smoke",
        "Browser dashboard reliability smoke",
        "scripts/reflex_lifecycle_smoke.py",
        "scripts/visual_regression_smoke.py",
        "scripts/interaction_stress_smoke.py",
        "benchmarks/bench_dashboard.py",
        "--chart-counts 10,20,50,60",
        "dashboard-smoke.json --kind dashboard-browser",
    )
    _require_job_contains(
        errors,
        jobs,
        "regression_checks",
        "CI",
        "hard benchmark regression gates",
        "scripts/bench_native.py --sizes 1e5,1e6",
        "scripts/bench.py --sizes 1e5,1e6",
        "--sizes 1e5,1e6,1e7 --production --json scatter.json",
        "scripts/bench_native.py --sizes 1e6,1e7 --json kernel.json",
        "scripts/verify_benchmark_report.py scatter.json --kind scatter-native",
        "scripts/verify_benchmark_report.py kernel.json --kind kernel-native",
        "benchmarks/bench_transport.py --n 1e6 --reps 15",
        '--browser-reps 12 --chromium "$CHROME" --require-browser --json transport.json',
        "scripts/verify_benchmark_report.py transport.json --kind transport-loopback",
        "scripts/check_regressions.py --scatter scatter.json --kernel kernel.json",
        "--transport transport.json --emit-md spec/benchmarks/metrics.md",
        "Upload regression benchmark report",
        "if: always()",
        "actions/upload-artifact@",
        "regression-benchmark-report",
        "if-no-files-found: warn",
        "spec/benchmarks/metrics.md",
        "transport.json",
    )
    test_job = jobs.get("test", "")
    allowed_step_conditions = {
        (
            "browser_smokes",
            "Pyplot backend, widget, mode, behavior, and protocol gate (Chromium)",
        ): ["needs.changes.outputs.pyplot == 'true'"],
        ("regression_checks", "Upload regression benchmark report"): ["always()"],
    }
    for job in ("test", "rust_checks", "browser_smokes", "regression_checks"):
        if _has_yaml_key(jobs.get(job, ""), "continue-on-error"):
            errors.append(f"CI {job} job and its required steps must be blocking")
        for step in _step_sequence_blocks(jobs.get(job, "")):
            names, names_unsafe = _step_direct_key_values(step, "name")
            name = _decode_yaml_key(names[0])[0] if len(names) == 1 else ""
            conditions, conditions_unsafe = _step_direct_key_values(step, "if")
            if (
                names_unsafe
                or len(names) > 1
                or conditions_unsafe
                or conditions != allowed_step_conditions.get((job, name), [])
            ):
                errors.append(f"CI {job} has an unreviewed step condition on {name or 'setup'}")
    rust_job = jobs.get("rust_checks", "")
    values, ambiguous = _direct_yaml_key_values(rust_job, "needs", indent=4)
    if ambiguous or values != ["changes"]:
        errors.append("CI rust_checks must depend only on changes, independent of the wheel")
    for name, command in (
        ("Rust unit tests", "cargo test"),
        ("Rust lint", "cargo clippy --all-targets -- -D warnings"),
    ):
        _require_step_runs_exactly(errors, rust_job, name, "blocking Rust checks", command)
    for job in ("test", "browser_smokes", "regression_checks"):
        _require_job_contains(
            errors,
            jobs,
            job,
            "CI",
            "shared Chromium setup",
            "uses: ./.github/actions/setup-ci-chromium",
        )
        _require_step_runs_exactly(
            errors,
            jobs.get(job, ""),
            "Install package + dev deps",
            "locked runtime development environment",
            "uv sync --locked --extra reflex --group dev",
            'uv pip install -p .venv/bin/python "matplotlib==3.11.0"',
        )
    _require_step_contains(
        errors,
        test_job,
        "Python tests (native core)",
        "required full pytest Chromium environment",
        "XY_CHROMIUM=",
        "require('playwright').chromium.executablePath()",
        "XY_REQUIRE_BROWSER=1",
        ".venv/bin/pytest -q",
    )
    _require_step_contains(
        errors,
        jobs.get("browser_smokes", ""),
        "Pyplot backend, widget, mode, behavior, and protocol gate (Chromium)",
        "pinned Matplotlib browser compatibility suites",
        'XY_REQUIRE_BROWSER: "1"',
        "XY_CHROMIUM=",
        "require('playwright').chromium.executablePath()",
        "matplotlib.__version__ == '3.11.0'",
        "tests/backends/test_backend_xy.py",
        "tests/backends/test_backend_xy_widget.py",
        "tests/backends/test_pyplot_svg_gallery_browser.py",
        "tests/backends/test_display_list.py",
        "tests/pyplot/test_modes.py",
        "tests/pyplot/test_gallery_behavior.py",
        "tests/pyplot/test_public_protocols.py",
    )
    _require_job_contains(
        errors,
        jobs,
        "browser_conformance",
        "CI",
        "accessibility and three-engine conformance gate",
        'node-version: "22.23.3"',
        "npm ci",
        "PLAYWRIGHT_BROWSERS_PATH: /ms-playwright",
        "Verify preinstalled Playwright browsers",
        "accessSync(browser.executablePath())",
        "chromium, firefox, webkit",
        "test -f python/xy/static/standalone.js",
        "node scripts/browser_conformance.mjs",
    )
    conformance_container = _unique_mapping_block(
        jobs.get("browser_conformance", ""), "container", indent=4
    )
    images, images_unsafe = _direct_yaml_key_values(conformance_container or "", "image", indent=6)
    if images_unsafe or images != [CONFORMANCE_IMAGE]:
        errors.append("CI browser_conformance must use the reviewed pinned browser image")
    conformance_job = jobs.get("browser_conformance", "")
    preflight = _named_step_blocks(conformance_job).get(
        "Verify preinstalled Playwright browsers", ""
    )
    # The text alone is not a gate: a skipped, non-blocking, or redirected
    # step would pass it without ever probing a browser.
    if (
        _direct_yaml_key_count(preflight, "run", indent=8) != 1
        or any(
            _has_yaml_key(preflight, key, indent=8)
            for key in ("if", "continue-on-error", "shell", "working-directory")
        )
        or any(
            _has_yaml_key(conformance_job, key, indent=4)
            for key in ("continue-on-error", "defaults")
        )
        or _step_run_lines(preflight)
        != [
            "node --input-type=module - <<'JS'",
            "import { accessSync } from 'node:fs';",
            "import { chromium, firefox, webkit } from 'playwright';",
            "for (const browser of [chromium, firefox, webkit]) {",
            "accessSync(browser.executablePath());",
            "}",
            "JS",
        ]
    ):
        errors.append("CI browser preflight must actively verify all three executable paths")
    _require_job_contains(
        errors,
        jobs,
        "python_floor",
        "CI",
        "Python 3.11 floor gate",
        'python-version: "3.11.17"',
        "scripts/check_python_floor.py",
        "scripts/check_public_api.py",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark_vs",
        "CI",
        "parallel cross-library benchmark matrix",
        "continue-on-error: true",
        "timeout-minutes: 20",
        "fail-fast: false",
        "matrix:",
        "xy: false",
        "browser: false",
        "build_js: false",
        "if: matrix.xy",
        "if: matrix.browser",
        "if: matrix.build_js",
        "--constraint benchmarks/requirements-ci.lock",
        "CHROMIUM_ARGS=()",
        "--libraries",
        "--max-n",
        "Run cross-library benchmark group",
        "Upload cross-library benchmark part",
        "benchmark-vs-${{ matrix.name }}",
        "if: always()",
        "actions/upload-artifact@",
        "if-no-files-found: warn",
    )
    cross_library = jobs.get("benchmark_vs", "")
    expected_matrix = {
        "native-and-webgl": {
            "libraries": "xy,plotly_gl,bokeh_webgl,datashader",
            "packages": "plotly kaleido bokeh datashader psutil",
            "max_n": "10000000",
            "xy": "true",
            "browser": "true",
            "build_js": "true",
        },
        "matplotlib": {
            "libraries": "matplotlib",
            "packages": "numpy matplotlib psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "false",
            "build_js": "false",
        },
        "seaborn": {
            "libraries": "seaborn",
            "packages": "numpy seaborn psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "false",
            "build_js": "false",
        },
        "plotly-svg": {
            "libraries": "plotly_svg",
            "packages": "numpy plotly kaleido psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "true",
            "build_js": "false",
        },
        "bokeh-canvas": {
            "libraries": "bokeh_canvas",
            "packages": "numpy bokeh psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "true",
            "build_js": "false",
        },
        "html-adapters": {
            "libraries": "altair,hvplot_bokeh",
            "packages": "numpy altair hvplot psutil",
            "max_n": "100000",
            "xy": "false",
            "browser": "true",
            "build_js": "false",
        },
    }
    matrix_entries = _matrix_include_entries(cross_library)
    matrix_by_name = {
        entry["name"]: entry for entry in matrix_entries if isinstance(entry.get("name"), str)
    }
    matrix_names = [entry.get("name") for entry in matrix_entries]
    duplicate_names = sorted({name for name in matrix_names if matrix_names.count(name) > 1})
    if duplicate_names:
        errors.append(f"CI benchmark_vs matrix has duplicate names: {duplicate_names}")
    if set(matrix_by_name) != set(expected_matrix):
        errors.append(
            "CI benchmark_vs matrix names must exactly match isolated benchmark groups; "
            f"got {sorted(matrix_by_name)}, expected {sorted(expected_matrix)}"
        )
    for name, expected in expected_matrix.items():
        actual = matrix_by_name.get(name)
        if actual is None:
            continue
        expected_entry = {"name": name, **expected}
        if actual != expected_entry:
            errors.append(
                f"CI benchmark_vs matrix entry {name!r} must exactly equal "
                f"{expected_entry!r}; got {actual!r}"
            )
    if not _step_is_conditioned(cross_library, "dtolnay/rust-toolchain@"):
        errors.append("CI benchmark_vs Rust toolchain setup must be conditioned on matrix.xy")
    _require_step_contains(
        errors,
        cross_library,
        "Build native core",
        "xy-only setup condition",
        "if: matrix.xy",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Install xy",
        "xy-only constrained install",
        "if: matrix.xy",
        'XY_REQUIRE_CARGO: "1"',
        "--constraint benchmarks/requirements-ci.lock",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Install selected competitors",
        "locked benchmark dependency constraint",
        "--constraint benchmarks/requirements-ci.lock",
        "${{ matrix.packages }}",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Verify native benchmark backend",
        "xy-only verification condition",
        "if: matrix.xy",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Install Chromium (Playwright)",
        "browser-only setup condition",
        "if: matrix.browser",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Build JS client",
        "xy browser-build condition",
        "if: matrix.build_js",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark_methodology",
        "CI",
        "non-blocking methodology benchmark artifact path",
        "continue-on-error: true",
        "benchmarks/requirements-ci.lock",
        "Verify native benchmark backend",
        "XY_REQUIRE_CARGO",
        'k.BACKEND == "native"',
        "benchmark job requires native backend",
        "scripts/verify_benchmark_report.py",
        "Upload benchmark methodology",
        "if: always()",
        "actions/upload-artifact@",
        "line.json",
        "install.json",
        "interaction.json",
        "dashboard.json",
        "workflows.json",
        "install-fresh.json",
        "verify_benchmark_report.py line.json --kind line-decimation",
        "verify_benchmark_report.py install.json --kind install-footprint",
        "verify_benchmark_report.py interaction.json --kind interaction-browser",
        "verify_benchmark_report.py dashboard.json --kind dashboard-browser",
        "verify_benchmark_report.py workflows.json --kind workflow-native",
        "bench_interaction.py",
        "bench_dashboard.py",
        "--chart-counts 10,20,50,60",
        "docs/benchmark_ci.md",
        "if-no-files-found: warn",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark",
        "CI",
        "merged benchmark artifact path",
        "continue-on-error: true",
        "needs: [benchmark_vs, benchmark_methodology]",
        "if: always()",
        "actions/download-artifact@",
        "pattern: benchmark-vs-*",
        "name: benchmark-methodology",
        "scripts/merge_benchmark_reports.py",
        "benchmark.json",
        "verify_benchmark_report.py benchmark.json --kind scatter-vs",
        "Upload benchmark report",
        "actions/upload-artifact@",
        "line.json",
        "install.json",
        "interaction.json",
        "dashboard.json",
        "workflows.json",
        "install-fresh.json",
        "docs/benchmark_ci.md",
        "if-no-files-found: warn",
    )
    _require_job_contains(
        errors,
        jobs,
        "sdist",
        "CI",
        "source artifact verification",
        "dtolnay/rust-toolchain@",
        "uv build --sdist",
        "scripts/verify_sdist.py",
    )
    ci_sdist = jobs.get("sdist", "")
    _require_step_contains(
        errors,
        ci_sdist,
        "Build and load native core from sdist",
        "Rust-backed sdist install contract",
        "XY_REQUIRE_CARGO",
        "uv pip install --no-cache",
        '"reflex>=0.9.6"',
        "import reflex_xy",
        "import xy.kernels as kernels",
        'kernels.BACKEND == "native"',
    )
    _require_step_contains(
        errors,
        ci_sdist,
        "Verify coreless sdist imports reflex_xy",
        "coreless sdist import contract",
        "XY_SKIP_CARGO",
        "uv pip install --no-cache",
        "import reflex_xy",
        "assert reflex_xy.__version__ == version",
        "native Rust core",
    )
    _require_job_contains(
        errors,
        jobs,
        "wheels",
        "CI",
        "native wheel verification and upload",
        "XY_REQUIRE_CARGO",
        "scripts/verify_wheel.py",
        "--expect-native",
        "actions/upload-artifact@",
        "dist/*.whl",
    )
    _require_job_contains(
        errors,
        jobs,
        "install_without_rust",
        "CI",
        "no-Rust wheel builds but errors clearly on compute",
        "Remove preinstalled Rust",
        "scripts/verify_wheel.py",
        "--expect-pure",
        "native Rust core",
    )
    return errors


def validate_workflow(path: Path = DEFAULT_WORKFLOW) -> list[str]:
    """Backward-compatible CI workflow verifier."""
    return validate_ci_workflow(path)


def validate_codspeed_workflow(path: Path = DEFAULT_CODSPEED_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CodSpeed workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_unique_workflow_structure(errors, text, "CodSpeed", REQUIRED_CODSPEED_JOBS)
    _require_docs_spec_pr_paths_ignored(errors, text, "CodSpeed")
    _require_trigger_with_direct_option(
        errors,
        text,
        "CodSpeed",
        "push",
        "branches",
        '["main"]',
    )
    if _workflow_trigger_block(text, "workflow_dispatch") is None:
        errors.append("CodSpeed workflow missing workflow_dispatch trigger")
    _require_unshallow_checkouts(errors, text, "CodSpeed")
    _require_ci_bootstrap_inputs(errors, text, "CodSpeed")
    missing_jobs = sorted(REQUIRED_CODSPEED_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"CodSpeed workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "CodSpeed",
        "OIDC permissions",
        "id-token: write",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmarks",
        "CodSpeed",
        "native-only benchmark path",
        "dtolnay/rust-toolchain@",
        "actions/setup-python@",
        'python-version: "3.11.17"',
        "astral-sh/setup-uv@",
        "cargo build --release",
        "XY_REQUIRE_CARGO",
        "--group dev --group codspeed",
        "Verify native benchmark backend",
        'k.BACKEND == "native"',
        "CodSpeed requires native backend",
        "CodSpeedHQ/action@",
        "mode: simulation",
        "benchmarks/test_codspeed_kernels.py --codspeed",
    )
    return errors


def validate_all_workflows(
    ci_path: Path = DEFAULT_CI_WORKFLOW,
    codspeed_path: Path = DEFAULT_CODSPEED_WORKFLOW,
) -> list[str]:
    return [
        *validate_ci_workflow(ci_path),
        *validate_codspeed_workflow(codspeed_path),
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workflow",
        nargs="?",
        type=Path,
        help="legacy CI workflow path override; checks CI only when provided",
    )
    parser.add_argument("--ci-workflow", type=Path, default=DEFAULT_CI_WORKFLOW)
    parser.add_argument("--codspeed-workflow", type=Path, default=DEFAULT_CODSPEED_WORKFLOW)
    parser.add_argument("--ci-only", action="store_true")
    parser.add_argument("--codspeed-only", action="store_true")
    args = parser.parse_args(argv)

    if args.ci_only and args.codspeed_only:
        parser.error("--ci-only and --codspeed-only are mutually exclusive")

    if args.workflow is not None:
        errors = validate_ci_workflow(args.workflow)
        checked = [args.workflow]
    elif args.ci_only:
        errors = validate_ci_workflow(args.ci_workflow)
        checked = [args.ci_workflow]
    elif args.codspeed_only:
        errors = validate_codspeed_workflow(args.codspeed_workflow)
        checked = [args.codspeed_workflow]
    else:
        errors = validate_all_workflows(args.ci_workflow, args.codspeed_workflow)
        checked = [args.ci_workflow, args.codspeed_workflow]

    if errors:
        print(
            "Workflow verification failed for " + ", ".join(str(path) for path in checked) + ":",
            file=sys.stderr,
        )
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Workflow verification OK: " + ", ".join(str(path) for path in checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
