#!/usr/bin/env python3
"""Verify workflow invariants that protect production-facing gates.

The workflows are YAML, but this checker intentionally stays stdlib-only so it
can run before the dev environment is installed. It does not try to be a full
YAML parser; it checks stable, high-value invariants that are easy to lose when
editing `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
`.github/workflows/release-reflex-xy.yml`, or the production docs release gate.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEFAULT_CODSPEED_WORKFLOW = ROOT / ".github" / "workflows" / "codspeed.yml"
DEFAULT_RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
DEFAULT_REFLEX_XY_RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-reflex-xy.yml"
DEFAULT_DOCS_DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-docs-stg.yml"
DEFAULT_WORKFLOW = DEFAULT_CI_WORKFLOW
REQUIRED_CI_JOBS = {
    "browser_conformance",
    "matplotlib_reference",
    "test",
    "python_floor",
    "benchmark_vs",
    "benchmark_methodology",
    "benchmark",
    "sdist",
    "wheels",
    "install_without_rust",
}
REQUIRED_CODSPEED_JOBS = {"benchmarks"}
REQUIRED_RELEASE_JOBS = {"wheels", "sdist", "publish", "wasm", "github-release"}
REQUIRED_REFLEX_XY_RELEASE_JOBS = {"build", "publish"}


def _job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "jobs:")
    except StopIteration:
        return {}

    blocks: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in lines[start + 1 :]:
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


def _named_step_blocks(job_text: str) -> dict[str, str]:
    """Return step-local blocks; comments elsewhere cannot satisfy a gate."""
    lines = job_text.splitlines()
    blocks: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in lines:
        match = re.match(r"^      - name:\s*(.+?)\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = [line]
            continue
        if re.match(r"^      - ", line):
            current = None
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def _job_step_blocks(job_text: str) -> list[str]:
    """Return every active job step, including unnamed ``uses``/``run`` steps."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in job_text.splitlines():
        if re.match(r"^      -(?:\s|$)", line):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)
    return ["\n".join(block) for block in blocks]


def _step_name(step_text: str) -> str | None:
    """Return an active step name, if the step declares one."""
    match = re.search(r"^      - name:\s*(.+?)\s*$", step_text, re.MULTILINE)
    return None if match is None else match.group(1)


def _step_run(step_text: str) -> str | None:
    """Return one step's shell, supporting block and one-line ``run`` values."""
    lines = step_text.splitlines()
    for start, line in enumerate(lines):
        match = re.match(r"^        run:\s*(.*?)\s*$", line)
        if match is None:
            continue
        value = _strip_yaml_inline_comment(match.group(1))
        if not re.fullmatch(r"[|>][+-]?", value):
            return value or None
        shell_lines: list[str] = []
        for body_line in lines[start + 1 :]:
            if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= 8:
                break
            if body_line.lstrip().startswith("#"):
                continue
            shell_lines.append(
                body_line[10:] if body_line.startswith("          ") else body_line.lstrip()
            )
        return "\n".join(shell_lines)
    return None


def _job_scalar(job_text: str, key: str) -> str | None:
    """Return an active job-level scalar, ignoring comments and nested keys."""
    match = re.search(rf"^    {re.escape(key)}:\s*(.*?)\s*$", job_text, re.MULTILINE)
    return None if match is None else match.group(1)


def _step_scalar(step_text: str, key: str) -> str | None:
    """Return an active named-step scalar, ignoring comments and nested keys."""
    match = re.search(rf"^        {re.escape(key)}:\s*(.*?)\s*$", step_text, re.MULTILINE)
    return None if match is None else _strip_yaml_inline_comment(match.group(1))


def _strip_yaml_inline_comment(value: str) -> str:
    """Strip a plain-scalar YAML comment without touching quoted ``#`` text."""
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value.rstrip()


def _job_mapping(job_text: str, key: str) -> dict[str, str] | None:
    """Return an active job-level mapping with direct scalar children."""
    lines = job_text.splitlines()
    try:
        start = lines.index(f"    {key}:")
    except ValueError:
        return None

    mapping: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 4:
            break
        match = re.fullmatch(r"      ([A-Za-z0-9_-]+):\s*(.*?)\s*", line)
        if match:
            mapping[match.group(1)] = _strip_yaml_inline_comment(match.group(2))
    return mapping


def _named_step_run(job_text: str, step: str) -> str | None:
    """Return one named step's active shell body without comment-only lines."""
    block = _named_step_blocks(job_text).get(step)
    return None if block is None else _step_run(block)


def _shell_logical_lines(shell: str) -> list[str]:
    """Join backslash-continued shell lines while preserving command order."""
    logical_lines: list[str] = []
    pending = ""
    for raw_line in shell.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pending = f"{pending} {line}".strip() if pending else line
        trailing_backslashes = len(pending) - len(pending.rstrip("\\"))
        if trailing_backslashes % 2:
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        logical_lines.append(pending)
    return logical_lines


