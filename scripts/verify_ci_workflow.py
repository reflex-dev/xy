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
RELEASE_DOWNLOAD_ACTION = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
RELEASE_ATTEST_ACTION = "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d"
RELEASE_CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
PYPI_PUBLISH_ACTION = "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b"


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


def _step_uses(step_text: str) -> list[str]:
    """Return every active action reference declared by one step."""
    uses: list[str] = []
    for line in step_text.splitlines():
        match = re.match(r"^      -\s+uses\s*:\s*(.*?)\s*$", line)
        if match is None:
            match = re.match(r"^        uses\s*:\s*(.*?)\s*$", line)
        if match is not None:
            uses.append(_strip_yaml_inline_comment(match.group(1)))
    return uses


def _step_declares_run(step_text: str) -> bool:
    """Return whether a step declares an active ``run`` key."""
    return bool(_step_scalar_values(step_text, "run"))


def _step_scalar_values(step_text: str, key: str) -> list[str]:
    """Return every direct scalar value for one step key."""
    values: list[str] = []
    for match in re.finditer(
        rf"^        {re.escape(key)}\s*:\s*(.*?)\s*$",
        step_text,
        re.MULTILINE,
    ):
        values.append(_strip_yaml_inline_comment(match.group(1)))
    return values


def _step_direct_keys(step_text: str) -> list[str]:
    """Return every direct step key, preserving duplicates and source order."""
    keys: list[str] = []
    for line in step_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 6 and line.startswith("      -"):
            match = re.fullmatch(r"      -\s+([^:]+?)\s*:.*", line)
        elif indent == 8:
            match = re.fullmatch(r"        ([^#\s][^:]*?)\s*:.*", line)
        else:
            continue
        keys.append("<unsupported>" if match is None else match.group(1).strip())
    return keys


def _step_mapping(step_text: str, key: str) -> dict[str, str] | None:
    """Return one direct step mapping with unique plain-scalar children."""
    lines = step_text.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"        {re.escape(key)}\s*:\s*", line)
    ]
    if len(starts) != 1:
        return None

    mapping: dict[str, str] = {}
    for line in lines[starts[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 8:
            break
        match = re.fullmatch(r"          ([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*", line)
        if match is None or match.group(1) in mapping:
            return None
        mapping[match.group(1)] = _strip_yaml_inline_comment(match.group(2))
    return mapping


def _job_direct_keys(job_text: str) -> list[str]:
    """Return active job-level keys, preserving duplicates and source order."""
    keys: list[str] = []
    for line in job_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) != 4:
            continue
        match = re.fullmatch(r"    ([^#\s][^:]*?)\s*:.*", line)
        keys.append("<unsupported>" if match is None else match.group(1).strip())
    return keys


def _workflow_direct_keys(workflow_text: str) -> list[str]:
    """Return active workflow-level keys, preserving duplicates and order."""
    keys: list[str] = []
    for line in workflow_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) != 0:
            continue
        match = re.fullmatch(r"([^#\s][^:]*?)\s*:.*", line)
        keys.append("<unsupported>" if match is None else match.group(1).strip())
    return keys


