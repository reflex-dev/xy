"""Chart tokens: the only chart-related values that live in Reflex state.

Three token families, one namespace:

- **Figure state tokens** (`xyv1|<client_token>|<state_full_name>|<var_name>`)
  are minted by the `@reflex_xy.figure` computed var. They are
  *deterministic*: any backend worker holding the same Reflex state can
  re-derive the figure from the token alone, which is what makes reconnects
  and multi-worker deployments work without a central figure store (the
  token IS the recipe; Reflex state is the pantry).
- **Data state tokens** (`xyd1|<client_token>|<state_full_name>|<var_name>`)
  are minted by the `@reflex_xy.data` computed var under the same grammar
  and rebuild contract, naming a registered *column set* instead of a
  figure. They never subscribe alone: the wrapper composes them with a plan
  digest into a **plan token** (`xyp1|<digest>|<data token>`), the composite
  figure identity of the data-bound tier — plan digest for the structure,
  data token for the columns; both halves independently recoverable.
- **Opaque tokens** (`xyfig-<uuid>` / `xyin-<digest>`) come from imperative
  `reflex_xy.register(...)` / `inline(...)`. They cannot be rebuilt
  elsewhere — dev/fixed tiers by design, documented in
  spec/design/reflex-integration.md.

Tokens are visible to their own client (they ride through state deltas), so
they must not carry anything the client doesn't already know: the client
token is the browser tab's own session id, state/var names already appear
in every state delta, and a plan digest is a content address of page code
the client was compiled from. Cross-client use is refused by the
namespace's affinity check, not by token secrecy.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "ParsedPlanToken",
    "ParsedToken",
    "build_data_token",
    "build_plan_token",
    "build_state_token",
    "builder_of",
    "parse_plan_token",
    "parse_token",
]

_FIGURE_PREFIX = "xyv1"
_DATA_PREFIX = "xyd1"
_PLAN_PREFIX = "xyp1"
_SEP = "|"
# Client tokens are UUID-ish; state full names and var names are dotted
# Python identifiers. Nothing here may contain the separator.
_STATE_TOKEN_BODY = (
    r"(?P<client>[A-Za-z0-9_-]{8,64})"
    r"\|(?P<state>[A-Za-z0-9_.]{1,512})"
    r"\|(?P<var>[A-Za-z_][A-Za-z0-9_]{0,255})$"
)
_TOKEN_RE = re.compile(r"^(?P<prefix>xyv1|xyd1)\|" + _STATE_TOKEN_BODY)
# Plan digests are lowercase sha256 hex prefixes (plan.py).
_PLAN_RE = re.compile(r"^xyp1\|(?P<digest>[0-9a-f]{8,64})\|(?P<data>xyd1\|.+)$")

#: Attribute stashed on a figure/data var's fget carrying the user's builder.
#: It lives on the *function* (not the ComputedVar) so it survives reflex's
#: `_replace` copies, which re-instantiate the var but thread fget through.
BUILDER_ATTR = "__xy_builder__"


@dataclass(frozen=True)
class ParsedToken:
    """A parsed state token; ``kind`` is ``"figure"`` (xyv1) or ``"data"`` (xyd1)."""

    client_token: str
    state_full_name: str
    var_name: str
    kind: str = "figure"


@dataclass(frozen=True)
class ParsedPlanToken:
    """A parsed composite plan token: plan digest + the embedded data token."""

    digest: str
    data: ParsedToken
    data_token: str  # the verbatim xyd1|… substring (registry key for columns)


def _build_state_token(prefix: str, client_token: str, state_full_name: str, var_name: str) -> str:
    token = _SEP.join((prefix, client_token, state_full_name, var_name))
    if _TOKEN_RE.match(token) is None:
        # Defensive: a state or client token that defeats the grammar would
        # otherwise mint a token the namespace can never resolve.
        msg = f"cannot build a valid {prefix} token from {client_token!r}/{state_full_name!r}/{var_name!r}"
        raise ValueError(msg)
    return token


def build_state_token(client_token: str, state_full_name: str, var_name: str) -> str:
    """Mint a figure token (`xyv1|…`)."""
    return _build_state_token(_FIGURE_PREFIX, client_token, state_full_name, var_name)


def build_data_token(client_token: str, state_full_name: str, var_name: str) -> str:
    """Mint a data token (`xyd1|…`)."""
    return _build_state_token(_DATA_PREFIX, client_token, state_full_name, var_name)


def build_plan_token(digest: str, data_token: str) -> str:
    """Compose the data-bound tier's figure identity (`xyp1|<digest>|<data>`)."""
    token = _SEP.join((_PLAN_PREFIX, digest, data_token))
    if parse_plan_token(token) is None:
        msg = f"cannot build a valid plan token from {digest!r}/{data_token!r}"
        raise ValueError(msg)
    return token


def parse_token(token: str) -> Optional[ParsedToken]:
    """Parse a state token (figure or data); None for opaque/foreign strings
    (fail closed). Composite plan tokens parse via :func:`parse_plan_token`."""
    if not isinstance(token, str):
        return None
    match = _TOKEN_RE.match(token)
    if match is None:
        return None
    return ParsedToken(
        client_token=match["client"],
        state_full_name=match["state"],
        var_name=match["var"],
        kind="figure" if match["prefix"] == _FIGURE_PREFIX else "data",
    )


def parse_plan_token(token: str) -> Optional[ParsedPlanToken]:
    """Parse a composite plan token; None for anything else (fail closed)."""
    if not isinstance(token, str):
        return None
    match = _PLAN_RE.match(token)
    if match is None:
        return None
    data = parse_token(match["data"])
    if data is None or data.kind != "data":
        return None
    return ParsedPlanToken(digest=match["digest"], data=data, data_token=match["data"])


def builder_of(state_cls: Any, var_name: str) -> Optional[Callable[[Any], Any]]:
    """Find the builder a `@reflex_xy.figure` / `@reflex_xy.data` var
    attached to a state class."""
    computed = getattr(state_cls, "computed_vars", None)
    var = computed.get(var_name) if isinstance(computed, dict) else None
    fget = getattr(var, "_fget", None)
    return getattr(fget, BUILDER_ATTR, None)
