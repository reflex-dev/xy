---
title: Sankey Diagram in Python
description: Create interactive Sankey diagrams in Python with xy. Show weighted flows between stages with automatic layout, colored nodes, and gradient ribbons.
components:
  - xy.sankey_chart
---

# Sankey Diagrams in Python

A **Sankey diagram** shows how a quantity flows through a sequence of stages.
Node height represents total flow, and each connecting ribbon is proportional
to its value. Use one for budgets, energy transfer, conversion funnels, supply
chains, or any directed flow where the size of each path matters.

With `xy`, pass `(source, target, value)` triples to `sankey_chart`. XY assigns
layers, minimizes crossings, sizes the nodes, stacks the ribbon endpoints, and
uses each link's source and target colors to paint its gradient.

Jump to [the basic chart](#create-a-sankey-diagram),
[a dense energy network](#trace-a-dense-energy-network),
[sink alignment](#compare-sink-alignment), or
[custom ribbon styling](#style-the-ribbon-layer).

## Create a Sankey Diagram

This example follows an investment inflow through allocations and outcomes:

~~~python demo exec
import reflex_xy
import xy

investment_flows = [
    ("Inflow", "Equities", 78_000),
    ("Inflow", "Bonds", 46_000),
    ("Inflow", "Cash", 24_000),
    ("Equities", "Growth", 61_000),
    ("Equities", "Income", 17_000),
    ("Bonds", "Income", 28_000),
    ("Bonds", "Reserve", 18_000),
    ("Cash", "Reserve", 24_000),
]

investment_sankey = xy.sankey_chart(
    investment_flows,
    colors=[
        "#6e56cf",
        "#3b82f6",
        "#0ea5e9",
        "#14b8a6",
        "#8b5cf6",
        "#f59e0b",
        "#64748b",
    ],
    link_opacity=0.48,
    node_width=0.025,
    node_padding=0.035,
    title="Investment allocation",
)


def sankey_chart_demo():
    return reflex_xy.chart(investment_sankey, height="440px")
~~~

Node names default to their first-appearance order in `links`. When you need
stable ordering independent of the input rows, pass every name through
`nodes=`:

~~~python
chart = xy.sankey_chart(
    links,
    nodes=["Inflow", "Equities", "Bonds", "Cash", "Growth", "Income", "Reserve"],
)
~~~

The `colors` sequence follows that same node order and must contain exactly one
CSS color per node.

## Trace a Dense Energy Network

Sankey diagrams are most useful when several branches split and rejoin. This
energy balance uses four stages, a compact `node_padding`, and extra
crossing-minimization `iterations`. Every ribbon blends from its source node
color to its target node color:

~~~python demo exec
import reflex_xy
import xy

energy_flows = [
    ("Grid supply", "Homes", 48),
    ("Grid supply", "Industry", 36),
    ("Grid supply", "Transport", 16),
    ("Homes", "Heating", 24),
    ("Homes", "Appliances", 16),
    ("Homes", "Lighting", 8),
    ("Industry", "Processes", 25),
    ("Industry", "Motors", 11),
    ("Transport", "EV charging", 16),
    ("Heating", "Useful energy", 18),
    ("Heating", "Losses", 6),
    ("Appliances", "Useful energy", 13),
    ("Appliances", "Losses", 3),
    ("Lighting", "Useful energy", 7),
    ("Lighting", "Losses", 1),
    ("Processes", "Useful energy", 20),
    ("Processes", "Losses", 5),
    ("Motors", "Useful energy", 9),
    ("Motors", "Losses", 2),
    ("EV charging", "Useful energy", 13),
    ("EV charging", "Losses", 3),
]

energy_nodes = [
    "Grid supply",
    "Homes",
    "Industry",
    "Transport",
    "Heating",
    "Appliances",
    "Lighting",
    "Processes",
    "Motors",
    "EV charging",
    "Useful energy",
    "Losses",
]

energy_sankey = xy.sankey_chart(
    energy_flows,
    nodes=energy_nodes,
    colors=[
        "#6366f1",
        "#8b5cf6",
        "#3b82f6",
        "#06b6d4",
        "#f97316",
        "#eab308",
        "#facc15",
        "#ec4899",
        "#14b8a6",
        "#0ea5e9",
        "#22c55e",
        "#ef4444",
    ],
    node_width=0.018,
    node_padding=0.012,
    iterations=14,
    link_opacity=0.58,
    label_size=11,
    title="Electricity from supply to outcome",
)


def energy_sankey_demo():
    return reflex_xy.chart(energy_sankey, height="500px")
~~~

Use an explicit `nodes` list when color meaning must remain stable even if the
input rows are reordered. More `iterations` can improve a busy layout, though
the crossing-minimization algorithm is heuristic rather than guaranteed to
find the mathematical optimum.

## Compare Sink Alignment

A sink is a node with no outgoing link. With `align="left"`, an early sink
stays in the first layer where the graph places it. The default
`align="justify"` moves every sink to the final layer, producing a flush right
edge. Compare the position of **Direct purchase**:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

conversion_flows = [
    ("Visitors", "Browse", 820),
    ("Visitors", "Direct purchase", 180),
    ("Browse", "Cart", 420),
    ("Browse", "Leave", 400),
    ("Cart", "Purchased", 260),
    ("Cart", "Abandoned", 160),
]

conversion_colors = [
    "#6366f1",
    "#8b5cf6",
    "#22c55e",
    "#f59e0b",
    "#16a34a",
    "#ef4444",
    "#fb7185",
]

left_aligned_sankey = xy.sankey_chart(
    conversion_flows,
    colors=conversion_colors,
    align="left",
    node_padding=0.035,
    title="Natural graph layers",
)

justified_sankey = xy.sankey_chart(
    conversion_flows,
    colors=conversion_colors,
    align="justify",
    node_padding=0.035,
    title="Sinks justified right",
)


def sankey_alignment_demo():
    return rx.grid(
        reflex_xy.chart(left_aligned_sankey, height="320px"),
        reflex_xy.chart(justified_sankey, height="320px"),
        columns="2",
        gap="1rem",
        width="100%",
    )
~~~

For a single-column mobile layout, place the two chart components in an
`rx.vstack` or make the grid's `columns` prop responsive in your Reflex app.

## Style the Ribbon Layer

Use the `xy.sankey` mark directly when you want mark-level styling. The `style`
mapping below adds a subtle purple outline, while high-opacity links preserve
the intended lavender-to-violet gradient without competing with the solid node
bars. Composing the mark yourself also means supplying the hidden unit-box axes
that `sankey_chart` normally adds for you:

~~~python demo exec
import reflex_xy
import xy

material_flows = [
    ("Virgin material", "Manufacturing", 72),
    ("Recovered material", "Manufacturing", 22),
    ("Recovered material", "Residual", 6),
    ("Manufacturing", "Product", 82),
    ("Manufacturing", "Process waste", 12),
]

material_sankey = xy.chart(
    xy.sankey(
        material_flows,
        colors=[
            "#c4b5fd",  # Virgin material — left
            "#7c3aed",  # Manufacturing — highlighted middle hub
            "#a78bfa",  # Recovered material — left
            "#3b0764",  # Residual — right
            "#4c1d95",  # Product — right
            "#5b21b6",  # Process waste — right
        ],
        node_width=0.05,
        node_padding=0.05,
        link_opacity=0.82,
        label_size=13,
        style={
            "stroke": "#6d28d9",
            "stroke-width": 0.7,
            "stroke-opacity": 0.35,
        },
    ),
    xy.x_axis(domain=(-0.09, 1.09), show=False),
    xy.y_axis(domain=(-0.05, 1.05), reverse=True, show=False),
    title="Material recovery",
    styles={
        "annotation_label": {
            "color": "#f8fafc",
            "font-weight": 600,
            "text-shadow": "0 1px 3px #0f172a, 0 0 4px #0f172a",
        },
    },
)


def styled_sankey_demo():
    return reflex_xy.chart(material_sankey, height="400px")
~~~

The mark's `style` mapping applies to links, while `colors` controls nodes and
the two ends of each link gradient. Here, pale lavender sources transition
through a saturated purple process hub to deep-violet outcomes, reinforcing
the left-to-right flow. Wider, fully opaque node bars sit above slightly dimmed
ribbons, so every stage remains distinct instead of blending into its attached
flows. Sankey names use the chart's `annotation_label` style slot; a light
color and dark shadow keep labels readable across changing ribbon colors. Set
`labels=False` for a compact, label-free diagram, or increase `label_size` when
the chart has room for larger text.

## Layout and Flow Rules

Sankey links form a directed acyclic graph: every path moves from an earlier
stage to a later stage. XY rejects cycles and names the nodes involved instead
of drawing a misleading backward flow.

Each `(source, target)` pair must appear once. Aggregate repeated pairs before
passing them to the chart, and use finite, non-negative values. Node height is
the larger of total inflow and total outflow, so a node remains large enough
for every ribbon attached to it.

`align="justify"` places terminal nodes on the final layer. The other supported
alignments are `"left"`, `"right"`, and `"center"`: left keeps each node in the
earliest layer its links allow, right hangs each node by its distance to a
sink, and center moves nodes without incoming links next to their first
target. Alternating barycenter sweeps reduce crossings; increase `iterations`
for a denser graph when the extra layout work improves the result.

## Sankey Options

| Option | Purpose |
| --- | --- |
| `links` | `(source, target, value)` triples describing each flow. |
| `nodes` | Explicit node order; defaults to first appearance in `links`. |
| `colors` | One CSS color per node, following node order. |
| `node_width` | Node width as a fraction of the diagram, between 0 and 1. |
| `node_padding` | Vertical gap between nodes in a layer, between 0 and 1. |
| `align` | Node alignment: `"justify"`, `"left"`, `"right"`, or `"center"`. |
| `iterations` | Number of crossing-minimization sweeps. |
| `link_opacity` | Ribbon opacity in the interval `(0, 1]`. |
| `labels` | Whether node names are drawn beside their nodes. |
| `label_size` | Node-label font size in pixels. |

Chart options such as `width`, `height`, `title`, and theme settings are passed
to `sankey_chart` alongside the Sankey options.

## Interaction and Export

The browser resolves ribbon hover by testing the pointer against the same
curved band geometry used for rendering. Link tooltips show
**source → target** with the flow value; node tooltips show the node name and
its total flow. Sankey diagrams also export through the standard chart methods:

~~~python
investment_sankey.to_html("allocation.html")
investment_sankey.to_png("allocation.png")
investment_sankey.to_svg("allocation.svg")
investment_sankey.to_pdf("allocation.pdf")
~~~

GPU picking, ribbon hover highlighting, automatic legend swatches for
two-color ribbons, cycle breaking, and Sankey-specific level of detail are not
implemented yet.

## Related Charts

- [Bar and column charts](/docs/xy/charts/bar-chart/) compare independent
  category totals without encoding a flow between them.
- [Segments](/docs/xy/charts/segments/) draw independent point-to-point
  connections when band width does not carry a value.
- [Annotations](/docs/xy/components/annotations/) add explanatory labels,
  callouts, and thresholds around a flow diagram.

## FAQ

### How do I create a Sankey diagram in Python?

Pass `(source, target, value)` triples to `xy.sankey_chart(...)`. XY computes
the node layers, sizes, ordering, and ribbon endpoints automatically.

### Can a Sankey diagram contain cycles?

No. A Sankey flows from earlier stages to later stages. XY raises an error that
names the nodes in a cycle so you can break or aggregate that loop explicitly.

### How do I control Sankey colors?

Pass one CSS color per node through `colors=`. The source and target colors are
interpolated across each ribbon to make its direction readable.

### How do I move terminal nodes to the right edge?

Use the default `align="justify"`. Choose `"left"`, `"right"`, or `"center"`
when a different layer alignment better matches the story in your data.