def _workflow_mapping(workflow_text: str, key: str) -> dict[str, str] | None:
    """Return one canonical flat workflow-level mapping."""
    lines = workflow_text.splitlines()
    starts = [index for index, line in enumerate(lines) if line == f"{key}:"]
    if len(starts) != 1:
        return None

    mapping: dict[str, str] = {}
    for line in lines[starts[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*(.*?)\s*", line)
        if match is None or match.group(1) in mapping:
            return None
        mapping[match.group(1)] = _strip_yaml_inline_comment(match.group(2))
    return mapping


def _release_trigger_is_exact(workflow_text: str) -> bool:
    """Return whether core releases have only the canonical tag/manual triggers."""
    lines = workflow_text.splitlines()
    starts = [position for position, line in enumerate(lines) if line == "on:"]
    if len(starts) != 1:
        return False

    entries: list[tuple[int, str]] = []
    for line in lines[starts[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        entries.append((indent, line.strip()))

    fixed_prefix = [
        (2, "push:"),
        (4, 'tags: ["v*"]'),
        (2, "workflow_dispatch:"),
        (4, "inputs:"),
        (6, "dry_run:"),
        (8, "description: >-"),
    ]
    if entries[: len(fixed_prefix)] != fixed_prefix:
        return False

    position = len(fixed_prefix)
    description_lines = 0
    while position < len(entries) and entries[position][0] >= 10:
        description_lines += 1
        position += 1
    return description_lines > 0 and entries[position:] == [
        (8, "type: boolean"),
        (8, "default: true"),
    ]


def _step_has_exact_bash_run(step_text: str) -> bool:
    """Return whether a step has one direct run and one exact Bash shell."""
    return len(_step_scalar_values(step_text, "run")) == 1 and _step_scalar_values(
        step_text, "shell"
    ) == ["bash"]


def _step_run(step_text: str) -> str | None:
    """Return one step's shell from a literal block or one-line ``run`` value.

    Folded YAML scalars replace source newlines with spaces according to YAML
    folding rules. Treating their indented source as separate shell commands
    validates different code from what Actions executes, so protected callers
    must fail closed instead of attempting to reconstruct folded semantics.
    """
    lines = step_text.splitlines()
    for start, line in enumerate(lines):
        match = re.match(r"^        run:\s*(.*?)\s*$", line)
        if match is None:
            continue
        value = _strip_yaml_inline_comment(match.group(1))
        block_scalar = re.fullmatch(
            r"[|>](?:(?:[1-9][+-]?)|(?:[+-][1-9]?))?",
            value,
        )
        if block_scalar is not None and not re.fullmatch(r"\|[+-]?", value):
            return None
        if not re.fullmatch(r"\|[+-]?", value):
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


def _step_uses_uninspectable_run(step_text: str) -> bool:
    """Return whether a shell step is not a supported literal YAML block."""
    for line in step_text.splitlines():
        match = re.match(r"^        run\s*:\s*(.*?)\s*$", line)
        if match is not None:
            if not line.startswith("        run:"):
                return True
            value = _strip_yaml_inline_comment(match.group(1))
            return re.fullmatch(r"\|[+-]?", value) is None
    return False


def _job_scalar(job_text: str, key: str) -> str | None:
    """Return an active job-level scalar, ignoring comments and nested keys."""
    match = re.search(rf"^    {re.escape(key)}:\s*(.*?)\s*$", job_text, re.MULTILINE)
    return None if match is None else match.group(1)


def _step_scalar(step_text: str, key: str) -> str | None:
    """Return an active named-step scalar, ignoring comments and nested keys."""
    values = _step_scalar_values(step_text, key)
    return values[0] if len(values) == 1 else None


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
    starts = [index for index, line in enumerate(lines) if line == f"    {key}:"]
    if len(starts) != 1:
        return None

    mapping: dict[str, str] = {}
    for line in lines[starts[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 4:
            break
        match = re.fullmatch(r"      ([A-Za-z0-9_-]+):\s*(.*?)\s*", line)
        if match is None or match.group(1) in mapping:
            return None
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


_SHELL_COMMAND_BOUNDARIES = {
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
_SHELL_ASSIGNMENT_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_REDIRECTION_TOKEN = re.compile(
    r"^(?:[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\})?"
    r"(?:<<<|<<-|<<|<>|>>|>|<)(.*)$"
)
_ALLOWED_PROTECTED_ARITHMETIC_LINES = {
    "POLL_DEADLINE=$((SECONDS + 30 * 60))",
    "if (( SECONDS >= POLL_DEADLINE )); then",
    "if (( ${#wheels[@]} == 0 || ${#sdists[@]} != 1 )); then",
    "if (( attempt < 12 )); then",
    "if (( attempt == MAX_ATTEMPTS )); then",
    "remaining_seconds=$((POLL_DEADLINE - SECONDS))",
    "if (( remaining_seconds <= 0 )); then",
    "if (( sleep_seconds > remaining_seconds )); then",
}
_ALLOWED_PYPI_CURL_COMMANDS = {
    (
        "curl",
        "-fsS",
        "--connect-timeout",
        "5",
        "--max-time",
        "20",
        f"https://pypi.org/pypi/xy/${{{version_variable}}}/json",
        "2>/dev/null",
    )
    for version_variable in ("pypi_version", "PYPI_VERSION")
}


def _shell_control_joins_redirection(tokens: list[str], position: int) -> bool:
    """Return whether ``&`` or ``|`` completes the preceding redirect."""
    if tokens[position] not in {"&", "|"} or position == 0 or position + 1 >= len(tokens):
        return False
    return (
        re.fullmatch(
            r"(?:[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\})?[<>]",
            tokens[position - 1],
        )
        is not None
    )


def _shell_prefix_without_redirections(prefix: list[str]) -> list[str] | None:
    """Remove complete Bash redirections from a simple-command prefix."""
    cleaned: list[str] = []
    index = 0
    while index < len(prefix):
        match = _SHELL_REDIRECTION_TOKEN.fullmatch(prefix[index])
        if match is None:
            cleaned.append(prefix[index])
            index += 1
            continue
        if match.group(1):
            index += 1
            continue
        if index + 1 >= len(prefix):
            return None
        if prefix[index + 1] in {"&", "|"}:
            if index + 2 >= len(prefix):
                return None
            index += 3
        else:
            index += 2
    return cleaned


def _shell_prefix_is_wrappers(prefix: list[str]) -> bool:
    """Return whether ``prefix`` only wraps the command that follows it."""
    prefix = _shell_prefix_without_redirections(prefix)
    if prefix is None:
        return False
    index = 0
    while index < len(prefix) and _SHELL_ASSIGNMENT_TOKEN.match(prefix[index]):
        index += 1

    while index < len(prefix):
        wrapper = prefix[index].rsplit("/", 1)[-1]
        index += 1
        if wrapper in {"builtin", "command"}:
            while index < len(prefix) and (prefix[index] == "--" or prefix[index].startswith("-")):
                index += 1
            continue
        if wrapper == "env":
            value_options = {
                "--argv0",
                "--chdir",
                "--split-string",
                "--unset",
                "-C",
                "-S",
                "-a",
                "-u",
            }
            while index < len(prefix):
                token = prefix[index]
                if _SHELL_ASSIGNMENT_TOKEN.match(token):
                    index += 1
                elif token == "--":
                    index += 1
                    break
                elif token in value_options:
                    index += 2
                elif token.startswith("-"):
                    index += 1
                else:
                    break
            continue
        if wrapper == "time":
            while index < len(prefix) and (prefix[index] == "--" or prefix[index].startswith("-")):
                index += 1
            continue
        if wrapper == "nohup":
            while index < len(prefix) and prefix[index].startswith("-"):
                index += 1
            continue
        if wrapper == "nice":
            while index < len(prefix):
                token = prefix[index]
                if token in {"--adjustment", "-n"}:
                    index += 2
                elif token.startswith("-"):
                    index += 1
                else:
                    break
            continue
        if wrapper == "stdbuf":
            value_options = {"--error", "--input", "--output", "-e", "-i", "-o"}
            while index < len(prefix):
                token = prefix[index]
                if token in value_options:
                    index += 2
                elif token.startswith("-"):
                    index += 1
                else:
                    break
            continue
        if wrapper == "timeout":
            value_options = {"--kill-after", "--signal", "-k", "-s"}
            while index < len(prefix):
                token = prefix[index]
                if token == "--":
                    index += 1
                    continue
                if token in value_options:
                    index += 2
                elif token.startswith("-"):
                    index += 1
                else:
                    # The first positional value is timeout's duration.
                    index += 1
                    break
            continue
        return False
    return True


def _shell_token_starts_command(tokens: list[str], token_position: int) -> bool:
    """Return whether one token is executable at a shell command boundary."""
    command_start = 0
    for prefix_position in range(token_position - 1, -1, -1):
        if tokens[prefix_position] in _SHELL_COMMAND_BOUNDARIES and not (
            _shell_control_joins_redirection(tokens, prefix_position)
        ):
            command_start = prefix_position + 1
            break
    return _shell_prefix_is_wrappers(tokens[command_start:token_position])


def _shell_command_arguments(tokens: list[str], token_position: int) -> list[str]:
    """Return arguments up to the next shell control boundary."""
    command_end = len(tokens)
    for suffix_position in range(token_position + 1, len(tokens)):
        if tokens[suffix_position] in _SHELL_COMMAND_BOUNDARIES and not (
            _shell_control_joins_redirection(tokens, suffix_position)
        ):
            command_end = suffix_position
            break
    return tokens[token_position + 1 : command_end]


def _shell_backtick_end(shell: str, start: int) -> int | None:
    """Return the closing backtick after ``start``, honoring escapes."""
    position = start
    while position < len(shell):
        if shell[position] == "\\":
            position += 2
            continue
        if shell[position] == "`":
            return position
        position += 1
    return None


def _shell_command_substitution_end(shell: str, start: int) -> int | None:
    """Return the closing parenthesis for a command substitution body."""
    depth = 1
    quote: str | None = None
    position = start
    while position < len(shell):
        character = shell[position]
        if quote == "'":
            if character == "'":
                quote = None
            position += 1
            continue
        if quote == '"':
            if character == "\\":
                position += 2
                continue
            if character == '"':
                quote = None
                position += 1
                continue
            if shell.startswith("$(", position) and not shell.startswith("$((", position):
                nested_end = _shell_command_substitution_end(shell, position + 2)
                if nested_end is None:
                    return None
                position = nested_end + 1
                continue
            if character == "`":
                nested_end = _shell_backtick_end(shell, position + 1)
                if nested_end is None:
                    return None
                position = nested_end + 1
                continue
            position += 1
            continue
        if character == "\\":
            position += 2
            continue
        if character in {"'", '"'}:
            quote = character
            position += 1
            continue
        if character == "#" and (
            position == 0 or shell[position - 1].isspace() or shell[position - 1] in ";|&()"
        ):
            newline = shell.find("\n", position)
            if newline < 0:
                return None
            position = newline + 1
            continue
        if shell.startswith("$(", position) and not shell.startswith("$((", position):
            nested_end = _shell_command_substitution_end(shell, position + 2)
            if nested_end is None:
                return None
            position = nested_end + 1
            continue
        if character == "`":
            nested_end = _shell_backtick_end(shell, position + 1)
            if nested_end is None:
                return None
            position = nested_end + 1
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return None


def _shell_substitution_scan(shell: str) -> tuple[list[str], str] | None:
    """Extract active substitution bodies and mask them in the outer shell."""
    bodies: list[str] = []
    masked: list[str] = []
    quote: str | None = None
    position = 0
    while position < len(shell):
        character = shell[position]
        if quote == "'":
            if character == "'":
                quote = None
            masked.append(character)
            position += 1
            continue
        if character == "\\":
            if position + 1 < len(shell) and shell[position + 1] == "\n":
                position += 2
                continue
            masked.append(shell[position : position + 2])
            position += 2
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            masked.append(character)
            position += 1
            continue
        if quote is None and character == "'":
            quote = "'"
            masked.append(character)
            position += 1
            continue
        if (
            quote is None
            and character == "#"
            and (position == 0 or shell[position - 1].isspace() or shell[position - 1] in ";|&()")
        ):
            newline = shell.find("\n", position)
            if newline < 0:
                break
            masked.append(shell[position:newline])
            masked.append("\n")
            position = newline + 1
            continue
        if shell.startswith("$(", position) and not shell.startswith("$((", position):
            end = _shell_command_substitution_end(shell, position + 2)
            if end is None:
                return None
            bodies.append(shell[position + 2 : end])
            masked.append("__SHELL_SUBSTITUTION__")
            position = end + 1
            continue
        if quote is None and shell.startswith(("<(", ">("), position):
            end = _shell_command_substitution_end(shell, position + 2)
            if end is None:
                return None
            bodies.append(shell[position + 2 : end])
            masked.append("__SHELL_SUBSTITUTION__")
            position = end + 1
            continue
        if character == "`":
            end = _shell_backtick_end(shell, position + 1)
            if end is None:
                return None
            bodies.append(shell[position + 1 : end])
            masked.append("__SHELL_SUBSTITUTION__")
            position = end + 1
            continue
        masked.append(character)
        position += 1
    return None if quote is not None else (bodies, "".join(masked))


def _shell_command_substitutions(shell: str) -> list[str] | None:
    """Extract active command- and process-substitution bodies from shell source."""
    scan = _shell_substitution_scan(shell)
    return None if scan is None else scan[0]


def _strip_active_shell_comments(shell: str) -> str | None:
    """Strip active Bash comments without treating parameter ``#`` as one."""
    stripped: list[str] = []
    quote: str | None = None
    position = 0
    while position < len(shell):
        character = shell[position]
        if quote == "'":
            stripped.append(character)
            if character == "'":
                quote = None
            position += 1
            continue
        if character == "\\":
            if position + 1 < len(shell) and shell[position + 1] == "\n":
                position += 2
                continue
            stripped.append(shell[position : position + 2])
            position += 2
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            stripped.append(character)
            position += 1
            continue
        if quote is None and character == "'":
            quote = "'"
            stripped.append(character)
            position += 1
            continue
        if (
            quote is None
            and character == "#"
            and (position == 0 or shell[position - 1].isspace() or shell[position - 1] in ";|&()")
        ):
            newline = shell.find("\n", position)
            if newline < 0:
                break
            stripped.append("\n")
            position = newline + 1
            continue
        stripped.append(character)
        position += 1
    return None if quote is not None else "".join(stripped)


def _shell_script_tokens(shell: str) -> list[str] | None:
    """Tokenize a complete Bash script while preserving command newlines.

    Keeping the script intact prevents multiline quoted jq programs from being
    mistaken for shell commands. Active substitutions are checked recursively
    and masked before this outer lexical pass.
    """
    scan = _shell_substitution_scan(shell)
    if scan is None:
        return None
    _, masked = scan
    uncommented = _strip_active_shell_comments(masked)
    if uncommented is None:
        return None
    lexer = shlex.shlex(uncommented, posix=True, punctuation_chars=";&|()\n")
    lexer.commenters = ""
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        raw_tokens = list(lexer)
    except ValueError:
        return None

    tokens: list[str] = []
    two_character_operators = {"&&", "||", ";;", "((", "))"}
    punctuation = set(";&|()\n")
    for token in raw_tokens:
        if not token or any(character not in punctuation for character in token):
            tokens.append(token)
            continue
        position = 0
        while position < len(token):
            pair = token[position : position + 2]
            if pair in two_character_operators:
                tokens.append(pair)
                position += 2
            else:
                tokens.append(token[position])
                position += 1
    return tokens


def _shell_command_end(tokens: list[str], start: int) -> int:
    """Return the first unambiguous simple-command boundary after ``start``."""
    for position in range(start, len(tokens)):
        if tokens[position] in {"\n", ";", ";;", "&", "&&", "|", "||"} and not (
            _shell_control_joins_redirection(tokens, position)
        ):
            return position
    return len(tokens)


def _skip_balanced_shell_tokens(
    tokens: list[str],
    start: int,
    opening: str,
    closing: str,
) -> int | None:
    """Return the position after one balanced token expression."""
    depth = 0
    for position in range(start, len(tokens)):
        if tokens[position] == opening:
            depth += 1
        elif tokens[position] == closing:
            depth -= 1
            if depth == 0:
                return position + 1
    return None


_ALLOWED_PROTECTED_COMMANDS = {
    ":",
    "break",
    "cat",
    "curl",
    "cut",
    "diff",
    "echo",
    "exit",
    "gh",
    "jq",
    "local",
    "mkdir",
    "mktemp",
    "printf",
    "read",
    "release_metadata_matches",
    "return",
    "rm",
    "seq",
    "sha256sum",
    "shopt",
    "sleep",
    "timeout",
    "verify_release_payload",
    "verify_tag_source",
}
_ALLOWED_PROTECTED_FUNCTIONS = {
    "release_metadata_matches",
    "verify_release_payload",
    "verify_tag_source",
}


def _has_unapproved_shell_command(shell: str) -> bool:
    """Reject every executable command head outside a small positive allowlist."""
    scan = _shell_substitution_scan(shell)
    if scan is None:
        return True
    substitutions, _ = scan
    if any(_has_unapproved_shell_command(body) for body in substitutions):
        return True

    tokens = _shell_script_tokens(shell)
    if tokens is None:
        return True

    command_expected = True
    for_header = False
    position = 0
    while position < len(tokens):
        token = tokens[position]

        if for_header:
            if token == "do":
                for_header = False
                command_expected = True
            position += 1
            continue

        if token in {"\n", ";", ";;", "&", "&&", "|", "||"}:
            if not _shell_control_joins_redirection(tokens, position):
                command_expected = True
            position += 1
            continue

        if not command_expected:
            position += 1
            continue

        if token in {"if", "elif", "while", "until", "!", "then", "else", "do", "{"}:
            command_expected = True
            position += 1
            continue
        if token in {"fi", "done", "esac", "}"}:
            command_expected = False
            position += 1
            continue
        if token in {"for", "select"}:
            for_header = True
            command_expected = False
            position += 1
            continue
        if token == "[[":
            try:
                position = tokens.index("]]", position + 1) + 1
            except ValueError:
                return True
            command_expected = False
            continue
        if token == "((":
            end = _skip_balanced_shell_tokens(tokens, position, "((", "))")
            if end is None:
                return True
            position = end
            command_expected = False
            continue
        if token == "(":
            command_expected = True
            position += 1
            continue
        if token == ")":
            command_expected = False
            position += 1
            continue

        redirection = _SHELL_REDIRECTION_TOKEN.fullmatch(token)
        if redirection is not None:
            if redirection.group(1):
                position += 1
            elif position + 2 < len(tokens) and tokens[position + 1] in {"&", "|"}:
                position += 3
            elif position + 1 < len(tokens):
                position += 2
            else:
                return True
            continue

        if _SHELL_ASSIGNMENT_TOKEN.match(token):
            if position + 1 < len(tokens) and tokens[position + 1] in {"(", "(("}:
                opening = tokens[position + 1]
                closing = ")" if opening == "(" else "))"
                end = _skip_balanced_shell_tokens(tokens, position + 1, opening, closing)
                if end is None:
                    return True
                position = end
                command_expected = False
            else:
                position += 1
            continue

        if token in _ALLOWED_PROTECTED_FUNCTIONS and tokens[position + 1 : position + 4] == [
            "(",
            ")",
            "{",
        ]:
            position += 4
            command_expected = True
            continue

        # Trust exact raw command names only. A generated `/tmp/gh`, dynamic
        # path, or other executable must not inherit trust from its basename.
        if token not in _ALLOWED_PROTECTED_COMMANDS:
            return True
        if token == "timeout":
            end = _shell_command_end(tokens, position + 1)
            arguments = tokens[position + 1 : end]
            if not (
                len(arguments) >= 5
                and arguments[:2] == ["--signal=TERM", "--kill-after=5s"]
                and arguments[2] in {"30s", "60s", "180s"}
                and arguments[3] == "gh"
            ):
                return True

        command_expected = False
        position += 1

    return for_header


def _has_deferred_shell_execution(shell: str) -> bool:
    """Reject inert-looking text that Bash can later reevaluate as arithmetic.

    Bash recursively interprets variable values used by arithmetic commands.
    Consequently, a single-quoted assignment such as
    ``payload='index[$(command)]'`` becomes executable when a later
    ``(( payload ))`` evaluates it. Treat executable substitution syntax in a
    single-quoted value as indirect execution instead of trying to prove every
    later arithmetic data flow safe.
    """
    in_single_quote = False
    position = 0
    while position < len(shell):
        character = shell[position]
        if character == "\\" and not in_single_quote:
            position += 2
            continue
        if character == "'":
            in_single_quote = not in_single_quote
            position += 1
            continue
        if in_single_quote and (shell.startswith(("$(", "<(", ">("), position) or character == "`"):
            return True
        position += 1
    return False


def _has_unapproved_shell_arithmetic(shell: str) -> bool:
    """Reject arithmetic evaluation outside the exact protected gate expressions."""
    return any(
        "((" in tokens and line not in _ALLOWED_PROTECTED_ARITHMETIC_LINES
        for _, line, tokens in _shell_command_records(shell)
    )


def _has_unapproved_network_access(shell: str) -> bool:
    """Reject network-capable commands outside the exact PyPI/GitHub surface."""
    substitutions = _shell_command_substitutions(shell)
    if substitutions is None or any(_has_unapproved_network_access(body) for body in substitutions):
        return True
    if re.search(r"/dev/(?:tcp|udp)/", shell):
        return True

    network_tools = {
        "aria2c",
        "busybox",
        "ftp",
        "http",
        "httpie",
        "nc",
        "ncat",
        "netcat",
        "openssl",
        "sftp",
        "socat",
        "ssh",
        "telnet",
        "wget",
    }
    sensitive_assignments = {
        "CURL_HOME",
        "GH_CONFIG_DIR",
        "HOME",
        "PATH",
        "XDG_CONFIG_HOME",
    }
    logical_lines = _shell_logical_lines(shell)
    if any(_assignment_lines(logical_lines, name) for name in sensitive_assignments):
        return True
    allowed_gh_commands = {"api", "attestation", "release"}
    for _, _, tokens in _shell_command_records(shell):
        if any(
            "=" in token and _assignment_target_is(token, name)
            for token in tokens
            for name in sensitive_assignments
        ):
            return True
        for position, token in enumerate(tokens):
            command = token.rsplit("/", 1)[-1]
            command_position = _shell_token_starts_command(tokens, position)
            if command in {"curl", "gh", *network_tools} and not command_position:
                # Unknown wrappers such as strace/taskset can execute a later
                # network-capable token. Fail closed instead of assuming the
                # token is inert merely because the prefix is unsupported.
                return True
            if not command_position:
                continue
            arguments = _shell_command_arguments(tokens, position)
            if command == "curl":
                if token != "curl" or tuple([command, *arguments]) not in (
                    _ALLOWED_PYPI_CURL_COMMANDS
                ):
                    return True
            elif command in network_tools:
                return True
            elif command == "gh":
                subcommand, _ = _gh_subcommand(arguments)
                if (
                    subcommand not in allowed_gh_commands
                    or subcommand is None
                    or any(marker in subcommand for marker in ("$", "`", "*", "?", "[", "{"))
                ):
                    return True
    return False


def _has_indirect_shell_execution(shell: str) -> bool:
    """Reject commands that can hide unparsed shell from protected validators."""
    substitutions = _shell_command_substitutions(shell)
    active_shell = _strip_active_shell_comments(shell)
    if (
        substitutions is None
        or active_shell is None
        or _has_deferred_shell_execution(shell)
        or _has_unapproved_shell_arithmetic(shell)
        or _has_unapproved_network_access(shell)
        or _has_unapproved_shell_command(shell)
        or re.search(r"\$(?:GITHUB_ENV|GITHUB_PATH)\b", shell)
        or re.search(r"\$\{(?:GITHUB_ENV|GITHUB_PATH)\}", shell)
        or any(
            marker in active_shell for marker in ("_runner_file_commands", "set_env_", "add_path_")
        )
        or any(_has_indirect_shell_execution(body) for body in substitutions)
    ):
        return True
    shell_interpreters = {
        "$SHELL",
        "${SHELL}",
        "ash",
        "bash",
        "dash",
        "fish",
        "ksh",
        "mksh",
        "sh",
        "zsh",
    }
    code_interpreters = {
        "awk",
        "bun",
        "deno",
        "gawk",
        "lua",
        "mawk",
        "node",
        "perl",
        "php",
        "ruby",
        "sed",
    }
    indirect_commands = {
        ".",
        "alias",
        "chroot",
        "chrt",
        "coproc",
        "enable",
        "eval",
        "exec",
        "find",
        "hash",
        "ionice",
        "let",
        "parallel",
        "script",
        "setsid",
        "source",
        "strace",
        "sudo",
        "systemd-run",
        "taskset",
        "trap",
        "unshare",
        "watch",
        "xargs",
    }
    dangerous_shell_environment = {
        "BASH_ENV",
        "CDPATH",
        "ENV",
        "PROMPT_COMMAND",
    }
    if any(
        _assignment_lines(_shell_logical_lines(shell), name) for name in dangerous_shell_environment
    ):
        return True
    double_bracket_open = False
    for _, line, tokens in _shell_command_records(shell):
        expression_positions: set[int] = set()
        arithmetic_open = False
        for position, token in enumerate(tokens):
            if token == "[[":
                double_bracket_open = True
            elif token == "((":
                arithmetic_open = True
            if double_bracket_open or arithmetic_open:
                expression_positions.add(position)
            if token == "]]":
                double_bracket_open = False
            elif token == "))":
                arithmetic_open = False

        function_definition = re.match(
            r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)"
            r"(?:\s*\(\))?\s*\{(?:\s|$)",
            line,
        )
        if function_definition is not None and function_definition.group(1) not in {
            "release_metadata_matches",
            "verify_release_payload",
            "verify_tag_source",
        }:
            return True
        for token_position, token in enumerate(tokens):
            if token_position in expression_positions:
                continue
            command = token.rsplit("/", 1)[-1]
            dynamic_command = token.startswith(("$", "`")) and not (
                len(tokens) > 1 and _SHELL_ASSIGNMENT_TOKEN.match(tokens[0]) and tokens[1] == "("
            )
            command_position = _shell_token_starts_command(tokens, token_position)
            potentially_executable = (
                command in indirect_commands
                or command in shell_interpreters
                or command in code_interpreters
                or command.startswith(("pypy", "python"))
                or dynamic_command
            )
            if not command_position:
                if (
                    command in shell_interpreters
                    or command in code_interpreters
                    or command.startswith(("pypy", "python"))
                ):
                    return True
                continue
            if potentially_executable:
                return True
            if command == "env" and any(
                argument in {"-S", "--split-string"}
                or argument.startswith(("-S", "--split-string="))
                for argument in _shell_command_arguments(tokens, token_position)
            ):
                return True
            if command in {"declare", "local", "readonly", "typeset"} and any(
                argument.startswith(("-i", "+i"))
                for argument in _shell_command_arguments(tokens, token_position)
            ):
                return True
    return False


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
    explicit_status = re.compile(r"^[+-]?[0-9]+$")
    terminations: list[tuple[int, int, str, str | None]] = []

    for position, line in enumerate(logical_lines):
        tokens = _shell_tokens(line)
        if tokens is None:
            continue
        for token_position, token in enumerate(tokens):
            if token not in {"exec", "exit", "return"}:
                continue
            if not _shell_token_starts_command(tokens, token_position):
                continue
            arguments = _shell_command_arguments(tokens, token_position)
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


def _normalized_api_endpoint(endpoint: str) -> str:
    """Normalize one REST/GraphQL endpoint without inspecting option values."""
    endpoint = endpoint.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    endpoint = re.sub(r"^https://[^/]+/(?:api/v3/)?", "", endpoint)
    return endpoint.lstrip("/")


def _normalized_release_api_endpoint(endpoint: str) -> tuple[bool, bool]:
    """Return ``(is_release_endpoint, is_generate_notes_endpoint)``."""
    endpoint = _normalized_api_endpoint(endpoint)
    release_path = re.fullmatch(
        r"repos/(?:\$\{REPO\}|\$REPO|[^/]+/[^/]+)/releases(?:/(.*))?",
        endpoint,
    )
    if release_path is None:
        return False, False
    return True, release_path.group(1) == "generate-notes"


def _gh_api_request(api_tokens: list[str]) -> tuple[str, str | None]:
    """Return the effective method and positional endpoint of ``gh api``."""
    method: str | None = None
    has_payload = False
    endpoint: str | None = None
    value_options = {
        "--cache",
        "--header",
        "--hostname",
        "--jq",
        "--preview",
        "--template",
        "-H",
        "-p",
        "-q",
        "-t",
    }
    payload_options = {"--field", "--input", "--raw-field", "-F", "-f"}
    index = 0
    while index < len(api_tokens):
        token = api_tokens[index]
        if token in {"--method", "-X"}:
            method = api_tokens[index + 1] if index + 1 < len(api_tokens) else ""
            index += 2
            continue
        if token.startswith("--method="):
            method = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("-X") and len(token) > 2:
            method = token[2:].removeprefix("=")
            index += 1
            continue
        if token in payload_options:
            has_payload = True
            index += 2
            continue
        if (
            token.startswith("--field=")
            or token.startswith("--input=")
            or token.startswith("--raw-field=")
            or (token.startswith("-F") and len(token) > 2)
            or (token.startswith("-f") and len(token) > 2)
        ):
            has_payload = True
            index += 1
            continue
        if token in value_options:
            index += 2
            continue
        if any(
            token.startswith(f"{option}=") for option in value_options if option.startswith("--")
        ):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if endpoint is None:
            endpoint = token
        index += 1
    return (method.upper() if method is not None else ("POST" if has_payload else "GET")), endpoint


def _gh_subcommand(arguments: list[str]) -> tuple[str | None, list[str]]:
    """Return the first positional gh command after persistent options."""
    value_options = {"--config-dir", "--hostname", "--repo", "-R"}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            index += 1
            break
        if token in value_options:
            index += 2
            continue
        if token.startswith(("--config-dir=", "--hostname=", "--repo=")):
            index += 1
            continue
        if token.startswith("-R") and len(token) > 2:
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token, arguments[index + 1 :]
    if index < len(arguments):
        return arguments[index], arguments[index + 1 :]
    return None, []


def _shell_token_is_dynamic(token: str) -> bool:
    """Return whether a shell token's value is computed at runtime."""
    return any(marker in token for marker in ("$", "`", "*", "?", "[", "]", "{", "}"))


def _has_gh_release_mutation(shell: str) -> bool:
    """Return whether shell directly invokes a GitHub Release write command."""
    mutations = {"create", "delete", "delete-asset", "edit", "new", "upload"}
    for _, _, tokens in _shell_command_records(shell):
        for index, token in enumerate(tokens):
            if token.rsplit("/", 1)[-1] != "gh" or not _shell_token_starts_command(tokens, index):
                continue
            gh_arguments = _shell_command_arguments(tokens, index)
            subcommand, subcommand_arguments = _gh_subcommand(gh_arguments)
            if subcommand is not None and _shell_token_is_dynamic(subcommand):
                # A computed top-level command can become `release` or `api`.
                return True
            if subcommand == "release":
                release_command, _ = _gh_subcommand(subcommand_arguments)
                if release_command in mutations or (
                    release_command is not None and _shell_token_is_dynamic(release_command)
                ):
                    return True
                continue
            if subcommand != "api":
                continue
            method, endpoint = _gh_api_request(subcommand_arguments)
            if method in {"GET", "HEAD"}:
                continue
            if endpoint is None:
                return True
            normalized_endpoint = _normalized_api_endpoint(endpoint)
            if normalized_endpoint == "graphql":
                return True
            is_release, is_generate_notes = _normalized_release_api_endpoint(endpoint)
            if is_release and not (is_generate_notes and method == "POST"):
                return True
            endpoint_without_repo = normalized_endpoint.replace("${REPO}", "REPO").replace(
                "$REPO", "REPO"
            )
            if "$" in endpoint_without_repo or "`" in endpoint_without_repo:
                # A computed write endpoint can resolve to Releases at runtime.
                return True
            if normalized_endpoint.startswith("graphql/"):
                # Fail closed on non-canonical GraphQL spellings as well.
                return True
            if endpoint.startswith(("$", "`")):
                return True
    return False


def _gh_api_write_requests(shell: str) -> list[tuple[str, str | None]]:
    """Return every non-read ``gh api`` request declared by a shell body."""
    requests: list[tuple[str, str | None]] = []
    for _, _, tokens in _shell_command_records(shell):
        for index, token in enumerate(tokens):
            if token != "gh" or not _shell_token_starts_command(tokens, index):
                continue
            subcommand, subcommand_arguments = _gh_subcommand(
                _shell_command_arguments(tokens, index)
            )
            if subcommand != "api":
                continue
            method, endpoint = _gh_api_request(subcommand_arguments)
            if method not in {"GET", "HEAD"}:
                requests.append((method, endpoint))
    return requests


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
    return tokens in (
        command,
        [*command, "2>/dev/null"],
        [*command, "2>$release_lookup_error"],
    )


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


def _assignment_target_is(token: str, name: str) -> bool:
    """Return whether an assignment/declaration token targets ``name``."""
    target = token.split("=", 1)[0].removesuffix("+")
    target = target.split("[", 1)[0]
    return target == name


def _assignment_target_is_dynamic(token: str) -> bool:
    """Return whether a variable-writing command computes its target name."""
    target = token.split("=", 1)[0]
    return "$" in target or "`" in target


def _shell_command_writes_variable(tokens: list[str], position: int, name: str) -> bool:
    """Recognize shell builtins that can overwrite a protected variable."""
    if not _shell_token_starts_command(tokens, position):
        return False
    command = tokens[position]
    arguments = _shell_command_arguments(tokens, position)

    if command in {"declare", "export", "local", "readonly", "typeset", "unset"}:
        nameref = any(argument.startswith("-") and "n" in argument[1:] for argument in arguments)
        if nameref:
            # A nameref can redirect later ordinary assignments to a protected
            # variable, including when its target name is computed indirectly.
            return True
        for argument in arguments:
            if argument == "--" or argument.startswith("-"):
                continue
            if _assignment_target_is(argument, name) or _assignment_target_is_dynamic(argument):
                return True
        return False

    if command == "printf":
        for index, argument in enumerate(arguments):
            if argument == "-v" and index + 1 < len(arguments):
                target = arguments[index + 1]
                return _assignment_target_is(target, name) or _assignment_target_is_dynamic(target)
            if argument.startswith("-v") and len(argument) > 2:
                target = argument[2:]
                return _assignment_target_is(target, name) or _assignment_target_is_dynamic(target)
        return False

    if command == "read":
        value_options = {"-d", "-i", "-n", "-N", "-p", "-t", "-u"}
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--":
                return any(
                    _assignment_target_is(target, name) or _assignment_target_is_dynamic(target)
                    for target in arguments[index + 1 :]
                )
            if argument == "-a" and index + 1 < len(arguments):
                target = arguments[index + 1]
                if _assignment_target_is(target, name) or _assignment_target_is_dynamic(target):
                    return True
                index += 2
                continue
            if argument.startswith("-a") and len(argument) > 2:
                target = argument[2:]
                if _assignment_target_is(target, name) or _assignment_target_is_dynamic(target):
                    return True
                index += 1
                continue
            if argument in value_options:
                index += 2
                continue
            if argument.startswith("-"):
                index += 1
                continue
            return any(
                _assignment_target_is(target, name) or _assignment_target_is_dynamic(target)
                for target in arguments[index:]
            )
        return False

    if command in {"mapfile", "readarray"}:
        value_options = {"-C", "-O", "-c", "-n", "-s", "-u"}
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument in value_options:
                index += 2
                continue
            if argument.startswith("-"):
                index += 1
                continue
            if re.match(r"^(?:[0-9]*)[<>]", argument):
                redirection_only = re.fullmatch(
                    r"[0-9]*(?:<<<|<<|<>|<&|>>|>&|>\||<|>)",
                    argument,
                )
                index += 2 if redirection_only is not None else 1
                continue
            return _assignment_target_is(argument, name) or _assignment_target_is_dynamic(argument)
        return name == "MAPFILE"

    if command == "let":
        if any("$" in argument or "`" in argument for argument in arguments):
            return True
        arithmetic_write = re.compile(
            rf"^{re.escape(name)}(?:\[[^]]+\])?\s*"
            r"(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))"
        )
        return any(arithmetic_write.search(argument) for argument in arguments)

    if command == "getopts" and len(arguments) >= 2:
        target = arguments[1]
        return _assignment_target_is(target, name) or _assignment_target_is_dynamic(target)

    return False


def _assignment_lines(logical_lines: list[str], name: str) -> list[str]:
    """Return every direct or builtin write to a protected shell variable."""
    pattern = re.compile(rf"^(?:if (?:! )?)?{re.escape(name)}(?:\[[^]]+\])?\+?=")
    arithmetic_write = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(name)}(?:\[[^]]+\])?\s*"
        r"(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))"
    )
    parameter_write = re.compile(rf"\$\{{{re.escape(name)}(?::?=)")
    iteration_write = re.compile(
        rf"(?:^|[;&|{{}}()]\s*|\b(?:do|then)\s+)"
        rf"(?:for|select)\s+{re.escape(name)}\b"
    )
    dynamic_arithmetic_write = re.compile(
        r"\(\([^)]*\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))"
    )
    assignments: list[str] = []
    for line in logical_lines:
        if (
            pattern.match(line)
            or arithmetic_write.search(line)
            or parameter_write.search(line)
            or iteration_write.search(line)
            or dynamic_arithmetic_write.search(line)
        ):
            assignments.append(line)
            continue
        tokens = _shell_tokens(line)
        if tokens is not None and any(
            _shell_command_writes_variable(tokens, position, name)
            for position in range(len(tokens))
        ):
            assignments.append(line)
    return assignments


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
CORE_PYPI_PUBLISH_GATE = (
    "if: (github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')) || "
    "(github.event_name == 'workflow_dispatch' && github.event.inputs.dry_run == 'false')"
)
CORE_PRERELEASE_TAG_PATTERN = r"^v[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$"


def _step_carries_publish_gate(
    job_text: str,
    step_needle: str,
    expected_gate: str = PYPI_PUBLISH_GATE,
) -> bool:
    block = _step_block(job_text, step_needle)
    return block is not None and expected_gate in block


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
    if _workflow_direct_keys(text) != ["name", "on", "permissions", "jobs"]:
        errors.append(
            "release workflow must use exact top-level controls with no inherited "
            "environment or run defaults"
        )
    if not _release_trigger_is_exact(text):
        errors.append(
            "release workflow triggers must be exactly v* tag pushes plus a "
            "boolean workflow_dispatch dry_run input defaulting to true"
        )
    if _workflow_mapping(text, "permissions") != {"contents": "read"}:
        errors.append("release workflow top-level permissions must be exactly contents: read")
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
    if _job_direct_keys(publish) != [
        "name",
        "needs",
        "runs-on",
        "environment",
        "permissions",
        "steps",
    ]:
        errors.append(
            "release publish job must use exact control keys with no inherited "
            "environment, defaults, or continue-on-error bypass"
        )
    if _job_scalar(publish, "runs-on") != "ubuntu-latest":
        errors.append("release publish job must run on the exact trusted ubuntu-latest runner")
    if _job_scalar(publish, "needs") != "[wheels, sdist, wasm]":
        errors.append(
            "release publish job must depend on the exact wheel, sdist, and wasm build jobs"
        )
    if _job_scalar(publish, "environment") != "pypi":
        errors.append("release publish job must use the exact protected pypi environment")
    if "password:" in publish or "api-token" in publish:
        errors.append("release publish job should use trusted publishing, not a PyPI token")
    expected_publish_permissions = {"contents": "read", "id-token": "write"}
    if _job_mapping(publish, "permissions") != expected_publish_permissions:
        errors.append(
            f"release publish job permissions must be exactly {expected_publish_permissions!r}"
        )
    publish_tag_block = _named_step_blocks(publish).get("Verify release tag source before PyPI")
    publish_tag_shell = _named_step_run(publish, "Verify release tag source before PyPI")
    publish_steps = _job_step_blocks(publish)
    expected_publish_step_names = [
        None,
        "Release version gate (tag == CHANGELOG)",
        None,
        "List artifacts",
        "Dry run summary (no PyPI publish)",
        "Verify release tag source before PyPI",
        None,
    ]
    publish_step_names = [_step_name(step) for step in publish_steps]
    publish_step_uses = [_step_uses(step) for step in publish_steps]
    publish_steps_are_exact = (
        publish_step_names == expected_publish_step_names
        and publish_step_uses
        == [
            [RELEASE_CHECKOUT_ACTION],
            [],
            [RELEASE_DOWNLOAD_ACTION],
            [],
            [],
            [],
            [PYPI_PUBLISH_ACTION],
        ]
        and [_step_direct_keys(step) for step in publish_steps]
        == [
            ["uses", "with"],
            ["name", "if", "run"],
            ["uses", "with"],
            ["name", "run"],
            ["name", "if", "run"],
            ["name", "if", "env", "shell", "run"],
            ["uses", "if", "with"],
        ]
        and _step_mapping(publish_steps[0], "with") == {"fetch-depth": "0"}
        and _step_scalar(publish_steps[1], "if") == "github.event_name == 'push'"
        and _step_run(publish_steps[1]) == "python3 scripts/check_release_version.py"
        and _step_mapping(publish_steps[2], "with")
        == {"merge-multiple": "true", "path": "dist", "pattern": "dist-*"}
        and _step_run(publish_steps[3]) == "ls -la dist/"
        and _step_scalar(publish_steps[4], "if")
        == "github.event_name == 'workflow_dispatch' && github.event.inputs.dry_run == 'true'"
        and _step_run(publish_steps[4])
        == (
            'echo "::notice::Dry run — built and verified '
            "$(ls dist/*.whl dist/*.tar.gz 2>/dev/null | wc -l | tr -d ' ') "
            'artifacts across the full release matrix. Skipping PyPI publish."\n'
            'echo "Re-run this workflow with dry_run=false, or push a v* tag, '
            'to publish for real."'
        )
        and _step_scalar(publish_steps[6], "if")
        == (
            "(github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')) || "
            "(github.event_name == 'workflow_dispatch' && "
            "github.event.inputs.dry_run == 'false')"
        )
        and _step_mapping(publish_steps[6], "with")
        == {"packages-dir": "dist/", "skip-existing": "true"}
    )
    if not publish_steps_are_exact:
        errors.append(
            "release publish job must contain exactly the pinned artifact download, "
            "fixed diagnostics, verified tag guard, and pinned PyPI publisher steps"
        )
    publish_action_position = publish.find("pypa/gh-action-pypi-publish@")
    publish_tag_position = publish.find("- name: Verify release tag source before PyPI")
    if publish_tag_block is None or publish_tag_shell is None:
        errors.append("release publish job must verify the current tag source before PyPI")
    else:
        expected_release_env = {
            "GH_TOKEN": "${{ github.token }}",
            "REPO": "${{ github.repository }}",
            "TAG": "${{ github.ref_name }}",
        }
        if not (
            _step_has_exact_bash_run(publish_tag_block)
            and _step_direct_keys(publish_tag_block) == ["name", "if", "env", "shell", "run"]
            and _step_mapping(publish_tag_block, "env") == expected_release_env
        ):
            errors.append(
                "release publish tag guard must use exact step controls, environment, "
                "one direct `run`, and exact step-local `shell: bash`"
            )
        if _has_indirect_shell_execution(publish_tag_shell):
            errors.append("release publish tag guard must not use indirect shell execution")
        if _gh_api_write_requests(publish_tag_shell):
            errors.append("release publish tag guard must not make write-mode gh api requests")
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
        publish,
        "pypa/gh-action-pypi-publish@",
        CORE_PYPI_PUBLISH_GATE,
    ):
        errors.append(
            "release publish job's PyPI upload step is not gated by the dry-run "
            f"predicate on the step itself (`{CORE_PYPI_PUBLISH_GATE}`) — a missing or "
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
        expected_job_keys = [
            "name",
            "if",
            "needs",
            "runs-on",
            "timeout-minutes",
            "permissions",
            "steps",
        ]
        if _job_direct_keys(github_release) != expected_job_keys:
            errors.append(
                "release github-release job must use exact control keys with no defaults, "
                "environment overrides, or continue-on-error bypass"
            )
        if _job_scalar(github_release, "runs-on") != "ubuntu-latest":
            errors.append(
                "release github-release job must run on the exact trusted ubuntu-latest runner"
            )
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
        step_identities = [
            (
                _step_name(step),
                tuple(_step_uses(step)),
                _step_declares_run(step),
            )
            for step in job_steps
        ]
        expected_step_identities = [
            (None, (RELEASE_DOWNLOAD_ACTION,), False),
            ("Inspect existing release", (), True),
            ("Prepare release provenance", (), True),
            ("Attest release provenance", (RELEASE_ATTEST_ACTION,), False),
            ("Create GitHub Release and attach distributions", (), True),
        ]
        if step_identities != expected_step_identities:
            errors.append(
                "release github-release job must contain exactly the pinned download, "
                "immutable preflight, provenance preparation, pinned attestation, and "
                f"publication steps in that order; found {step_identities!r}"
            )
        expected_step_keys = [
            ["uses", "with"],
            ["name", "id", "env", "shell", "run"],
            ["name", "if", "env", "shell", "run"],
            ["name", "if", "uses", "with"],
            ["name", "env", "shell", "run"],
        ]
        if [_step_direct_keys(step) for step in job_steps] != expected_step_keys:
            errors.append(
                "release github-release steps must use exact control keys; explicit "
                "`if`, `continue-on-error`, working-directory, or duplicate keys are forbidden"
            )
        expected_release_env = {
            "GH_TOKEN": "${{ github.token }}",
            "REPO": "${{ github.repository }}",
            "TAG": "${{ github.ref_name }}",
        }
        step_mappings_are_exact = len(job_steps) == 5 and (
            _step_mapping(job_steps[0], "with")
            == {
                "path": "dist",
                "pattern": "dist-*",
                "merge-multiple": "true",
            }
            and _step_scalar(job_steps[1], "id") == "release_state"
            and _step_mapping(job_steps[1], "env") == expected_release_env
            and _step_mapping(job_steps[2], "env") == expected_release_env
            and _step_mapping(job_steps[3], "with")
            == {
                "subject-path": (
                    "${{ runner.temp }}/xy-${{ github.ref_name }}"
                    "-release-provenance/xy-release-provenance.json"
                )
            }
            and _step_mapping(job_steps[4], "env") == expected_release_env
        )
        if not step_mappings_are_exact:
            errors.append(
                "release github-release steps must use exact environments, action inputs, "
                "and immutable-state output identity"
            )
        invalid_step_shapes = [
            _step_name(step) or "<unnamed>"
            for step in job_steps
            if _step_declares_run(step) == bool(_step_uses(step))
        ]
        if invalid_step_shapes:
            errors.append(
                "release github-release job steps must declare exactly one inspectable "
                f"`run` or allowlisted `uses` action; found {invalid_step_shapes}"
            )
        action_uses = [uses for step in job_steps for uses in _step_uses(step)]
        expected_action_uses = [RELEASE_DOWNLOAD_ACTION, RELEASE_ATTEST_ACTION]
        if action_uses != expected_action_uses:
            errors.append(
                "release github-release job action steps must be exactly the pinned "
                "download and provenance-attestation actions; found "
                f"{action_uses!r}"
            )
        unsupported_shell_steps = [
            _step_name(step) or "<unnamed>"
            for step in job_steps
            if _step_declares_run(step) and not _step_has_exact_bash_run(step)
        ]
        if unsupported_shell_steps:
            errors.append(
                "release github-release job must give every inspected shell step exactly "
                "one direct `run` and one exact step-local `shell: bash`; found "
                f"{unsupported_shell_steps}"
            )
        uninspectable_run_steps = [
            _step_name(step) or "<unnamed>"
            for step in job_steps
            if _step_uses_uninspectable_run(step)
        ]
        if uninspectable_run_steps:
            errors.append(
                "release github-release job must use literal `run: |` blocks so every "
                "shell step can be inspected for release mutations; found unsupported "
                f"`run` scalars in {uninspectable_run_steps}"
            )
        indirect_shell_steps = [
            _step_name(step) or "<unnamed>"
            for step in job_steps
            if (shell := _step_run(step)) is not None and _has_indirect_shell_execution(shell)
        ]
        if indirect_shell_steps:
            errors.append(
                "release github-release job must not hide release behavior behind "
                f"indirect shell execution; found it in {indirect_shell_steps}"
            )
        expected_api_writes = {
            "Inspect existing release": [],
            "Prepare release provenance": [("POST", "repos/${REPO}/releases/generate-notes")],
            "Create GitHub Release and attach distributions": [
                ("DELETE", "repos/${REPO}/releases/assets/${asset_id}")
            ],
        }
        unexpected_api_write_steps = [
            _step_name(step) or "<unnamed>"
            for step in job_steps
            if (shell := _step_run(step)) is not None
            and _gh_api_write_requests(shell) != expected_api_writes.get(_step_name(step), [])
        ]
        if unexpected_api_write_steps:
            errors.append(
                "release github-release shell steps may declare only the exact "
                "generated-notes POST and release-asset DELETE API writes; found "
                f"unexpected writes in {unexpected_api_write_steps}"
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
            if _has_indirect_shell_execution(inspect_shell):
                errors.append(
                    "release immutable-release preflight must not use indirect shell execution"
                )
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
            if _has_indirect_shell_execution(prepare_shell):
                errors.append(
                    "release provenance preparation must not use indirect shell execution"
                )
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
                _assignment_lines(prepare_lines, "tag_source_sha")
                == ["local tag_source_sha", 'if ! tag_source_sha="$(']
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
        attest_pin = RELEASE_ATTEST_ACTION
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
            if _has_indirect_shell_execution(release_shell):
                errors.append("release publication step must not use indirect shell execution")
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
            release_lookup_is_fail_closed = (
                _assignment_lines(logical_lines, "release_lookup_error")
                == [
                    'release_lookup_error="$(mktemp "${RUNNER_TEMP}/xy-release-view-error.XXXXXX")"'
                ]
                and _logical_line_is(
                    logical_lines,
                    initial_view_position - 2,
                    'release_lookup_error="$(mktemp '
                    '"${RUNNER_TEMP}/xy-release-view-error.XXXXXX")"',
                )
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 4,
                    "elif ! jq -eRs '. == \"release not found\\n\"' "
                    '"$release_lookup_error" >/dev/null; then',
                )
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 5,
                    'cat "$release_lookup_error" >&2',
                )
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 6,
                    'rm -f "$release_lookup_error"',
                )
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 7,
                    'echo "::error::Could not inspect existing GitHub Release '
                    '${TAG}; refusing to create it"',
                )
                and _logical_line_is(logical_lines, initial_view_position + 8, "exit 1")
                and _logical_line_is(logical_lines, initial_view_position + 9, "fi")
                and _logical_line_is(
                    logical_lines,
                    initial_view_position + 10,
                    'rm -f "$release_lookup_error"',
                )
            )
            if not release_lookup_is_fail_closed:
                errors.append(
                    "release github-release job must treat only an exact `release not found` "
                    "lookup result as absent and fail closed on every other metadata-read error"
                )
            immutable_state_is_exact = (
                _assignment_lines(logical_lines, "release_exists")
                == ["release_exists=false", "release_exists=true"]
                and _assignment_lines(logical_lines, "is_immutable")
                == [
                    "is_immutable=false",
                    'is_immutable="$(jq -r \'.isImmutable\' <<<"$release_json")"',
                ]
                and release_lookup_is_fail_closed
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
                and logical_lines.count('if [[ "$release_exists" == true ]]; then') == 1
                and logical_lines.count('if [[ "$is_immutable" == "true" ]]; then') == 1
            )
            if not (
                len(tag_resolution_positions) == 1
                and _assignment_lines(logical_lines, "tag_source_sha")
                == ["local tag_source_sha", 'if ! tag_source_sha="$(']
                and _shell_function_definition_count(release_shell, "verify_tag_source") == 1
                and _shell_function_definition_count(release_shell, "release_metadata_matches") == 1
                and _shell_function_definition_count(release_shell, "verify_release_payload") == 1
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
    if _workflow_direct_keys(text) != [
        "name",
        "on",
        "permissions",
        "concurrency",
        "jobs",
    ]:
        errors.append(
            "docs deploy workflow must use exact top-level controls with no inherited "
            "environment or run defaults"
        )
    if _workflow_mapping(text, "permissions") != {"contents": "read"}:
        errors.append("docs deploy workflow top-level permissions must be exactly contents: read")
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
    if _job_direct_keys(release_gate) != [
        "name",
        "needs",
        "runs-on",
        "timeout-minutes",
        "permissions",
        "steps",
    ]:
        errors.append(
            "docs deploy release gate job must use exact control keys with no inherited "
            "environment, defaults, or continue-on-error bypass"
        )
    if _job_scalar(release_gate, "runs-on") != "ubuntu-latest":
        errors.append(
            "docs deploy release gate job must run on the exact trusted ubuntu-latest runner"
        )
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
    else:
        expected_production_needs = "[prepare, await-prod-approval, verify-library-release]"
        expected_production_with = {
            "auto_merge": "true",
            "environment": "prod",
            "image_tag": "${{ needs.prepare.outputs.version }}",
            "source_ref": "${{ needs.prepare.outputs.source_sha }}",
        }
        if not (
            _job_direct_keys(production)
            == ["name", "needs", "permissions", "uses", "with", "secrets"]
            and _job_scalar(production, "needs") == expected_production_needs
            and _job_mapping(production, "permissions") == {"contents": "read"}
            and _job_scalar(production, "uses") == "./.github/workflows/_helm-docs-pr.yml"
            and _job_mapping(production, "with") == expected_production_with
            and _job_scalar(production, "secrets") == "inherit"
        ):
            errors.append(
                "docs deploy production Helm promotion must use the exact reusable "
                "workflow controls and depend on verify-library-release without bypasses"
            )

    gate_step = _named_step_blocks(release_gate).get("Await GitHub Release and PyPI availability")
    gate_steps = _job_step_blocks(release_gate)
    gate_shell = _named_step_run(
        release_gate,
        "Await GitHub Release and PyPI availability",
    )
    if gate_step is None or gate_shell is None:
        errors.append("docs deploy release gate is missing its active polling shell step")
        return errors
    if len(gate_steps) != 1 or gate_steps[0] != gate_step:
        errors.append(
            "docs deploy release gate job must contain exactly its one verified polling step"
        )
    expected_gate_env = {
        "GH_TOKEN": "${{ github.token }}",
        "VERSION": "${{ needs.prepare.outputs.version }}",
        "SOURCE_SHA": "${{ needs.prepare.outputs.source_sha }}",
        "REPO": "${{ github.repository }}",
    }
    if not (
        _step_has_exact_bash_run(gate_step)
        and _step_direct_keys(gate_step) == ["name", "env", "shell", "run"]
        and _step_mapping(gate_step, "env") == expected_gate_env
    ):
        errors.append(
            "docs deploy release gate must use exact step controls, environment, "
            "one direct `run`, and exact step-local `shell: bash`"
        )
    if _has_indirect_shell_execution(gate_shell):
        errors.append("docs deploy release gate must not use indirect shell execution")
    if _gh_api_write_requests(gate_shell):
        errors.append("docs deploy release gate must not make write-mode gh api requests")
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