def _shell_tokens(command: str) -> list[str] | None:
    """Tokenize one logical shell line, including control-operator tokens."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.commenters = "#"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _shell_command_records(shell: str) -> list[tuple[int, str, list[str]]]:
    """Return successfully tokenized logical shell lines in source order."""
    records: list[tuple[int, str, list[str]]] = []
    for position, command in enumerate(_shell_logical_lines(shell)):
        tokens = _shell_tokens(command)
        if tokens is not None:
            records.append((position, command, tokens))
    return records


def _shell_maybe_successful_terminations(
    logical_lines: list[str],
) -> list[tuple[int, int, str, str | None]]:
    """Return active shell termination commands that may report success.

    A release gate must enumerate every successful termination, not merely
    prove that its expected success path exists: an earlier ``exit 0`` leaves
    all of the later guarded shell present but dead. ``exec`` can replace the
    gate with a successful command. Bare exit/return commands inherit the
    preceding status, and dynamic statuses can evaluate to zero. Bash also
    reduces numeric statuses modulo 256, so only an explicit integer whose
    reduced status is nonzero is unambiguously a failure.

    The command-start check recognizes normal shell control boundaries and the
    ``command``/``builtin`` wrappers without mistaking text such as
    ``printf '%s' exit`` for an active termination.
    """
    boundary_tokens = {
        "&",
        "&&",
        "(",
        ")",
        ";",
        ";;",
        "do",
        "elif",
        "else",
        "if",
        "then",
        "until",
        "while",
        "|",
        "||",
        "{",
        "}",
        "!",
    }
    command_wrappers = {"builtin", "command", "time"}
    executing_wrapper_options = {"--", "-p"}
    assignment = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    explicit_status = re.compile(r"^[+-]?[0-9]+$")
    terminations: list[tuple[int, int, str, str | None]] = []

    for position, line in enumerate(logical_lines):
        tokens = _shell_tokens(line)
        if tokens is None:
            continue
        for token_position, token in enumerate(tokens):
            if token not in {"exec", "exit", "return"}:
                continue

            command_start = 0
            for prefix_position in range(token_position - 1, -1, -1):
                if tokens[prefix_position] in boundary_tokens:
                    command_start = prefix_position + 1
                    break
            prefix = tokens[command_start:token_position]
            while prefix and assignment.match(prefix[0]):
                prefix = prefix[1:]
            if prefix and not all(
                item in command_wrappers or item in executing_wrapper_options for item in prefix
            ):
                continue

            command_end = len(tokens)
            for suffix_position in range(token_position + 1, len(tokens)):
                if tokens[suffix_position] in boundary_tokens:
                    command_end = suffix_position
                    break
            arguments = tokens[token_position + 1 : command_end]
            status = arguments[0] if len(arguments) == 1 else None
            if (
                token != "exec"
                and status is not None
                and explicit_status.fullmatch(status)
                and int(status, 10) % 256 != 0
            ):
                continue
            terminations.append((position, token_position, token, status))

    return terminations


def _shell_function_definition_count(shell: str, name: str) -> int:
    """Count active Bash definitions of ``name``, including one-line overrides."""
    pattern = re.compile(rf"^(?:function\s+)?{re.escape(name)}(?:\s*\(\))?\s*\{{(?:\s|$)")
    return sum(bool(pattern.match(line)) for line in _shell_logical_lines(shell))


def _has_gh_release_mutation(shell: str) -> bool:
    """Return whether shell directly invokes a GitHub Release write command."""
    mutations = {"create", "delete", "edit", "upload"}
    write_methods = {"DELETE", "PATCH", "POST", "PUT"}
    for _, _, tokens in _shell_command_records(shell):
        for index in range(len(tokens) - 2):
            if tokens[index : index + 2] == ["gh", "release"] and tokens[index + 2] in mutations:
                return True
            if tokens[index : index + 2] != ["gh", "api"]:
                continue
            api_tokens = tokens[index + 2 :]
            methods = [
                api_tokens[position + 1].upper()
                for position, token in enumerate(api_tokens[:-1])
                if token in {"--method", "-X"}
            ]
            if not any(method in write_methods for method in methods):
                continue
            release_endpoints = [
                token for token in api_tokens if re.search(r"(?:^|/)releases(?:/|$)", token)
            ]
            if any(
                not endpoint.endswith("/releases/generate-notes") for endpoint in release_endpoints
            ):
                return True
    return False


def _option_values(tokens: list[str], option: str) -> list[str | None]:
    """Return every value supplied to an exact long option token."""
    values: list[str | None] = []
    for index, token in enumerate(tokens):
        if token == option:
            values.append(tokens[index + 1] if index + 1 < len(tokens) else None)
        elif token.startswith(f"{option}="):
            values.append(token.removeprefix(f"{option}="))
    return values


def _has_exact_option(tokens: list[str], option: str, value: str) -> bool:
    """Require one unambiguous long option whose value is exactly expected."""
    return _option_values(tokens, option) == [value]


def _is_release_metadata_read(tokens: list[str]) -> bool:
    """Recognize the complete GitHub Release metadata read used by the gate."""
    fields = "assets,body,isDraft,isImmutable,isPrerelease,name,publishedAt,tagName"
    command = [
        "timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "30s",
        "gh",
        "release",
        "view",
        "$TAG",
        "--repo",
        "$REPO",
        "--json",
        fields,
    ]
    return tokens in (command, [*command, "2>/dev/null"])


def _is_release_payload_verification(tokens: list[str]) -> bool:
    """Recognize a direct call that validates the current release payload."""
    return tokens in (
        [
            "verify_release_payload",
            "$release_json",
            "$pypi_hashes_json",
            ";",
            "then",
        ],
        [
            "!",
            "verify_release_payload",
            "$release_json",
            "$expected_hashes_json",
            ";",
            "then",
        ],
    )


def _has_guarded_release_validation(logical_lines: list[str], metadata_position: int) -> bool:
    """Bind a metadata assignment to payload verification and a failing guard."""
    if metadata_position < 1 or metadata_position + 6 >= len(logical_lines):
        return False
    if logical_lines[metadata_position - 1] != 'release_json="$(':
        return False
    if logical_lines[metadata_position + 1] != ')"':
        return False
    if _shell_tokens(logical_lines[metadata_position + 2]) != [
        "if",
        "!",
        "release_metadata_matches",
        "$release_json",
        "||",
    ]:
        return False
    if _shell_tokens(logical_lines[metadata_position + 3]) != [
        "!",
        "verify_release_payload",
        "$release_json",
        "$expected_hashes_json",
        ";",
        "then",
    ]:
        return False
    expected_errors = {
        'echo "::error::${TAG} release metadata, notes, or assets are invalid after creation"',
        'echo "::error::${TAG} release metadata, notes, or assets are invalid after normalization"',
    }
    return (
        logical_lines[metadata_position + 4] in expected_errors
        and _shell_tokens(logical_lines[metadata_position + 5]) == ["exit", "1"]
        and _shell_tokens(logical_lines[metadata_position + 6]) == ["fi"]
    )


def _assignment_lines(logical_lines: list[str], name: str) -> list[str]:
    """Return active direct assignments to one protected shell variable."""
    pattern = re.compile(rf"^(?:if (?:! )?)?{re.escape(name)}=")
    return [line for line in logical_lines if pattern.match(line)]


def _logical_line_is(logical_lines: list[str], position: int, expected: str) -> bool:
    """Compare one logical shell line without allowing negative indexing."""
    return 0 <= position < len(logical_lines) and logical_lines[position] == expected


def _has_exact_tag_source_gate(
    logical_lines: list[str],
    lookup_position: int,
    *,
    failure_statement: str,
) -> bool:
    """Require an adjacent, timeout-bounded tag lookup and failing SHA guard."""
    if lookup_position < 1 or lookup_position + 8 >= len(logical_lines):
        return False
    return logical_lines[lookup_position - 1 : lookup_position + 9] == [
        'if ! tag_source_sha="$(',
        "timeout --signal=TERM --kill-after=5s 30s "
        "gh api \"repos/${REPO}/commits/${TAG}\" --jq '.sha'",
        ')"; then',
        'echo "::error::Could not resolve ${TAG} to its source commit"',
        failure_statement,
        "fi",
        'if [[ "$tag_source_sha" != "$GITHUB_SHA" ]]; then',
        'echo "::error::${TAG} resolves to ${tag_source_sha}, not workflow source ${GITHUB_SHA}"',
        failure_statement,
        "fi",
    ]


def _has_exact_tag_source_function(
    logical_lines: list[str],
    lookup_position: int,
) -> bool:
    """Require the reusable tag guard to fail on lookup or SHA mismatch."""
    if lookup_position < 3 or lookup_position + 9 >= len(logical_lines):
        return False
    return logical_lines[lookup_position - 3 : lookup_position + 10] == [
        "verify_tag_source() {",
        "local tag_source_sha",
        'if ! tag_source_sha="$(',
        "timeout --signal=TERM --kill-after=5s 30s "
        "gh api \"repos/${REPO}/commits/${TAG}\" --jq '.sha'",
        ')"; then',
        'echo "::error::Could not resolve ${TAG} to its source commit"',
        "return 1",
        "fi",
        'if [[ "$tag_source_sha" != "$GITHUB_SHA" ]]; then',
        'echo "::error::${TAG} resolves to ${tag_source_sha}, not workflow source ${GITHUB_SHA}"',
        "return 1",
        "fi",
        "}",
    ]


def _has_exact_docs_tag_source_function(
    logical_lines: list[str],
    lookup_position: int,
) -> bool:
    """Require the docs gate's bounded current-tag/source comparison."""
    if lookup_position < 3 or lookup_position + 5 >= len(logical_lines):
        return False
    return logical_lines[lookup_position - 3 : lookup_position + 6] == [
        "verify_tag_source() {",
        "local current_tag_sha",
        'if ! current_tag_sha="$(',
        "timeout --signal=TERM --kill-after=5s 30s "
        "gh api \"repos/${REPO}/commits/${VERSION}\" --jq '.sha'",
        ')"; then',
        "return 1",
        "fi",
        '[[ "$current_tag_sha" == "$SOURCE_SHA" ]]',
        "}",
    ]


def _has_exact_pypi_gate_flow(
    logical_lines: list[str],
    *,
    version_variable: str,
    expected_hashes_variable: str,
    immutable_variable: str | None = None,
) -> tuple[bool, int]:
    """Bind one bounded PyPI response to an exact all-file equality guard."""
    url = f"https://pypi.org/pypi/xy/${{{version_variable}}}/json"
    fetch_tokens = [
        "curl",
        "-fsS",
        "--connect-timeout",
        "5",
        "--max-time",
        "20",
        url,
        "2>/dev/null",
    ]
    fetch_positions = [
        position
        for position, _, tokens in _shell_command_records("\n".join(logical_lines))
        if tokens == fetch_tokens
    ]
    equality_tokens = (
        [
            "if",
            "[[",
            immutable_variable,
            "==",
            "true",
            "||",
            "$pypi_hashes_json",
            "==",
            expected_hashes_variable,
            "]]",
            ";",
            "then",
        ]
        if immutable_variable is not None
        else [
            "[[",
            "$pypi_hashes_json",
            "==",
            expected_hashes_variable,
            "]]",
            ";",
            "then",
        ]
    )
    equality_positions = [
        position
        for position, line in enumerate(logical_lines)
        if _shell_tokens(line) == equality_tokens
    ]
    guard_tokens = ["if", "[[", "$pypi_matches", "!=", "true", "]]", ";", "then"]
    guard_positions = [
        position
        for position, line in enumerate(logical_lines)
        if _shell_tokens(line) == guard_tokens
    ]
    if len(fetch_positions) != 1 or len(equality_positions) != 1 or len(guard_positions) != 1:
        return False, -1

    fetch_position = fetch_positions[0]
    equality_position = equality_positions[0]
    guard_position = guard_positions[0]
    hash_assignment_positions = [
        position for position, line in enumerate(logical_lines) if line == 'if pypi_hashes_json="$('
    ]
    assignments_are_exact = (
        _assignment_lines(logical_lines, "pypi_json") == ['if pypi_json="$(']
        and _assignment_lines(logical_lines, "pypi_hashes_json") == ['if pypi_hashes_json="$(']
        and _assignment_lines(logical_lines, "pypi_matches")
        == ["pypi_matches=false", "pypi_matches=true"]
    )
    fetch_is_direct = (
        fetch_position >= 1
        and fetch_position + 1 < len(logical_lines)
        and logical_lines[fetch_position - 1] == 'if pypi_json="$('
        and logical_lines[fetch_position + 1] == ')"; then'
    )
    malformed_response_retries = (
        len(hash_assignment_positions) == 1
        and hash_assignment_positions[0] == fetch_position + 2
        and ')" &&' in logical_lines[hash_assignment_positions[0] + 1 : equality_position]
    )
    equality_sets_match = equality_position + 3 < len(logical_lines) and logical_lines[
        equality_position + 1 : equality_position + 4
    ] == ["pypi_matches=true", "break", "fi"]
    guard_fails_closed = (
        guard_position >= 1
        and guard_position + 3 < len(logical_lines)
        and logical_lines[guard_position - 1] == "done"
        and logical_lines[guard_position + 1 : guard_position + 4]
        == [
            'echo "::error::PyPI files for ${TAG} do not exactly match the verified build"',
            "exit 1",
            "fi",
        ]
    )
    return (
        assignments_are_exact
        and fetch_is_direct
        and malformed_response_retries
        and fetch_position < equality_position < guard_position
        and equality_sets_match
        and guard_fails_closed,
        guard_position,
    )


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
        job_text,
    )
    return None if match is None else match.group(0)


def _step_is_conditioned(job_text: str, step_needle: str) -> bool:
    """True if the step has its own `if:` key — not just any `if:` elsewhere
    in the job (e.g. a sibling step's dry-run summary)."""
    block = _step_block(job_text, step_needle)
    return block is not None and "if:" in block


# The one condition that actually gates a PyPI upload behind the manual
# dry-run switch. Requiring this exact predicate on the upload step itself —
# not merely *an* `if:` — is the point: `if: always()` or any unrelated
# condition would satisfy a mere presence check while gating nothing.
PYPI_PUBLISH_GATE = (
    "if: github.event_name != 'workflow_dispatch' || github.event.inputs.dry_run != 'true'"
)
CORE_PRERELEASE_TAG_PATTERN = r"^v[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$"


