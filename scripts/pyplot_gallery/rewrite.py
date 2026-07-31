"""Token-preserving, AST-verified pyplot import rewriting.

The gallery contract deliberately changes one thing in an upstream example:
the module which supplies ``pyplot``.  Reformatting a complete example with
``ast.unparse`` would make review and provenance needlessly difficult, while a
plain string replacement can alter comments, strings, or unrelated imports.
This module changes only import tokens and then proves that the resulting AST
is exactly the expected import-only transformation.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass


class PyplotRewriteError(ValueError):
    """The source cannot be safely rewritten as a pyplot drop-in test."""


@dataclass(frozen=True)
class RewriteResult:
    """A verified import rewrite and its audit metadata."""

    source: str
    import_count: int
    original_ast: str
    rewritten_ast: str


def pyplot_imports(tree: ast.AST) -> list[dict[str, object]]:
    """Return direct pyplot imports in source order."""

    imports: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "matplotlib.pyplot":
                    imports.append(
                        {
                            "kind": "import",
                            "alias": alias.asname,
                            "line": node.lineno,
                        }
                    )
        elif isinstance(node, ast.ImportFrom) and node.module == "matplotlib":
            for alias in node.names:
                if alias.name == "pyplot":
                    imports.append(
                        {
                            "kind": "from",
                            "alias": alias.asname,
                            "line": node.lineno,
                        }
                    )
    return sorted(imports, key=lambda item: (int(item["line"]), str(item["kind"])))


class _ExpectedRewrite(ast.NodeTransformer):
    """Construct the only AST that a successful rewrite is allowed to emit."""

    def __init__(self) -> None:
        self.count = 0

    def visit_Import(self, node: ast.Import) -> ast.AST:
        for alias in node.names:
            if alias.name != "matplotlib.pyplot":
                continue
            if alias.asname is None:
                raise PyplotRewriteError(
                    "`import matplotlib.pyplot` without an alias binds `matplotlib`; "
                    "rewriting it would change the program's binding"
                )
            alias.name = "xy.pyplot"
            self.count += 1
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        pyplot_aliases = [alias for alias in node.names if alias.name == "pyplot"]
        if node.module != "matplotlib" or not pyplot_aliases:
            return node
        if len(node.names) != 1:
            raise PyplotRewriteError(
                "a mixed `from matplotlib import ...` statement cannot be rewritten "
                "without also changing non-pyplot imports"
            )
        node.module = "xy"
        self.count += 1
        return node


def _significant(tokens: list[tokenize.TokenInfo], index: int) -> int | None:
    ignored = {
        tokenize.ENCODING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.COMMENT,
    }
    while index < len(tokens):
        if tokens[index].type not in ignored:
            return index
        index += 1
    return None


def _rewrite_tokens(source: str) -> tuple[str, int]:
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    replacements: set[int] = set()

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string != "matplotlib":
            continue

        previous = index - 1
        while previous >= 0 and tokens[previous].type in {
            tokenize.NL,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.COMMENT,
        }:
            previous -= 1
        before = tokens[previous].string if previous >= 0 else None

        following = _significant(tokens, index + 1)
        if before == "import" and following is not None and tokens[following].string == ".":
            pyplot = _significant(tokens, following + 1)
            if pyplot is not None and tokens[pyplot].string == "pyplot":
                replacements.add(index)
        elif before == "from":
            imported = _significant(tokens, index + 1)
            if imported is not None and tokens[imported].string == "import":
                name = _significant(tokens, imported + 1)
                if name is not None and tokens[name].string in {"(", "pyplot"}:
                    replacements.add(index)

    rewritten = [
        token._replace(string="xy") if index in replacements else token
        for index, token in enumerate(tokens)
    ]
    return tokenize.untokenize(rewritten), len(replacements)


def rewrite_pyplot_imports(source: str, *, filename: str = "<gallery-example>") -> RewriteResult:
    """Rewrite direct Matplotlib pyplot imports and verify the complete AST.

    Strings, comments, formatting, and all non-pyplot imports remain byte-for-
    byte stable.  Unsupported or ambiguous import forms fail closed.
    """

    original_tree = ast.parse(source, filename=filename)
    expected_tree = ast.parse(source, filename=filename)
    expected = _ExpectedRewrite()
    expected.visit(expected_tree)
    ast.fix_missing_locations(expected_tree)
    if expected.count == 0:
        raise PyplotRewriteError("example has no direct matplotlib.pyplot import")

    rewritten_source, token_count = _rewrite_tokens(source)
    if token_count != expected.count:
        raise PyplotRewriteError(
            f"token rewrite count {token_count} does not match AST import count {expected.count}"
        )

    rewritten_tree = ast.parse(rewritten_source, filename=filename)
    expected_dump = ast.dump(expected_tree, include_attributes=False)
    rewritten_dump = ast.dump(rewritten_tree, include_attributes=False)
    if rewritten_dump != expected_dump:
        raise PyplotRewriteError("rewritten AST contains changes beyond the pyplot import")

    return RewriteResult(
        source=rewritten_source,
        import_count=expected.count,
        original_ast=ast.dump(original_tree, include_attributes=False),
        rewritten_ast=rewritten_dump,
    )
