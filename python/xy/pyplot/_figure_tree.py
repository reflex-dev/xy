"""First-class ownership and resolved-layout tree for native pyplot figures.

The native shim historically inferred every relationship from ``Figure.axes``
at export time.  That flat list cannot distinguish an inset from an unrelated
overlay, a twin from a second panel, or renderer-owned colorbar chrome from a
real colorbar axes.  This module keeps those relationships explicit while
remaining independent of Matplotlib and of XY's concrete exporters.

All rectangles are normalized ``(left, bottom, width, height)`` coordinates in
the root figure.  Insets may lie outside their parent axes; their own clip is
therefore resolved against the nearest figure/subfigure container, not against
the parent axes' data clip.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

NormalizedRect: TypeAlias = tuple[float, float, float, float]
FigureNodeKind: TypeAlias = Literal[
    "figure",
    "subfigure",
    "axes",
    "inset_axes",
    "twin_axes",
    "colorbar_axes",
    "colorbar_chrome",
    "figure_text",
]


def normalized_rect(value: Any, *, label: str = "viewport") -> NormalizedRect:
    """Validate one normalized-coordinate rectangle without clamping it."""
    try:
        values = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be (left, bottom, width, height)") from exc
    if len(values) != 4 or not all(math.isfinite(item) for item in values):
        raise ValueError(f"{label} must contain four finite values")
    if values[2] < 0 or values[3] < 0:
        raise ValueError(f"{label} width and height must be nonnegative")
    return values


def intersect_rect(first: NormalizedRect, second: NormalizedRect) -> NormalizedRect:
    """Return the nonnegative intersection of two normalized rectangles."""
    left = max(first[0], second[0])
    bottom = max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    top = min(first[1] + first[3], second[1] + second[3])
    return left, bottom, max(0.0, right - left), max(0.0, top - bottom)


@dataclass(slots=True)
class FigureTreeNode:
    """Persistent native figure-tree node.

    ``viewport`` and ``clip`` are refreshed by the figure's measured layout
    solve, so callers inspecting the tree see the same geometry exporters use.
    ``rendered`` distinguishes semantic children such as a composited ``twinx``
    or virtual colorbar from independently composed axes panels.
    """

    node_id: str
    kind: FigureNodeKind
    owner: Any = field(repr=False)
    viewport: NormalizedRect = (0.0, 0.0, 1.0, 1.0)
    clip: NormalizedRect = (0.0, 0.0, 1.0, 1.0)
    parent: FigureTreeNode | None = field(default=None, repr=False)
    children: list[FigureTreeNode] = field(default_factory=list, repr=False)
    rendered: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def root(self) -> FigureTreeNode:
        node = self
        while node.parent is not None:
            node = node.parent
        return node

    def is_descendant_of(self, candidate: FigureTreeNode) -> bool:
        node = self.parent
        while node is not None:
            if node is candidate:
                return True
            node = node.parent
        return False


@dataclass(frozen=True, slots=True)
class ResolvedFigureNode:
    """Immutable node snapshot consumed by one export/layout operation."""

    node_id: str
    kind: FigureNodeKind
    owner: Any = field(repr=False, compare=False)
    viewport: NormalizedRect
    clip: NormalizedRect
    parent_id: str | None
    child_ids: tuple[str, ...]
    rendered: bool
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class ResolvedFigureTree:
    """One measured tree snapshot shared by every native exporter."""

    root: ResolvedFigureNode
    nodes: tuple[ResolvedFigureNode, ...]

    def for_owner(self, owner: Any) -> ResolvedFigureNode | None:
        return next((node for node in self.nodes if node.owner is owner), None)

    @property
    def axes(self) -> tuple[ResolvedFigureNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if node.kind in {"axes", "inset_axes", "twin_axes", "colorbar_axes"}
        )


class FigureTree:
    """Mutable ownership graph whose resolved snapshots are immutable."""

    def __init__(self, owner: Any) -> None:
        self._counter = 0
        self.root = self._new_node("figure", owner, parent=None)
        self._by_owner: dict[int, FigureTreeNode] = {id(owner): self.root}

    def _new_node(
        self,
        kind: FigureNodeKind,
        owner: Any,
        *,
        parent: FigureTreeNode | None,
        rendered: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> FigureTreeNode:
        self._counter += 1
        node = FigureTreeNode(
            node_id=f"{kind}-{self._counter}",
            kind=kind,
            owner=owner,
            parent=parent,
            rendered=rendered,
            metadata=dict(metadata or {}),
        )
        if parent is not None:
            parent.children.append(node)
        return node

    def node_for(self, owner: Any) -> FigureTreeNode | None:
        return self._by_owner.get(id(owner))

    def attach(
        self,
        kind: FigureNodeKind,
        owner: Any,
        *,
        parent: FigureTreeNode | None = None,
        rendered: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> FigureTreeNode:
        existing = self.node_for(owner)
        if existing is not None:
            existing.kind = kind
            existing.rendered = rendered
            if metadata is not None:
                existing.metadata = dict(metadata)
            if parent is not None and existing.parent is not parent:
                self.reparent(existing, parent)
            return existing
        node = self._new_node(
            kind,
            owner,
            parent=parent or self.root,
            rendered=rendered,
            metadata=metadata,
        )
        self._by_owner[id(owner)] = node
        return node

    def reparent(self, node: FigureTreeNode, parent: FigureTreeNode) -> None:
        if node is self.root or parent is node or parent.is_descendant_of(node):
            raise ValueError("figure-tree nodes cannot form a cycle")
        if node.parent is not None:
            node.parent.children.remove(node)
        node.parent = parent
        parent.children.append(node)

    def detach(self, owner: Any) -> None:
        node = self.node_for(owner)
        if node is None or node is self.root:
            return

        def forget(current: FigureTreeNode) -> None:
            for child in list(current.children):
                forget(child)
            self._by_owner.pop(id(current.owner), None)

        forget(node)
        if node.parent is not None:
            node.parent.children.remove(node)

    def clear(self) -> None:
        for child in list(self.root.children):
            self.detach(child.owner)

    def resolve(
        self,
        resolver: Callable[
            [FigureTreeNode, ResolvedFigureNode | None],
            tuple[NormalizedRect, NormalizedRect],
        ],
    ) -> ResolvedFigureTree:
        """Resolve every node once, parent-first, into an immutable snapshot."""
        snapshots: list[ResolvedFigureNode] = []

        def visit(
            node: FigureTreeNode,
            parent: ResolvedFigureNode | None,
        ) -> ResolvedFigureNode:
            viewport, clip = resolver(node, parent)
            node.viewport = normalized_rect(viewport, label=f"{node.kind} viewport")
            node.clip = normalized_rect(clip, label=f"{node.kind} clip")
            placeholder = ResolvedFigureNode(
                node_id=node.node_id,
                kind=node.kind,
                owner=node.owner,
                viewport=node.viewport,
                clip=node.clip,
                parent_id=None if parent is None else parent.node_id,
                child_ids=tuple(child.node_id for child in node.children),
                rendered=node.rendered,
                metadata=MappingProxyType(dict(node.metadata)),
            )
            snapshots.append(placeholder)
            for child in node.children:
                visit(child, placeholder)
            return placeholder

        root = visit(self.root, None)
        return ResolvedFigureTree(root=root, nodes=tuple(snapshots))


__all__ = [
    "FigureNodeKind",
    "FigureTree",
    "FigureTreeNode",
    "NormalizedRect",
    "ResolvedFigureNode",
    "ResolvedFigureTree",
    "intersect_rect",
    "normalized_rect",
]