def _step_carries_publish_gate(job_text: str, step_needle: str) -> bool:
    block = _step_block(job_text, step_needle)
    return block is not None and PYPI_PUBLISH_GATE in block


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
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "uses: actions/checkout@" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        step: list[str] = []
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped:
                continue
            following_indent = len(following) - len(following.lstrip())
            if following_indent < indent or (
                following_indent == indent and stripped.startswith("-")
            ):
                break
            step.append(stripped)
        if "fetch-depth: 0" not in step:
            errors.append(
                f"{workflow_label} workflow has an actions/checkout step (line {index + 1}) "
                "without `fetch-depth: 0` — the distribution version is derived from git "
                "tags, which a shallow checkout does not fetch, so the build would quietly "
                "fall back to 0.0.0"
            )


def _require_docs_spec_pr_paths_ignored(errors: list[str], text: str, workflow_label: str) -> None:
    """Require PR-only docs/spec changes to skip an expensive workflow."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "  pull_request:")
    except StopIteration:
        errors.append(f"{workflow_label} workflow missing pull_request trigger")
        return

    paths_ignore: list[str] | None = None
    collecting_paths_ignore = False
    for line in lines[start + 1 :]:
        indent = len(line) - len(line.lstrip())
        if line.strip() and indent <= 2:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if indent == 4:
            collecting_paths_ignore = bool(re.fullmatch(r"paths-ignore:\s*(?:#.*)?", stripped))
            if collecting_paths_ignore:
                paths_ignore = []
            continue
        if not collecting_paths_ignore or indent <= 4:
            continue
        item = re.fullmatch(r"-\s+(.+?)\s*", stripped)
        if item is None or paths_ignore is None:
            continue
        value = re.sub(r"\s+#.*$", "", item.group(1)).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        paths_ignore.append(value)

    required = {"docs/**", "spec/**"}
    missing = sorted(required - set(paths_ignore or []))
    if missing:
        errors.append(
            f"{workflow_label} pull_request trigger must skip docs/spec-only changes: {missing}"
        )


def validate_ci_workflow(path: Path = DEFAULT_CI_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CI workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_docs_spec_pr_paths_ignored(errors, text, "CI")
    _require_unshallow_checkouts(errors, text, "CI")
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
        "scripts/sync_matplotlib_compat.py --check",
        "tests/pyplot/test_launch_compat.py",
        "tests/pyplot/test_reference_corpus.py",
        "tests/pyplot/test_reference_semantics.py",
        "MPLBACKEND: Agg",
    )
    reference = jobs.get("matplotlib_reference", "")
    _require_step_contains(
        errors,
        reference,
        "Install xy and released reference wheel",
        "released reference installation",
        'uv pip install -p .venv/bin/python "matplotlib==3.11.0"',
    )
    _require_step_contains(
        errors,
        reference,
        "Verify released reference and reviewed snapshot",
        "version and snapshot checks",
        "matplotlib.__version__ == '3.11.0'",
        "scripts/sync_matplotlib_compat.py --check",
    )
    _require_step_contains(
        errors,
        reference,
        "Run optional-interoperability and dual-engine corpus tests",
        "reference test commands",
        ".venv/bin/pytest -q tests/pyplot/test_launch_compat.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_corpus.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_semantics.py",
    )

    _require_job_contains(
        errors,
        jobs,
        "test",
        "CI",
        "hard production gates",
        "scripts/verify_ci_workflow.py",
        "scripts/check_public_api.py",
        "ruff check .",
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
        "--chart-counts 10,20,50",
        "dashboard-smoke.json --kind dashboard-browser",
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
    _require_job_contains(
        errors,
        jobs,
        "browser_conformance",
        "CI",
        "accessibility and three-engine conformance gate",
        'node-version: "22"',
        "npm ci",
        "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
        "~/.cache/ms-playwright",
        "playwright-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('package-lock.json') }}",
        "npx playwright install --with-deps chromium firefox webkit",
        "node js/build.mjs",
        "node scripts/browser_conformance.mjs",
    )
    _require_job_contains(
        errors,
        jobs,
        "python_floor",
        "CI",
        "Python 3.11 floor gate",
        'python-version: "3.11"',
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
        "timeout-minutes: 10",
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
        "uv build --sdist",
        "scripts/verify_sdist.py",
        "XY_SKIP_CARGO",
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
    _require_docs_spec_pr_paths_ignored(errors, text, "CodSpeed")
    _require_unshallow_checkouts(errors, text, "CodSpeed")
    missing_jobs = sorted(REQUIRED_CODSPEED_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"CodSpeed workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "CodSpeed",
        "push, PR, manual triggers, and OIDC permissions",
        'branches: ["main"]',
        "pull_request:",
        "workflow_dispatch:",
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
        'python-version: "3.11"',
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


def validate_release_workflow(path: Path = DEFAULT_RELEASE_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read release workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_unshallow_checkouts(errors, text, "release")
    missing_jobs = sorted(REQUIRED_RELEASE_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"release workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "release",
        "tag and manual triggers",
        'tags: ["v*"]',
        "workflow_dispatch:",
    )
    if "reflex-xy-v" in text:
        errors.append(
            "release workflow must not touch the reflex-xy tag namespace — the "
            "adapter publishes via release-reflex-xy.yml (bare `v*` tags never "
            "match `reflex-xy-v*` and vice versa; keep it that way)"
        )
    _require_job_contains(
        errors,
        jobs,
        "wheels",
        "release",
        "cross-platform wheel matrix (glibc+musl, macOS, Windows), verification, and upload",
        "dtolnay/rust-toolchain@",
        "astral-sh/setup-uv@",
        "actions/setup-node@",
        'node-version: "22"',
        "npm ci",
        "cargo-zigbuild",
        "uv build --wheel",
        "XY_REQUIRE_CARGO",
        "XY_WHEEL_PLATFORM",
        "musllinux_1_2_x86_64",
        "win_arm64",
        "scripts/verify_wheel.py",
        "--expect-native",
        "Install-size budget (<= 15 MB)",
        "assert k.BACKEND=='native'",
        "actions/upload-artifact@",
        "dist/*.whl",
    )
    wheels_job = jobs.get("wheels", "")
    if "continue-on-error:" in wheels_job:
        errors.append(
            "release wheels job must block publishing when any native wheel build or "
            "verification fails"
        )
    _require_job_contains(
        errors,
        jobs,
        "wasm",
        "release",
        "runtime-verified, PyPI-published PyEmscripten WASM wheel",
        "permissions:",
        "contents: read",
        "toolchain: 1.97.0",
        "wasm32-unknown-emscripten",
        'RUSTFLAGS="-C panic=abort"',
        "pypa/cibuildwheel@294735312765b09d24a2fbec22660ce817587d55",
        "CIBW_PLATFORM: pyodide",
        "CIBW_BUILD: cp314-pyodide_wasm32",
        'CIBW_PYODIDE_VERSION: "314.0.0"',
        "CIBW_BEFORE_BUILD_PYODIDE",
        "CIBW_ENVIRONMENT_PYODIDE",
        "pyemscripten_2026_0_wasm32",
        "pyodide@314.0.0",
        "scripts/pyodide_load_smoke.py",
        "scripts/verify_wheel.py",
        "--expect-native",
        "wheelhouse/*.whl",
        "name: dist-pyemscripten",
    )
    wasm_job = jobs.get("wasm", "")
    if "continue-on-error:" in wasm_job:
        errors.append("release wasm job must block publishing when the Pyodide runtime probe fails")
    _require_job_contains(
        errors,
        jobs,
        "sdist",
        "release",
        "sdist build, content verification, no-Rust clear-error smoke, and upload",
        "astral-sh/setup-uv@",
        "actions/setup-node@",
        'node-version: "22"',
        "npm ci",
        "uv build --sdist",
        "scripts/verify_sdist.py",
        "XY_SKIP_CARGO",
        "native Rust core",
        "actions/upload-artifact@",
        "dist/*.tar.gz",
    )
    _require_job_contains(
        errors,
        jobs,
        "publish",
        "release",
        "trusted PyPI publishing from downloaded artifacts, gated by a dry-run switch "
        "and a tag/version/CHANGELOG agreement gate",
        "needs: [wheels, sdist, wasm]",
        "environment: pypi",
        "contents: read",
        "id-token: write",
        "scripts/check_release_version.py",
        "actions/download-artifact@",
        "pattern: dist-*",
        "merge-multiple: true",
        "dry_run",
        "Verify release tag source before PyPI",
        "pypa/gh-action-pypi-publish@",
        "packages-dir: dist/",
        "skip-existing: true",
    )
    _require_workflow_contains(
        errors,
        text,
        "release",
        "a workflow_dispatch dry-run input defaulting to true, so a manual run "
        "never accidentally publishes",
        "workflow_dispatch:",
        "dry_run:",
        "type: boolean",
        "default: true",
    )
    publish = jobs.get("publish", "")
    if "password:" in publish or "api-token" in publish:
        errors.append("release publish job should use trusted publishing, not a PyPI token")
    expected_publish_permissions = {"contents": "read", "id-token": "write"}
    if _job_mapping(publish, "permissions") != expected_publish_permissions:
        errors.append(
            f"release publish job permissions must be exactly {expected_publish_permissions!r}"
        )
    publish_tag_block = _named_step_blocks(publish).get("Verify release tag source before PyPI")
    publish_tag_shell = _named_step_run(publish, "Verify release tag source before PyPI")
    publish_action_position = publish.find("pypa/gh-action-pypi-publish@")
    publish_tag_position = publish.find("- name: Verify release tag source before PyPI")
    if publish_tag_block is None or publish_tag_shell is None:
        errors.append("release publish job must verify the current tag source before PyPI")
    else:
        publish_tag_lines = _shell_logical_lines(publish_tag_shell)
        lookup_tokens = [
            "timeout",
            "--signal=TERM",
            "--kill-after=5s",
            "30s",
            "gh",
            "api",
            "repos/${REPO}/commits/${TAG}",
            "--jq",
            ".sha",
        ]
        lookup_positions = [
            position
            for position, _, tokens in _shell_command_records(publish_tag_shell)
            if tokens == lookup_tokens
        ]
        if not (
            _step_scalar(publish_tag_block, "if") == "github.event_name == 'push'"
            and _assignment_lines(publish_tag_lines, "tag_source_sha")
            == ['if ! tag_source_sha="$(']
            and len(lookup_positions) == 1
            and _has_exact_tag_source_gate(
                publish_tag_lines,
                lookup_positions[0],
                failure_statement="exit 1",
            )
            and 0 <= publish_tag_position < publish_action_position
        ):
            errors.append(
                "release publish job must use one timeout-bounded, failing tag/SHA "
                "guard immediately before the PyPI publisher"
            )
    if "pypa/gh-action-pypi-publish@" in publish and not _step_carries_publish_gate(
        publish, "pypa/gh-action-pypi-publish@"
    ):
        errors.append(
            "release publish job's PyPI upload step is not gated by the dry-run "
            f"predicate on the step itself (`{PYPI_PUBLISH_GATE}`) — a missing or "
            "unrelated condition (e.g. `if: always()`) would let a manual "
            "dispatch publish unintentionally"
        )
    _require_job_contains(
        errors,
        jobs,
        "github-release",
        "release",
        "GitHub Release creation from downloaded verified distributions",
        "actions/download-artifact@",
        "pattern: dist-*",
        "merge-multiple: true",
        "GH_TOKEN: ${{ github.token }}",
        "Inspect existing release",
        "Prepare release provenance",
        "Attest release provenance",
        "Create GitHub Release and attach distributions",
    )
    github_release = jobs.get("github-release")
    if github_release is not None:
        job_steps = _job_step_blocks(github_release)
        protected_step_names = (
            "Inspect existing release",
            "Prepare release provenance",
            "Attest release provenance",
            "Create GitHub Release and attach distributions",
        )
        duplicate_protected_steps = [
            name
            for name in protected_step_names
            if sum(_step_name(step) == name for step in job_steps) != 1
        ]
        if duplicate_protected_steps:
            errors.append(
                "release github-release job must declare each protected step exactly once: "
                f"{duplicate_protected_steps}"
            )
        sibling_release_mutations = [
            _step_name(step) or "<unnamed>"
            for step in job_steps
            if _step_name(step) != "Create GitHub Release and attach distributions"
            and (shell := _step_run(step)) is not None
            and _has_gh_release_mutation(shell)
        ]
        if sibling_release_mutations:
            errors.append(
                "release github-release job must keep every GitHub Release mutation "
                "inside the structurally verified publication step; found writes in "
                f"{sibling_release_mutations}"
            )

        expected_gate = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
        if _job_scalar(github_release, "if") != expected_gate:
            errors.append(
                "release github-release job must use the active tag-only gate "
                f"`if: {expected_gate}`"
            )
        if _job_scalar(github_release, "needs") != "publish":
            errors.append("release github-release job must actively declare `needs: publish`")
        if _job_scalar(github_release, "timeout-minutes") != "30":
            errors.append(
                "release github-release job must retain its 30-minute network-failure timeout"
            )
        permissions = _job_mapping(github_release, "permissions")
        expected_permissions = {
            "attestations": "write",
            "artifact-metadata": "write",
            "contents": "write",
            "id-token": "write",
        }
        if permissions != expected_permissions:
            errors.append(
                "release github-release job permissions must be exactly "
                f"{expected_permissions!r}, found {permissions!r}"
            )

        step_blocks = _named_step_blocks(github_release)
        inspect_shell = _named_step_run(github_release, "Inspect existing release")
        if inspect_shell is None:
            errors.append("release github-release job is missing immutable-release preflight")
        else:
            missing = _missing_needles(
                inspect_shell,
                (
                    'gh release view "$TAG"',
                    "--json isImmutable",
                    "immutable=true",
                    'echo "immutable=${immutable}" >> "$GITHUB_OUTPUT"',
                ),
            )
            if missing:
                errors.append(f"release immutable-release preflight is incomplete: {missing}")
            inspect_tokens = [
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "gh",
                "release",
                "view",
                "$TAG",
                "--repo",
                "$REPO",
                "--json",
                "isImmutable",
                "2>/dev/null",
            ]
            inspect_commands = [
                tokens for _, _, tokens in _shell_command_records(inspect_shell) if "gh" in tokens
            ]
            if inspect_commands != [inspect_tokens]:
                errors.append(
                    "release immutable-release preflight must use one exact "
                    "30-second timeout-bounded metadata read"
                )

        immutable_skip = "steps.release_state.outputs.immutable != 'true'"
        prepare_block = step_blocks.get("Prepare release provenance")
        prepare_shell = _named_step_run(github_release, "Prepare release provenance")
        if prepare_block is None or prepare_shell is None:
            errors.append("release github-release job is missing active provenance preparation")
        else:
            if _step_scalar(prepare_block, "if") != immutable_skip:
                errors.append(
                    "release provenance preparation must skip pre-existing immutable releases"
                )
            required_prepare_shell = (
                "shopt -s nullglob",
                "wheels=(dist/*.whl)",
                "sdists=(dist/*.tar.gz)",
                'artifacts=("${wheels[@]}" "${sdists[@]}")',
                "if (( ${#wheels[@]} == 0 || ${#sdists[@]} != 1 )); then\n"
                '  echo "::error::Expected at least one wheel and exactly one sdist"\n'
                "  exit 1\n"
                "fi",
                "distributions_json=",
                'sha256sum "$artifact"',
                "timeout --signal=TERM --kill-after=5s 30s",
                "gh api \"repos/${REPO}/commits/${TAG}\" --jq '.sha'",
                '"$tag_source_sha" != "$GITHUB_SHA"',
                "pypi_hashes_json=",
                "{name: .filename, sha256: .digests.sha256}",
                ".yanked == false",
                '"$pypi_hashes_json" == "$distributions_json"',
                '"repos/${REPO}/releases/generate-notes"',
                '-f tag_name="$TAG"',
                'generated_notes="$(<"$notes_file")"',
                'if [[ -z "${generated_notes//[[:space:]]/}" ]]; then\n'
                '  echo "::error::GitHub generated empty release notes for ${TAG}"\n'
                "  exit 1\n"
                "fi",
                '"xy-release-provenance/v1"',
                '--arg source_sha "$GITHUB_SHA"',
                "release_notes_sha256:",
                "distributions:",
                "xy-release-provenance.json",
                "<!-- xy-release-provenance:v1:%s:sha256:%s -->",
            )
            missing = _missing_needles(prepare_shell, required_prepare_shell)
            if missing:
                errors.append(
                    "release provenance preparation must bind generated notes and exact "
                    f"distribution hashes to the tag source: {missing}"
                )
            prepare_lines = _shell_logical_lines(prepare_shell)
            prepare_records = _shell_command_records(prepare_shell)
            tag_lookup_tokens = [
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "gh",
                "api",
                "repos/${REPO}/commits/${TAG}",
                "--jq",
                ".sha",
            ]
            tag_lookup_positions = [
                position for position, _, tokens in prepare_records if tokens == tag_lookup_tokens
            ]
            pypi_flow_valid, pypi_guard_position = _has_exact_pypi_gate_flow(
                prepare_lines,
                version_variable="pypi_version",
                expected_hashes_variable="$distributions_json",
            )
            pypi_projection = re.search(
                r"\[\s*\.urls\[\]\s*\|\s*"
                r"\{name:\s*\.filename,\s*sha256:\s*\.digests\.sha256\}\s*\]\s*"
                r"\|\s*sort_by\(\.name\)",
                prepare_shell,
            )
            pypi_policy = re.search(
                r"all\(\.urls\[\];\s*"
                r"\.yanked\s*==\s*false\s+and\s*"
                r"\(\.filename\s*\|\s*"
                r"endswith\(\"\.whl\"\)\s+or\s+endswith\(\"\.tar\.gz\"\)\)\s+and\s*"
                r"\(\.digests\.sha256\s*\|\s*"
                r"type\s*==\s*\"string\"\s+and\s*"
                r"test\(\"\^\[0-9a-f\]\{64\}\$\"\)\)\)",
                prepare_shell,
            )
            generated_notes_tokens = [
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "gh",
                "api",
                "--method",
                "POST",
                "repos/${REPO}/releases/generate-notes",
                "-f",
                "tag_name=$TAG",
                "--jq",
                ".body",
                ">",
                "$notes_file",
            ]
            generated_notes_positions = [
                position
                for position, _, tokens in prepare_records
                if tokens == generated_notes_tokens
            ]
            tag_guard_call_positions = [
                position
                for position, line in enumerate(prepare_lines)
                if line == "verify_tag_source"
            ]
            if not (
                _assignment_lines(prepare_lines, "tag_source_sha") == ['if ! tag_source_sha="$(']
                and _shell_function_definition_count(prepare_shell, "verify_tag_source") == 1
                and len(tag_lookup_positions) == 1
                and _has_exact_tag_source_function(
                    prepare_lines,
                    tag_lookup_positions[0],
                )
                and tag_guard_call_positions
                == [tag_lookup_positions[0] + 10, len(prepare_lines) - 1]
                and pypi_flow_valid
                and pypi_projection is not None
                and pypi_policy is not None
                and len(generated_notes_positions) == 1
                and tag_guard_call_positions[0]
                < pypi_guard_position
                < generated_notes_positions[0]
                < tag_guard_call_positions[1]
            ):
                errors.append(
                    "release provenance preparation must independently bind one reusable, "
                    "timeout-bounded tag guard before PyPI, a malformed-response-safe exact "
                    "all-file PyPI gate, and a fresh final tag guard before attesting"
                )

        attest_block = step_blocks.get("Attest release provenance")
        attest_pin = "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d"
        if attest_block is None:
            errors.append("release github-release job is missing provenance attestation")
        else:
            if _step_scalar(attest_block, "if") != immutable_skip:
                errors.append(
                    "release provenance attestation must skip pre-existing immutable releases"
                )
            attest_uses = _step_scalar(attest_block, "uses")
            if attest_uses is None or attest_uses.split(" #", 1)[0] != attest_pin:
                errors.append(
                    "release provenance attestation must use the pinned actions/attest v4 action"
                )
            if not re.search(
                r"^          subject-path:\s*"
                r"\$\{\{ runner\.temp \}\}/xy-\$\{\{ github\.ref_name \}\}"
                r"-release-provenance/xy-release-provenance\.json\s*$",
                attest_block,
                re.MULTILINE,
            ):
                errors.append("release provenance attestation must sign the prepared manifest path")
        protected_step_order = [
            "Prepare release provenance",
            "Attest release provenance",
            "Create GitHub Release and attach distributions",
        ]
        named_step_order = list(step_blocks)
        if not all(name in named_step_order for name in protected_step_order) or not (
            named_step_order.index(protected_step_order[0])
            < named_step_order.index(protected_step_order[1])
            < named_step_order.index(protected_step_order[2])
        ):
            errors.append(
                "release provenance must be prepared and gated before attestation, then published"
            )

        release_shell = _named_step_run(
            github_release,
            "Create GitHub Release and attach distributions",
        )
        if release_shell is None:
            errors.append(
                "release github-release job is missing the active release publication shell step"
            )
        else:
            required_shell = (
                "shopt -s nullglob",
                "wheels=(dist/*.whl)",
                "sdists=(dist/*.tar.gz)",
                'artifacts=("${wheels[@]}" "${sdists[@]}")',
                "if (( ${#wheels[@]} == 0 || ${#sdists[@]} != 1 )); then\n"
                '  echo "::error::Expected at least one wheel and exactly one sdist"\n'
                "  exit 1\n"
                "fi",
                "verify_tag_source() {",
                "timeout --signal=TERM --kill-after=5s 30s",
                "gh api \"repos/${REPO}/commits/${TAG}\" --jq '.sha'",
                '"$tag_source_sha" != "$GITHUB_SHA"',
                "return 1",
                f'if [[ "$TAG" =~ {CORE_PRERELEASE_TAG_PATTERN} ]]; then',
                "prerelease=(--prerelease)",
                "edit_prerelease=(--prerelease)",
                "expected_prerelease=true",
                '"${edit_prerelease[@]}"',
                '"${prerelease[@]}"',
                "expected_assets_json=",
                "expected_hashes_json=",
                "pypi_hashes_json=",
                "{name: .filename, sha256: .digests.sha256}",
                ".yanked == false",
                '"$pypi_hashes_json" == "$expected_hashes_json"',
                'if [[ "$pypi_matches" != true ]]; then\n'
                '  echo "::error::PyPI files for ${TAG} do not exactly match the verified build"\n'
                "  exit 1\n"
                "fi",
                'provenance_name="xy-release-provenance.json"',
                'gh release upload "$TAG" "${artifacts[@]}" "$provenance_file"',
                'gh release create "$TAG" "${artifacts[@]}" "$provenance_file"',
                "--verify-tag",
                "--prerelease=false",
                "index($name) != null",
                '.assets[] | select(.name | endswith(".whl") or endswith(".tar.gz"))',
                '"repos/${REPO}/releases/assets/${asset_id}"',
                '--notes-file "$notes_file"',
                "isImmutable",
                "publishedAt",
                "tagName",
                "actual_assets_json=",
                'gh release download "$TAG"',
                "timeout --signal=TERM --kill-after=5s 180s",
                'gh attestation verify "$verified_provenance"',
                "timeout --signal=TERM --kill-after=5s 60s",
                '--signer-workflow "${REPO}/.github/workflows/release.yml"',
                '--source-ref "refs/tags/${TAG}"',
                '--source-digest "$GITHUB_SHA"',
                "--deny-self-hosted-runners",
                "actual_hashes_json=",
                "manifest_hashes_json=",
                "reference_assets_json=",
                '"$actual_assets_json" != "$reference_assets_json"',
                '"$actual_hashes_json" != "$reference_hashes_json"',
                '"$manifest_hashes_json" != "$reference_hashes_json"',
                'verify_release_payload "$release_json" "$pypi_hashes_json"',
                'verify_release_payload "$release_json" "$expected_hashes_json"',
                "<!-- xy-release-provenance:v1:${TAG}:sha256:${manifest_sha256} -->",
                '"$actual_notes_sha256" != "$manifest_notes_sha256"',
                "--draft=false",
                "--clobber",
            )
            missing = _missing_needles(release_shell, required_shell)
            if missing:
                errors.append(
                    "release github-release job missing retry-safe artifact, metadata, "
                    f"prerelease, hash, or signed-provenance behavior: {missing}"
                )

            logical_lines = _shell_logical_lines(release_shell)
            command_records = _shell_command_records(release_shell)
            upload_commands = [
                (position, tokens)
                for position, _, tokens in command_records
                if tokens[:3] == ["gh", "release", "upload"]
            ]
            create_commands = [
                (position, tokens)
                for position, _, tokens in command_records
                if tokens[:3] == ["gh", "release", "create"]
            ]
            valid_upload = len(upload_commands) == 1 and upload_commands[0][1] == [
                "gh",
                "release",
                "upload",
                "$TAG",
                "${artifacts[@]}",
                "$provenance_file",
                "--repo",
                "$REPO",
                "--clobber",
            ]
            valid_create = len(create_commands) == 1 and create_commands[0][1] == [
                "gh",
                "release",
                "create",
                "$TAG",
                "${artifacts[@]}",
                "$provenance_file",
                "--repo",
                "$REPO",
                "--verify-tag",
                "--title",
                "$TAG",
                "--notes-file",
                "$notes_file",
                "${prerelease[@]}",
            ]
            if not valid_upload or not valid_create:
                errors.append(
                    "release github-release job must pass verified distributions and "
                    "provenance directly to one active upload command (with exact "
                    '`--repo "$REPO"` and `--clobber` arguments) and one active '
                    'create command (with exact `--repo "$REPO"`, `--verify-tag`, '
                    'and `--notes-file "$notes_file"` arguments)'
                )

            classifier = f'if [[ "$TAG" =~ {CORE_PRERELEASE_TAG_PATTERN} ]]; then'
            active_lines = [
                line.strip().removesuffix("\\").rstrip()
                for line in release_shell.splitlines()
                if line.strip()
            ]
            for assignment in (
                classifier,
                "prerelease=(--prerelease)",
                "edit_prerelease=(--prerelease)",
                "expected_prerelease=true",
            ):
                if assignment not in active_lines:
                    errors.append(
                        "release github-release job must actively classify canonical "
                        f"alpha/beta/RC tags; missing {assignment!r}"
                    )

            metadata_read_positions = [
                position
                for position, _, tokens in command_records
                if _is_release_metadata_read(tokens)
            ]
            payload_verification_positions = [
                position
                for position, _, tokens in command_records
                if _is_release_payload_verification(tokens)
            ]
            upload_position = upload_commands[0][0] if len(upload_commands) == 1 else -1
            create_position = create_commands[0][0] if len(create_commands) == 1 else -1
            edit_positions = [
                position
                for position, _, tokens in command_records
                if tokens
                == [
                    "gh",
                    "release",
                    "edit",
                    "$TAG",
                    "--repo",
                    "$REPO",
                    "--draft=false",
                    "--title",
                    "$TAG",
                    "--notes-file",
                    "$notes_file",
                    "${edit_prerelease[@]}",
                ]
            ]
            edit_position = edit_positions[0] if len(edit_positions) == 1 else -1
            prune_positions = [
                position
                for position, _, tokens in command_records
                if tokens
                == [
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    "repos/${REPO}/releases/assets/${asset_id}",
                ]
            ]
            prune_position = prune_positions[0] if len(prune_positions) == 1 else -1
            initial_view_positions = [
                position for position in metadata_read_positions if position < upload_position
            ]
            initial_view_position = initial_view_positions[-1] if initial_view_positions else -1
            uploaded_view_position = next(
                (
                    position
                    for position in metadata_read_positions
                    if upload_position < position < prune_position
                ),
                -1,
            )
            normalized_view_position = next(
                (
                    position
                    for position in metadata_read_positions
                    if edit_position < position < create_position
                ),
                -1,
            )
            normalized_verify_position = next(
                (
                    position
                    for position in payload_verification_positions
                    if normalized_view_position < position < create_position
                ),
                -1,
            )
            created_view_position = next(
                (position for position in metadata_read_positions if position > create_position),
                -1,
            )
            created_verify_position = next(
                (
                    position
                    for position in payload_verification_positions
                    if position > created_view_position
                ),
                -1,
            )
            if not (
                0
                <= initial_view_position
                < upload_position
                < uploaded_view_position
                < prune_position
                < edit_position
                < normalized_view_position
                < normalized_verify_position
                < create_position
                and _has_guarded_release_validation(logical_lines, normalized_view_position)
            ):
                errors.append(
                    "release github-release job recovery must inspect, upload, re-read, "
                    "prune stale assets by id, edit metadata last, re-read, and validate again"
                )
            if not (
                0 <= create_position < created_view_position < created_verify_position
                and _has_guarded_release_validation(logical_lines, created_view_position)
            ):
                errors.append(
                    "release github-release job creation must re-read complete metadata "
                    "and validate again with the active signed-payload check"
                )

            tag_lookup_tokens = [
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "gh",
                "api",
                "repos/${REPO}/commits/${TAG}",
                "--jq",
                ".sha",
            ]
            tag_resolution_positions = [
                position for position, _, tokens in command_records if tokens == tag_lookup_tokens
            ]
            pypi_flow_valid, pypi_guard_position = _has_exact_pypi_gate_flow(
                logical_lines,
                version_variable="pypi_version",
                expected_hashes_variable="$expected_hashes_json",
                immutable_variable="$is_immutable",
            )
            pypi_projection = re.search(
                r"\[\s*\.urls\[\]\s*\|\s*"
                r"\{name:\s*\.filename,\s*sha256:\s*\.digests\.sha256\}\s*\]\s*"
                r"\|\s*sort_by\(\.name\)",
                release_shell,
            )
            pypi_policy = re.search(
                r"all\(\.urls\[\];\s*"
                r"\.yanked\s*==\s*false\s+and\s*"
                r"\(\.filename\s*\|\s*"
                r"endswith\(\"\.whl\"\)\s+or\s+endswith\(\"\.tar\.gz\"\)\)\s+and\s*"
                r"\(\.digests\.sha256\s*\|\s*"
                r"type\s*==\s*\"string\"\s+and\s*"
                r"test\(\"\^\[0-9a-f\]\{64\}\$\"\)\)\)",
                release_shell,
            )
            mutation_positions = [
                position
                for position in (
                    upload_position,
                    prune_position,
                    edit_position,
                    create_position,
                )
                if position >= 0
            ]
            first_mutation_position = min(mutation_positions, default=-1)
            pre_guard_github_commands = [
                (position, tokens)
                for position, _, tokens in command_records
                if position < pypi_guard_position and any(token == "gh" for token in tokens)
            ]
            allowed_release_subcommands = {"create", "download", "edit", "upload", "view"}
            unknown_release_commands = [
                tokens
                for _, _, tokens in command_records
                for index in range(len(tokens) - 2)
                if tokens[index : index + 2] == ["gh", "release"]
                and tokens[index + 2] not in allowed_release_subcommands
            ]
            immutable_payload_positions = [
                position
                for position in payload_verification_positions
                if position < upload_position
                and _shell_tokens(logical_lines[position])
                == [
                    "verify_release_payload",
                    "$release_json",
                    "$pypi_hashes_json",
                    ";",
                    "then",
                ]
            ]
            download_tokens = [
                "if",
                "!",
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "180s",
                "gh",
                "release",
                "download",
                "$TAG",
                "--repo",
                "$REPO",
                "--dir",
                "$verify_dir",
                "--pattern",
                "*.whl",
                "--pattern",
                "*.tar.gz",
                "--pattern",
                "$provenance_name",
                ";",
                "then",
            ]
            attestation_tokens = [
                "if",
                "!",
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "60s",
                "gh",
                "attestation",
                "verify",
                "$verified_provenance",
                "--repo",
                "$REPO",
                "--signer-workflow",
                "${REPO}/.github/workflows/release.yml",
                "--source-ref",
                "refs/tags/${TAG}",
                "--source-digest",
                "$GITHUB_SHA",
                "--deny-self-hosted-runners",
                ">/dev/null",
                ";",
                "then",
            ]
            guarded_mutations = len(mutation_positions) == 4 and all(
                _logical_line_is(logical_lines, position - 1, "verify_tag_source")
                for position in mutation_positions
            )
            successful_terminations_are_exact = (
                len(immutable_payload_positions) == 1
                and normalized_view_position >= 0
                and _shell_maybe_successful_terminations(logical_lines)
                == [
                    (immutable_payload_positions[0] + 3, 0, "exit", "0"),
                    (normalized_view_position + 8, 0, "exit", "0"),
                ]
            )
            if not successful_terminations_are_exact:
                errors.append(
                    "release github-release job must allow only its two exact "
                    "tag-guarded `exit 0` sites and no additional potentially "
                    "successful termination commands"
                )
            guarded_successes = (
                len(immutable_payload_positions) == 1
                and _logical_line_is(
                    logical_lines,
                    immutable_payload_positions[0] + 1,
                    "verify_tag_source",
                )
                and _logical_line_is(
                    logical_lines,
                    immutable_payload_positions[0] + 3,
                    "exit 0",
                )
                and _logical_line_is(
                    logical_lines,
                    normalized_view_position + 7,
                    "verify_tag_source",
                )
                and _logical_line_is(
                    logical_lines,
                    normalized_view_position + 8,
                    "exit 0",
                )
                and _logical_line_is(
                    logical_lines,
                    created_view_position + 7,
                    "verify_tag_source",
                )
                and logical_lines[-1:] == ["verify_tag_source"]
                and successful_terminations_are_exact
            )
            network_verification_is_bounded = (
                sum(tokens == download_tokens for _, _, tokens in command_records) == 1
                and sum(tokens == attestation_tokens for _, _, tokens in command_records) == 1
                and len(metadata_read_positions) == 4
            )
            immutable_state_is_exact = (
                _assignment_lines(logical_lines, "release_exists")
                == ["release_exists=false", "release_exists=true"]
                and _assignment_lines(logical_lines, "is_immutable")
                == [
                    "is_immutable=false",
                    'is_immutable="$(jq -r \'.isImmutable\' <<<"$release_json")"',
                ]
                and _logical_line_is(
                    logical_lines,
                    initial_view_position - 1,
                    'if release_json="$(',
                )
                and _logical_line_is(logical_lines, initial_view_position + 1, ')"; then')
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 2,
                    "release_exists=true",
                )
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 3,
                    'is_immutable="$(jq -r \'.isImmutable\' <<<"$release_json")"',
                )
                and _logical_line_is(logical_lines, initial_view_position + 4, "fi")
                and logical_lines.count('if [[ "$release_exists" == true ]]; then') == 1
                and logical_lines.count('if [[ "$is_immutable" == "true" ]]; then') == 1
            )
            if not (
                len(tag_resolution_positions) == 1
                and _assignment_lines(logical_lines, "tag_source_sha")
                == ['if ! tag_source_sha="$(']
                and _shell_function_definition_count(release_shell, "verify_tag_source") == 1
                and _has_exact_tag_source_function(
                    logical_lines,
                    tag_resolution_positions[0] if tag_resolution_positions else -1,
                )
                and pypi_flow_valid
                and pypi_projection is not None
                and pypi_policy is not None
                and _assignment_lines(logical_lines, "expected_hashes_json")
                == ['expected_hashes_json="$(']
                and pre_guard_github_commands
                == [
                    (tag_resolution_positions[0], tag_lookup_tokens),
                    (initial_view_position, _shell_tokens(logical_lines[initial_view_position])),
                ]
                and not unknown_release_commands
                and 0 <= pypi_guard_position < first_mutation_position
                and _logical_line_is(
                    logical_lines,
                    tag_resolution_positions[0] + 10,
                    "verify_tag_source",
                )
                and tag_resolution_positions[0] + 10 < initial_view_position
                and guarded_mutations
                and guarded_successes
                and network_verification_is_bounded
                and immutable_state_is_exact
            ):
                errors.append(
                    "release github-release job must define one timeout-bounded tag guard, "
                    "require a malformed-response-safe exact non-yanked all-file PyPI gate, "
                    "reject pre-gate API writes, recheck the tag at every mutation/success "
                    "boundary, and bound every release read/verification"
                )
    return errors


def validate_docs_deploy_workflow(path: Path = DEFAULT_DOCS_DEPLOY_WORKFLOW) -> list[str]:
    """Keep production promotion behind a complete, published library release."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read docs deploy workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_job_contains(
        errors,
        jobs,
        "verify-library-release",
        "docs deploy",
        "published GitHub Release metadata, generated notes, distribution assets, "
        "and PyPI availability before production promotion",
        "needs: [prepare, await-prod-approval]",
        "permissions:",
        "contents: read",
        "Await GitHub Release and PyPI availability",
    )
    release_gate = jobs.get("verify-library-release")
    if release_gate is None:
        return errors
    if _job_scalar(release_gate, "needs") != "[prepare, await-prod-approval]":
        errors.append(
            "docs deploy verify-library-release job must actively depend on "
            "prepare and production approval"
        )
    expected_permissions = {"attestations": "read", "contents": "read"}
    if _job_mapping(release_gate, "permissions") != expected_permissions:
        errors.append(
            "docs deploy verify-library-release permissions must be exactly "
            f"{expected_permissions!r}"
        )

    production = jobs.get("helm-pr-prod")
    if production is None:
        errors.append("docs deploy workflow is missing the production Helm promotion job")
    elif _job_scalar(production, "needs") != (
        "[prepare, await-prod-approval, verify-library-release]"
    ):
        errors.append(
            "docs deploy production Helm promotion must actively depend on verify-library-release"
        )

    gate_step = _named_step_blocks(release_gate).get("Await GitHub Release and PyPI availability")
    gate_shell = _named_step_run(
        release_gate,
        "Await GitHub Release and PyPI availability",
    )
    if gate_step is None or gate_shell is None:
        errors.append("docs deploy release gate is missing its active polling shell step")
        return errors
    if not re.search(
        r"^          SOURCE_SHA:\s*"
        r"\$\{\{ needs\.prepare\.outputs\.source_sha \}\}\s*$",
        gate_step,
        re.MULTILINE,
    ):
        errors.append("docs deploy release gate must use the prepared exact source SHA")

    required = (
        "shopt -s nullglob",
        'PROVENANCE_NAME="xy-release-provenance.json"',
        "MAX_ATTEMPTS=30",
        "POLL_INTERVAL_SECONDS=60",
        "POLL_DEADLINE=$((SECONDS + 30 * 60))",
        "verify_tag_source() {",
        "timeout --signal=TERM --kill-after=5s 30s",
        "EXPECTED_PRERELEASE=false",
        f'if [[ "$VERSION" =~ {CORE_PRERELEASE_TAG_PATTERN} ]]; then',
        "EXPECTED_PRERELEASE=true",
        'gh release view "$VERSION"',
        "--json assets,body,isDraft,isPrerelease,name,publishedAt,tagName",
        ".isDraft == false",
        ".name == $name",
        ".tagName == $name",
        ".publishedAt != null",
        ".isPrerelease == $prerelease",
        'any(.assets[]?; .name | endswith(".whl"))',
        '([.assets[]? | select(.name | endswith(".tar.gz"))] | length) == 1',
        'select(.name == "xy-release-provenance.json")',
        "all(.urls[]; .yanked == false)",
        "all(.urls[];",
        ".filename |",
        'endswith(".whl") or endswith(".tar.gz")',
        'gh release download "$VERSION"',
        'gh attestation verify "$provenance_file"',
        '--signer-workflow "${REPO}/.github/workflows/release.yml"',
        '--source-ref "refs/tags/${VERSION}"',
        '--source-digest "$SOURCE_SHA"',
        "--deny-self-hosted-runners",
        "xy-release-provenance/v1",
        "release_notes_sha256",
        "manifest_sha256=",
        "<!-- xy-release-provenance:v1:${VERSION}:sha256:${manifest_sha256} -->",
        "github_hashes_json=",
        "manifest_hashes_json=",
        "pypi_hashes_json=",
        ".digests.sha256",
        '"$github_hashes_json" == "$manifest_hashes_json"',
        '"$github_hashes_json" == "$pypi_hashes_json"',
        'if [[ "$RELEASED" == true &&',
        '"$PUBLISHED" == true &&',
        '"$PROVENANCE_VALID" == true &&',
        '"$ASSETS_MATCH" == true ]] &&',
        "verify_tag_source; then",
        "TAG_MATCH=true",
        '"$TAG_MATCH" == true ]]; then',
        'rm -rf -- "$verify_dir"',
        "if (( attempt == MAX_ATTEMPTS )); then",
        'echo "${status}; no retries remain"',
        "remaining_seconds=$((POLL_DEADLINE - SECONDS))",
        'sleep "$sleep_seconds"',
    )
    missing = _missing_needles(gate_shell, required)
    if missing:
        errors.append(
            "docs deploy release gate must require expected non-draft metadata, "
            f"signed notes provenance, non-yanked PyPI files, and exact asset hashes: {missing}"
        )

    logical_lines = _shell_logical_lines(gate_shell)
    command_records = _shell_command_records(gate_shell)
    timeout = _job_scalar(release_gate, "timeout-minutes")
    deadline_matches = re.findall(
        r"^POLL_DEADLINE=\$\(\(SECONDS \+ ([0-9]+) \* 60\)\)$",
        gate_shell,
        re.MULTILINE,
    )
    timeout_minutes = int(timeout) if timeout is not None and timeout.isdigit() else 0
    deadline_minutes = int(deadline_matches[0]) if len(deadline_matches) == 1 else 0
    gross_headroom_seconds = (timeout_minutes - deadline_minutes) * 60
    # Include each timeout's five-second TERM→KILL grace plus the final fresh
    # tag lookup after release/asset/attestation verification.
    worst_case_attempt_seconds = 35 + 20 + 185 + 65 + 35
    protected_timing_assignments = (
        _assignment_lines(logical_lines, "MAX_ATTEMPTS") == ["MAX_ATTEMPTS=30"]
        and _assignment_lines(logical_lines, "POLL_INTERVAL_SECONDS")
        == ["POLL_INTERVAL_SECONDS=60"]
        and _assignment_lines(logical_lines, "POLL_DEADLINE")
        == ["POLL_DEADLINE=$((SECONDS + 30 * 60))"]
    )
    if not (
        timeout_minutes == 45
        and deadline_minutes == 30
        and protected_timing_assignments
        and gross_headroom_seconds >= 10 * 60
        and gross_headroom_seconds - worst_case_attempt_seconds >= 5 * 60
    ):
        errors.append(
            "docs deploy verify-library-release job must retain one 30-minute polling "
            "deadline inside its 45-minute timeout, with ten minutes gross and five "
            "minutes beyond a worst-case bounded network attempt"
        )

    pypi_supported_policy = re.search(
        r"all\(\.urls\[\];\s*"
        r"\.filename\s*\|\s*"
        r"endswith\(\"\.whl\"\)\s+or\s+endswith\(\"\.tar\.gz\"\)\)",
        gate_shell,
    )
    pypi_all_files_projection = re.search(
        r"\[\s*\.urls\[\]\s*\|\s*"
        r"\{name:\s*\.filename,\s*sha256:\s*\.digests\.sha256\}\s*\]\s*"
        r"\|\s*sort_by\(\.name\)",
        gate_shell,
    )
    if pypi_supported_policy is None or pypi_all_files_projection is None:
        errors.append(
            "docs deploy release gate must reject unsupported PyPI filenames and "
            "compare an unfiltered all-file `.urls[]` filename/digest projection"
        )

    tag_lookup_tokens = [
        "timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "30s",
        "gh",
        "api",
        "repos/${REPO}/commits/${VERSION}",
        "--jq",
        ".sha",
    ]
    release_view_tokens = [
        "timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "30s",
        "gh",
        "release",
        "view",
        "$VERSION",
        "--repo",
        "$REPO",
        "--json",
        "assets,body,isDraft,isPrerelease,name,publishedAt,tagName",
        "2>/dev/null",
    ]
    pypi_fetch_tokens = [
        "curl",
        "-fsS",
        "--connect-timeout",
        "5",
        "--max-time",
        "20",
        "https://pypi.org/pypi/xy/${PYPI_VERSION}/json",
        "2>/dev/null",
    ]
    release_download_tokens = [
        "if",
        "timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "180s",
        "gh",
        "release",
        "download",
        "$VERSION",
        "--repo",
        "$REPO",
        "--dir",
        "$verify_dir",
        "--pattern",
        "*.whl",
        "--pattern",
        "*.tar.gz",
        "--pattern",
        "$PROVENANCE_NAME",
        ";",
        "then",
    ]
    attestation_tokens = [
        "timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "60s",
        "gh",
        "attestation",
        "verify",
        "$provenance_file",
        "--repo",
        "$REPO",
        "--signer-workflow",
        "${REPO}/.github/workflows/release.yml",
        "--source-ref",
        "refs/tags/${VERSION}",
        "--source-digest",
        "$SOURCE_SHA",
        "--deny-self-hosted-runners",
        ">/dev/null",
        "&&",
    ]
    network_positions = {
        "tag": [position for position, _, tokens in command_records if tokens == tag_lookup_tokens],
        "view": [
            position for position, _, tokens in command_records if tokens == release_view_tokens
        ],
        "pypi": [
            position for position, _, tokens in command_records if tokens == pypi_fetch_tokens
        ],
        "download": [
            position for position, _, tokens in command_records if tokens == release_download_tokens
        ],
        "attest": [
            position for position, _, tokens in command_records if tokens == attestation_tokens
        ],
    }
    pypi_fetch_position = (
        network_positions["pypi"][0] if len(network_positions["pypi"]) == 1 else -1
    )
    pypi_flow_is_direct = (
        _assignment_lines(logical_lines, "pypi_json") == ['if pypi_json="$(']
        and _assignment_lines(logical_lines, "pypi_hashes_json") == ['pypi_hashes_json="$(']
        and _logical_line_is(
            logical_lines,
            pypi_fetch_position - 1,
            'if pypi_json="$(',
        )
        and _logical_line_is(logical_lines, pypi_fetch_position + 1, ')"; then')
    )
    tag_lookup_position = network_positions["tag"][0] if len(network_positions["tag"]) == 1 else -1
    tag_function_is_exact = (
        _has_exact_docs_tag_source_function(
            logical_lines,
            tag_lookup_position,
        )
        and _shell_function_definition_count(gate_shell, "verify_tag_source") == 1
    )
    tag_verification_positions = [
        position for position, line in enumerate(logical_lines) if line == "verify_tag_source; then"
    ]
    tag_verification_position = (
        tag_verification_positions[0] if len(tag_verification_positions) == 1 else -1
    )
    tag_state_is_fresh = (
        _assignment_lines(logical_lines, "TAG_MATCH") == ["TAG_MATCH=false", "TAG_MATCH=true"]
        and _logical_line_is(
            logical_lines,
            tag_verification_position - 4,
            'if [[ "$RELEASED" == true &&',
        )
        and _logical_line_is(
            logical_lines,
            tag_verification_position - 3,
            '"$PUBLISHED" == true &&',
        )
        and _logical_line_is(
            logical_lines,
            tag_verification_position - 2,
            '"$PROVENANCE_VALID" == true &&',
        )
        and _logical_line_is(
            logical_lines,
            tag_verification_position - 1,
            '"$ASSETS_MATCH" == true ]] &&',
        )
        and _logical_line_is(
            logical_lines,
            tag_verification_position + 1,
            "TAG_MATCH=true",
        )
        and _logical_line_is(logical_lines, tag_verification_position + 2, "fi")
    )
    readiness_success_block = [
        'if [[ "$RELEASED" == true &&',
        '"$PUBLISHED" == true &&',
        '"$PROVENANCE_VALID" == true &&',
        '"$ASSETS_MATCH" == true &&',
        '"$TAG_MATCH" == true ]]; then',
        'echo "::notice::${VERSION} has signed release provenance and '
        'byte-identical, non-yanked GitHub/PyPI distributions"',
        "exit 0",
        "fi",
    ]
    readiness_success_positions = [
        position
        for position in range(len(logical_lines) - len(readiness_success_block) + 1)
        if logical_lines[position : position + len(readiness_success_block)]
        == readiness_success_block
    ]
    readiness_success_is_exact = len(
        readiness_success_positions
    ) == 1 and _shell_maybe_successful_terminations(logical_lines) == [
        (readiness_success_positions[0] + 6, 0, "exit", "0")
    ]
    if not readiness_success_is_exact:
        errors.append(
            "docs deploy release gate must have exactly one readiness-bound "
            "`exit 0` and no other potentially successful termination commands"
        )
    readiness_assignments_are_exact = all(
        _assignment_lines(logical_lines, name) == [f"{name}=false", f"{name}=true"]
        for name in (
            "RELEASED",
            "PUBLISHED",
            "PROVENANCE_VALID",
            "ASSETS_MATCH",
            "TAG_MATCH",
        )
    )
    network_calls_are_bounded = all(
        len(network_positions[name]) == 1 for name in ("tag", "view", "pypi", "download", "attest")
    )
    if not (
        pypi_flow_is_direct
        and tag_function_is_exact
        and tag_state_is_fresh
        and readiness_success_is_exact
        and readiness_assignments_are_exact
        and network_calls_are_bounded
    ):
        errors.append(
            "docs deploy release gate must bind one unfiltered bounded PyPI response, "
            "use exact timeout-bounded release/tag/attestation calls, and derive every "
            "fresh readiness flag only through its protected control flow"
        )

    early_deadline_position = gate_shell.find("if (( SECONDS >= POLL_DEADLINE )); then")
    release_poll_position = gate_shell.find('gh release view "$VERSION"')
    final_attempt_position = gate_shell.find("if (( attempt == MAX_ATTEMPTS )); then")
    remaining_position = gate_shell.find("remaining_seconds=$((POLL_DEADLINE - SECONDS))")
    exhausted_deadline_position = gate_shell.find("if (( remaining_seconds <= 0 )); then")
    bounded_sleep_position = gate_shell.find('sleep "$sleep_seconds"')
    final_error_position = gate_shell.find('echo "::error::${VERSION} did not become release-ready')
    early_deadline_guard = re.search(
        r"if \(\( SECONDS >= POLL_DEADLINE \)\); then\s*"
        r'echo "::warning::release-readiness polling deadline reached '
        r'before attempt \$\{attempt\}"\s*'
        r"break\s*fi",
        gate_shell,
    )
    final_attempt_guard = re.search(
        r"if \(\( attempt == MAX_ATTEMPTS \)\); then\s*"
        r'echo "\$\{status\}; no retries remain"\s*'
        r"break\s*fi",
        gate_shell,
    )
    exhausted_deadline_guard = re.search(
        r"if \(\( remaining_seconds <= 0 \)\); then\s*"
        r'echo "\$\{status\}; polling deadline reached"\s*'
        r"break\s*fi",
        gate_shell,
    )
    sleep_lines = [
        line for line in logical_lines if re.search(r"(?<![A-Za-z0-9_])sleep(?![A-Za-z0-9_])", line)
    ]
    final_error = (
        'echo "::error::${VERSION} did not become release-ready (current tag source, '
        "metadata, signed notes provenance, non-yanked PyPI files, or exact asset hashes "
        'missing/mismatched) — refusing to promote prod"'
    )
    if not (
        0
        <= early_deadline_position
        < release_poll_position
        < final_attempt_position
        < remaining_position
        < exhausted_deadline_position
        < bounded_sleep_position
        < final_error_position
        and early_deadline_guard is not None
        and final_attempt_guard is not None
        and exhausted_deadline_guard is not None
        and sleep_lines == ['sleep "$sleep_seconds"']
        and logical_lines[-3:] == ["done", final_error, "exit 1"]
    ):
        errors.append(
            "docs deploy release gate must use a deadline-aware retry loop, "
            "break before its only bounded sleep after the final attempt, and end "
            "immediately with the final diagnostic"
        )
    return errors


