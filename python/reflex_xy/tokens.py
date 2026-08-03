"""Figure tokens: the only chart-related value that lives in Reflex state.

Two token families, one namespace:

- **State tokens** (`xyv1|<client_token>|<state_full_name>|<var_name>`) are
  minted by the `@reflex_xy.figure` computed var. They are *deterministic*:
  any backend worker holding the same Reflex state can re-derive the figure
  from the token alone, which is what makes reconnects and multi-worker
  deployments work without a central figure store (the token IS the recipe;
  Reflex state is the pantry).
- **Opaque tokens** (`xyfig-<uuid>`) come from imperative
  `reflex_xy.register(...)`. They cannot be rebuilt elsewhere — dev-tier by
  design, documented in spec/design/reflex-integration.md.

Tokens are visible to their own client (they ride through state deltas), so
they must not carry anything the client doesn't already know: the client
token is the browser tab's own session id, and state/var names already
appear in every state delta. Cross-client use is refused by the namespace's
affinity check, not by token secrecy.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "ParsedToken",
    "build_state_token",
    "builder_of",
    "parse_token",
]

_PREFIX = "xyv1"
_SEP = "|"
# Client tokens are UUID-ish; state full names and var names are dotted
# Python identifiers. Nothing here may contain the separator.
_TOKEN_RE = re.compile(
    r"^xyv1\|(?P<client>[A-Za-z0-9_-]{8,64})"
    r"\|(?P<state>[A-Za-z0-9_.]{1,512})"
    r"\|(?P<var>[A-Za-z_][A-Za-z0-9_]{0,255})$"
)

#: Attribute stashed on a figure var's fget carrying the user's builder.
#: It lives on the *function* (not the ComputedVar) so it survives reflex's
#: `_replace` copies, which re-instantiate the var but thread fget through.
BUILDER_ATTR = "__xy_builder__"


@dataclass(frozen=True)
class ParsedToken:
    client_token: str
    state_full_name: str
    var_name: str


def build_state_token(client_token: str, state_full_name: str, var_name: str) -> str:
    token = _SEP.join((_PREFIX, client_token, state_full_name, var_name))
    if parse_token(token) is None:
        # Defensive: a state or client token that defeats the grammar would
        # otherwise mint a token the namespace can never resolve.
        msg = f"cannot build a valid figure token from {client_token!r}/{state_full_name!r}/{var_name!r}"
        raise ValueError(msg)
    return token


def parse_token(token: str) -> Optional[ParsedToken]:
    """Parse a state token; None for opaque/foreign strings (fail closed)."""
    if not isinstance(token, str):
        return None
    match = _TOKEN_RE.match(token)
    if match is None:
        return None
    return ParsedToken(
        client_token=match["client"],
        state_full_name=match["state"],
        var_name=match["var"],
    )


def builder_of(state_cls: Any, var_name: str) -> Optional[Callable[[Any], Any]]:
    """Find the figure builder a `@reflex_xy.figure` var attached to a state class."""
    computed = getattr(state_cls, "computed_vars", None)
    var = computed.get(var_name) if isinstance(computed, dict) else None
    fget = getattr(var, "_fget", None)
    return getattr(fget, BUILDER_ATTR, None)
