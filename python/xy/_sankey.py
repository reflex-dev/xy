"""Sankey layout — the part of a flow diagram that is not a rendering problem.

A Sankey is not a new primitive so much as a *placement*: given nodes, weighted
links and a box, decide where every node rectangle and every ribbon endpoint
goes. That decision is what the roadmap means by "requires layout work"
(spec/api/chart-roadmap.md item 30), and it is pure arithmetic, so it lives here
in Python, testable on its own, exactly as `wind_rose`'s binning and
`radar_chart`'s angle derivation do.

The output is in **data space**: x runs 0..1 across the layers and y runs 0..1
down the diagram, so the caller maps it through ordinary axes and every
renderer inherits the placement unchanged. Nothing here knows about pixels.

The algorithm is the conventional one (d3-sankey's shape, and ECharts' before
it), in five passes:

1. **Layer assignment** — longest path from a source, so a node sits one layer
   right of its deepest upstream neighbour. Sinks optionally re-align to the
   last layer (`align="justify"`), which is what makes the right edge flush.
2. **Node value** — `max(sum of inflow, sum of outflow)`; a node that emits more
   than it receives is still as tall as it emits.
3. **Crossing minimisation** — alternating left/right barycentre sweeps. This is
   a heuristic: optimal crossing minimisation is NP-hard, and the median/
   barycentre sweep is the standard, cheap answer that gets most of the way.
4. **Vertical placement** — value-proportional heights, fixed padding between
   nodes in a layer, then the whole column centred in the box.
5. **Endpoint stacking** — links leave a node ordered by where they arrive, and
   arrive ordered by where they left, which is what stops a node's own ribbons
   from crossing each other immediately.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Optional

_ALIGNMENTS = frozenset({"justify", "left", "right", "center"})


@dataclass
class SankeyNode:
    """One placed node. `x0/x1/y0/y1` are in the 0..1 layout box."""

    name: str
    index: int
    layer: int = 0
    order: int = 0
    value: float = 0.0
    x0: float = 0.0
    x1: float = 0.0
    y0: float = 0.0
    y1: float = 0.0
    incoming: list[int] = field(default_factory=list)
    outgoing: list[int] = field(default_factory=list)


@dataclass
class SankeyLink:
    """One placed link. The two endpoints are vertical spans, not points."""

    source: int
    target: int
    value: float
    index: int = 0
    source_y0: float = 0.0
    source_y1: float = 0.0
    target_y0: float = 0.0
    target_y1: float = 0.0
    label: Optional[str] = None


@dataclass
class SankeyLayout:
    nodes: list[SankeyNode]
    links: list[SankeyLink]
    layers: int


def _resolve_nodes(
    nodes: Optional[list[Any]], links: list[tuple[Any, Any, float]]
) -> tuple[list[str], dict[str, int]]:
    """Node names in a stable order, plus their index.

    When `nodes` is omitted the order is first-appearance across the links,
    which keeps a diagram's column order predictable from the source data
    rather than from a set's iteration order.
    """
    if nodes is not None:
        names = [str(n) for n in nodes]
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicates:
            raise ValueError(f"sankey nodes must be unique; repeated: {duplicates}")
    else:
        names = []
        seen: set[str] = set()
        for source, target, _value in links:
            for endpoint in (str(source), str(target)):
                if endpoint not in seen:
                    seen.add(endpoint)
                    names.append(endpoint)
    return names, {name: i for i, name in enumerate(names)}


def _cyclic_nodes(nodes: list[SankeyNode], links: list[SankeyLink]) -> list[str]:
    """Names of the nodes that actually lie on a cycle.

    Tarjan's strongly connected components, iteratively: a node is cyclic iff
    its component has more than one member (self-links are refused earlier).
    Kahn's leftover set would also blame everything *downstream* of a cycle,
    sending the user off to remove nodes that were never part of the problem.
    Only runs to build the refusal message, so clarity beats constant factors.
    """
    order = [-1] * len(nodes)
    low = [0] * len(nodes)
    on_stack = [False] * len(nodes)
    stack: list[int] = []
    count = 0
    cyclic: list[str] = []
    for root in range(len(nodes)):
        if order[root] != -1:
            continue
        work: list[tuple[int, int]] = [(root, 0)]
        while work:
            current, edge = work.pop()
            if edge == 0:
                order[current] = low[current] = count
                count += 1
                stack.append(current)
                on_stack[current] = True
            descended = False
            outgoing = nodes[current].outgoing
            while edge < len(outgoing):
                child = links[outgoing[edge]].target
                edge += 1
                if order[child] == -1:
                    work.append((current, edge))
                    work.append((child, 0))
                    descended = True
                    break
                if on_stack[child]:
                    low[current] = min(low[current], order[child])
            if descended:
                continue
            if low[current] == order[current]:
                component: list[int] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == current:
                        break
                if len(component) > 1:
                    cyclic.extend(nodes[member].name for member in component)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[current])
    return sorted(cyclic)


def _assign_layers(nodes: list[SankeyNode], links: list[SankeyLink]) -> int:
    """Longest-path layering, with an explicit cycle refusal.

    Kahn's algorithm: repeatedly strip nodes with no unplaced predecessor. A
    node left over when the queue empties is part of a cycle, which a Sankey
    cannot express — flow would have to reach a column left of where it
    started — so it is refused by name rather than drawn wrong.
    """
    indegree = [0] * len(nodes)
    for link in links:
        indegree[link.target] += 1
    queue = deque(n.index for n in nodes if indegree[n.index] == 0)
    placed = 0
    while queue:
        current = queue.popleft()
        placed += 1
        for link_index in nodes[current].outgoing:
            link = links[link_index]
            nodes[link.target].layer = max(nodes[link.target].layer, nodes[current].layer + 1)
            indegree[link.target] -= 1
            if indegree[link.target] == 0:
                queue.append(link.target)
    if placed != len(nodes):
        stuck = _cyclic_nodes(nodes, links)
        raise ValueError(
            f"sankey links form a cycle through {stuck}; a Sankey flows left to right, "
            "so every link must point to a later stage. Break the cycle or aggregate "
            "the nodes involved."
        )
    return max((n.layer for n in nodes), default=0) + 1


def _heights(nodes: list[SankeyNode], links: list[SankeyLink]) -> list[int]:
    """Longest path from each node to a sink — `_assign_layers` mirrored.

    Runs after the cycle refusal, so the reverse Kahn sweep always drains.
    """
    outdegree = [len(node.outgoing) for node in nodes]
    height = [0] * len(nodes)
    queue = deque(n.index for n in nodes if outdegree[n.index] == 0)
    while queue:
        current = queue.popleft()
        for link_index in nodes[current].incoming:
            link = links[link_index]
            height[link.source] = max(height[link.source], height[current] + 1)
            outdegree[link.source] -= 1
            if outdegree[link.source] == 0:
                queue.append(link.source)
    return height


def _align(nodes: list[SankeyNode], links: list[SankeyLink], layers: int, alignment: str) -> None:
    """Re-layer nodes per the requested alignment (d3-sankey's four).

    `left` keeps the longest-path layering as assigned. `justify` pushes sinks
    to the last layer for a flush right edge. `right` hangs every node by its
    distance to a sink, so sources start late instead of early. `center` keeps
    sinks in place but moves source-only nodes just left of their nearest
    target, so an isolated late branch does not open at the far left.
    """
    if alignment == "left" or layers < 2:
        return
    if alignment == "justify":
        for node in nodes:
            if not node.outgoing:
                node.layer = layers - 1
    elif alignment == "right":
        height = _heights(nodes, links)
        for node in nodes:
            node.layer = layers - 1 - height[node.index]
    elif alignment == "center":
        for node in nodes:
            if not node.incoming and node.outgoing:
                nearest = min(nodes[links[i].target].layer for i in node.outgoing)
                node.layer = max(nearest - 1, 0)


def _order_layers(
    nodes: list[SankeyNode], links: list[SankeyLink], layers: int, iterations: int
) -> list[list[int]]:
    """Barycentre sweeps, alternating direction.

    Each pass re-sorts one layer by the mean position of its neighbours in the
    already-ordered adjacent layer. Sweeping both ways matters: a left-to-right
    pass only ever considers inflow, so it leaves the last layer ordered by
    nothing at all.
    """
    columns: list[list[int]] = [[] for _ in range(layers)]
    for node in nodes:
        columns[node.layer].append(node.index)
    for column in columns:
        column.sort()

    def positions() -> dict[int, float]:
        return {index: rank for column in columns for rank, index in enumerate(column)}

    for sweep in range(iterations):
        forward = sweep % 2 == 0
        order = range(1, layers) if forward else range(layers - 2, -1, -1)
        pos = positions()
        for layer in order:
            neighbours = "incoming" if forward else "outgoing"

            # `pos` and `which` are bound as defaults, not captured: the sort
            # runs inside the loop that rebinds them, and a late-binding
            # closure would silently rank against the *next* pass's positions.
            def barycentre(
                index: int, which: str = neighbours, ranks: dict[int, float] = pos
            ) -> float:
                related = getattr(nodes[index], which)
                if not related:
                    # No neighbour to follow: hold the current rank so an
                    # unconnected node does not jump to the top every sweep.
                    return float(ranks.get(index, 0))
                other = [
                    ranks.get(links[i].source if which == "incoming" else links[i].target, 0)
                    for i in related
                ]
                return sum(other) / len(other)

            columns[layer].sort(key=barycentre)
            pos = positions()
    for column in columns:
        for rank, index in enumerate(column):
            nodes[index].order = rank
    return columns


def _place(
    nodes: list[SankeyNode],
    columns: list[list[int]],
    layers: int,
    node_width: float,
    node_padding: float,
) -> None:
    """Value-proportional heights in a 0..1 box, each column centred.

    The scale is shared across columns — the tallest column sets it — so a
    node's height means the same thing everywhere in the diagram. That is the
    whole point of a Sankey: area is comparable.
    """
    spans = []
    for layer, column in enumerate(columns):
        if not column:
            continue
        room = 1.0 - node_padding * (len(column) - 1)
        if room <= 0.0:
            # A negative room would flip the shared scale and draw every span
            # inverted; zero room collapses the whole diagram to nothing.
            # Refused by name rather than drawn wrong (§28).
            raise ValueError(
                f"sankey node_padding {node_padding:g} leaves no room for nodes: "
                f"layer {layer} holds {len(column)} of them, so node_padding must "
                f"stay below {1.0 / (len(column) - 1):g}"
            )
        total = sum(nodes[i].value for i in column)
        spans.append((total, len(column)))
    if not spans:
        return
    usable = [1.0 - node_padding * (count - 1) for _total, count in spans]
    scale = min(
        (room / total if total > 0 else math.inf)
        for room, (total, _c) in zip(usable, spans, strict=True)
    )
    if not math.isfinite(scale):
        scale = 0.0

    step = 1.0 if layers <= 1 else (1.0 - node_width) / (layers - 1)
    for layer, column in enumerate(columns):
        if not column:
            continue
        heights = [nodes[i].value * scale for i in column]
        extent = sum(heights) + node_padding * (len(column) - 1)
        cursor = (1.0 - extent) / 2.0
        for index, height in zip(column, heights, strict=True):
            node = nodes[index]
            node.x0 = layer * step
            node.x1 = node.x0 + node_width
            node.y0 = cursor
            node.y1 = cursor + height
            cursor = node.y1 + node_padding


def _stack_endpoints(nodes: list[SankeyNode], links: list[SankeyLink]) -> None:
    """Give every link its two vertical spans.

    Outgoing links are stacked in order of where they land, incoming in order
    of where they came from. Sorting each side by the *other* end is what keeps
    a node's own ribbons from crossing each other the moment they leave it.
    """
    for node in nodes:
        outgoing = sorted(node.outgoing, key=lambda i: (nodes[links[i].target].y0, links[i].index))
        cursor = node.y0
        for link_index in outgoing:
            link = links[link_index]
            height = (node.y1 - node.y0) * (link.value / node.value) if node.value > 0 else 0.0
            link.source_y0 = cursor
            link.source_y1 = cursor + height
            cursor = link.source_y1

        incoming = sorted(node.incoming, key=lambda i: (nodes[links[i].source].y0, links[i].index))
        cursor = node.y0
        for link_index in incoming:
            link = links[link_index]
            height = (node.y1 - node.y0) * (link.value / node.value) if node.value > 0 else 0.0
            link.target_y0 = cursor
            link.target_y1 = cursor + height
            cursor = link.target_y1


def compute_layout(
    links: list[tuple[Any, Any, float]],
    *,
    nodes: Optional[list[Any]] = None,
    node_width: float = 0.02,
    node_padding: float = 0.02,
    align: str = "justify",
    iterations: int = 6,
) -> SankeyLayout:
    """Place a Sankey in a 0..1 x 0..1 box.

    Args:
        links: ``(source, target, value)`` triples. Endpoints are node names.
        nodes: Explicit node order. Defaults to first appearance in `links`.
        node_width: Node rectangle width, as a fraction of the box.
        node_padding: Vertical gap between nodes in a layer, as a fraction.
        align: ``"justify"`` (default) flushes sinks to the last layer.
        iterations: Barycentre sweeps for crossing minimisation.

    Returns:
        A `SankeyLayout` whose coordinates are all in 0..1.
    """
    if align not in _ALIGNMENTS:
        raise ValueError(f"sankey align must be one of {sorted(_ALIGNMENTS)}")
    if not links:
        raise ValueError("sankey needs at least one link")
    if not 0.0 < node_width < 1.0:
        raise ValueError("sankey node_width must be between 0 and 1")
    if not 0.0 <= node_padding < 1.0:
        raise ValueError("sankey node_padding must be between 0 and 1")

    names, index_of = _resolve_nodes(nodes, links)
    placed_nodes = [SankeyNode(name=name, index=i) for i, name in enumerate(names)]
    placed_links: list[SankeyLink] = []
    seen: set[tuple[int, int]] = set()
    for position, (source, target, value) in enumerate(links):
        source_name, target_name = str(source), str(target)
        for endpoint in (source_name, target_name):
            if endpoint not in index_of:
                raise ValueError(
                    f"sankey link {position} references unknown node {endpoint!r}; "
                    f"known nodes are {names}"
                )
        si, ti = index_of[source_name], index_of[target_name]
        if si == ti:
            raise ValueError(
                f"sankey link {position} connects {source_name!r} to itself; "
                "a self-link has no width to draw and no direction to flow in"
            )
        weight = float(value)
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(
                f"sankey link {position} ({source_name} -> {target_name}) has value {value!r}; "
                "link values must be finite and non-negative"
            )
        if (si, ti) in seen:
            raise ValueError(
                f"sankey has duplicate link {source_name!r} -> {target_name!r}; "
                "sum the values into one link"
            )
        seen.add((si, ti))
        link = SankeyLink(source=si, target=ti, value=weight, index=len(placed_links))
        placed_nodes[si].outgoing.append(link.index)
        placed_nodes[ti].incoming.append(link.index)
        placed_links.append(link)

    layers = _assign_layers(placed_nodes, placed_links)
    _align(placed_nodes, placed_links, layers, align)
    for node in placed_nodes:
        node.value = max(
            sum(placed_links[i].value for i in node.incoming),
            sum(placed_links[i].value for i in node.outgoing),
        )
    columns = _order_layers(placed_nodes, placed_links, layers, iterations)
    _place(placed_nodes, columns, layers, node_width, node_padding)
    _stack_endpoints(placed_nodes, placed_links)
    return SankeyLayout(nodes=placed_nodes, links=placed_links, layers=layers)