def validate_reflex_xy_release_workflow(
    path: Path = DEFAULT_REFLEX_XY_RELEASE_WORKFLOW,
) -> list[str]:
    """The adapter's deliberately small release pipeline stays wired.

    reflex-xy is a pure-Python distribution (one py3-none-any wheel + one
    sdist), so it publishes from its own `reflex-xy-vX.Y.Z` tags via a
    separate workflow rather than a second build shape wedged into
    release.yml's cross-compile matrix. Small is the point — but the safety
    rails must match release.yml's: unshallow checkouts (tag-derived
    version), artifact verification, a changelog gate, trusted publishing,
    and a dry-run default that keeps manual dispatches from publishing.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read reflex-xy release workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_unshallow_checkouts(errors, text, "reflex-xy release")
    missing_jobs = sorted(REQUIRED_REFLEX_XY_RELEASE_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"reflex-xy release workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "reflex-xy release",
        "adapter tag trigger and a workflow_dispatch dry-run input defaulting "
        "to true, so a manual run never accidentally publishes",
        'tags: ["reflex-xy-v*"]',
        "workflow_dispatch:",
        "dry_run:",
        "type: boolean",
        "default: true",
    )
    if 'tags: ["v*"]' in text or '"v*"' in text:
        errors.append(
            "reflex-xy release workflow must not trigger on bare `v*` tags — "
            "those belong to the xy core's release.yml"
        )
    _require_job_contains(
        errors,
        jobs,
        "build",
        "reflex-xy release",
        "pure sdist+wheel build, verification, install smoke, and upload",
        "astral-sh/setup-uv@",
        "working-directory: python/reflex-xy",
        "uv build",
        "scripts/verify_reflex_xy_dist.py",
        '--tag "$GITHUB_REF_NAME"',
        "import reflex_xy",
        "actions/upload-artifact@",
        "name: dist-reflex-xy",
    )
    _require_job_contains(
        errors,
        jobs,
        "publish",
        "reflex-xy release",
        "trusted PyPI publishing from downloaded artifacts, gated by a dry-run "
        "switch and the adapter tag/CHANGELOG agreement gate",
        "needs: [build]",
        "environment: pypi",
        "id-token: write",
        "scripts/check_release_version.py --package reflex-xy",
        "actions/download-artifact@",
        "name: dist-reflex-xy",
        "dry_run",
        "pypa/gh-action-pypi-publish@",
        "packages-dir: dist/",
        "skip-existing: true",
    )

    publish = jobs.get("publish", "")
    if "password:" in publish or "api-token" in publish:
        errors.append(
            "reflex-xy release publish job should use trusted publishing, not a PyPI token"
        )
    if "pypa/gh-action-pypi-publish@" in publish and not _step_carries_publish_gate(
        publish, "pypa/gh-action-pypi-publish@"
    ):
        errors.append(
            "reflex-xy release publish job's PyPI upload step is not gated by "
            f"the dry-run predicate on the step itself (`{PYPI_PUBLISH_GATE}`) — "
            "a missing or unrelated condition (e.g. `if: always()`) would let a "
            "manual dispatch publish unintentionally"
        )
    return errors


def validate_all_workflows(
    ci_path: Path = DEFAULT_CI_WORKFLOW,
    codspeed_path: Path = DEFAULT_CODSPEED_WORKFLOW,
    release_path: Path = DEFAULT_RELEASE_WORKFLOW,
    reflex_xy_release_path: Path = DEFAULT_REFLEX_XY_RELEASE_WORKFLOW,
    docs_deploy_path: Path = DEFAULT_DOCS_DEPLOY_WORKFLOW,
) -> list[str]:
    return [
        *validate_ci_workflow(ci_path),
        *validate_codspeed_workflow(codspeed_path),
        *validate_release_workflow(release_path),
        *validate_reflex_xy_release_workflow(reflex_xy_release_path),
        *validate_docs_deploy_workflow(docs_deploy_path),
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
    parser.add_argument("--release-workflow", type=Path, default=DEFAULT_RELEASE_WORKFLOW)
    parser.add_argument(
        "--reflex-xy-release-workflow", type=Path, default=DEFAULT_REFLEX_XY_RELEASE_WORKFLOW
    )
    parser.add_argument(
        "--docs-deploy-workflow",
        type=Path,
        default=DEFAULT_DOCS_DEPLOY_WORKFLOW,
    )
    parser.add_argument("--ci-only", action="store_true")
    parser.add_argument("--codspeed-only", action="store_true")
    parser.add_argument("--release-only", action="store_true")
    parser.add_argument("--reflex-xy-release-only", action="store_true")
    parser.add_argument("--docs-deploy-only", action="store_true")
    args = parser.parse_args(argv)

    selected_modes = [
        args.ci_only,
        args.codspeed_only,
        args.release_only,
        args.reflex_xy_release_only,
        args.docs_deploy_only,
    ]
    if sum(1 for selected in selected_modes if selected) > 1:
        parser.error(
            "--ci-only, --codspeed-only, --release-only, "
            "--reflex-xy-release-only, and --docs-deploy-only are mutually exclusive"
        )

    if args.workflow is not None:
        errors = validate_ci_workflow(args.workflow)
        checked = [args.workflow]
    elif args.ci_only:
        errors = validate_ci_workflow(args.ci_workflow)
        checked = [args.ci_workflow]
    elif args.codspeed_only:
        errors = validate_codspeed_workflow(args.codspeed_workflow)
        checked = [args.codspeed_workflow]
    elif args.release_only:
        errors = validate_release_workflow(args.release_workflow)
        checked = [args.release_workflow]
    elif args.reflex_xy_release_only:
        errors = validate_reflex_xy_release_workflow(args.reflex_xy_release_workflow)
        checked = [args.reflex_xy_release_workflow]
    elif args.docs_deploy_only:
        errors = validate_docs_deploy_workflow(args.docs_deploy_workflow)
        checked = [args.docs_deploy_workflow]
    else:
        errors = validate_all_workflows(
            args.ci_workflow,
            args.codspeed_workflow,
            args.release_workflow,
            args.reflex_xy_release_workflow,
            args.docs_deploy_workflow,
        )
        checked = [
            args.ci_workflow,
            args.codspeed_workflow,
            args.release_workflow,
            args.reflex_xy_release_workflow,
            args.docs_deploy_workflow,
        ]

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
