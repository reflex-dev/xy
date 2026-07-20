---
title: Dashboards and Linked Views
description: Coordinate chart ranges, application filters, and many-chart browser resources.
---

# Dashboards and Linked Views

Charts in the same browser document can synchronize view ranges without
round-tripping every pan or zoom through Python. Give them the same
`link_group` and choose the synchronized axes with `link_axes`.

~~~python
import xy

overview = xy.scatter_chart(
    xy.scatter([0, 1, 2, 3], [2, 5, 3, 7]),
    xy.interaction_config(link_group="orders", link_axes=("x",)),
    title="Overview",
)

detail = xy.line_chart(
    xy.line([0, 1, 2, 3], [20, 18, 24, 29]),
    xy.interaction_config(link_group="orders", link_axes=("x",)),
    title="Detail",
)
~~~

Use unique group names for independent dashboard regions. Link only `x` when
panels share time but use different y units. Facet domains remain independent
at runtime by default; opt into synchronized navigation with
`facet_chart(..., link="x")`, `link="y"`, or `link="both"`. A linked axis also
shares its initial domain, even when its matching `share_x`/`share_y` flag is
false. Set `link_select=True` to echo the same data-space brush predicate and
selection highlighting across the facet panels.

## Application-Driven Coordination

Range linking is browser-local. For a stateful dashboard, use `on_select` or
`on_view_change` to send a small semantic payload to the host application,
update filters there, and build the affected state-backed charts. XY does not
silently apply an arbitrary cross-filter to unrelated datasets.

Standalone HTML can link ranges and retain local interactions, but it cannot
invoke Python callbacks. Notebook widgets and the Reflex live tier can.

## Many Charts and the Context Budget

Browsers cap the number of live WebGL contexts on a page. XY's client keeps a
default budget of 12: least-recently-visible off-screen charts can be
snapshotted and release their contexts, then reacquire one when they return to
view or receive pointer interaction.

This makes dashboards with more than 12 total charts practical; it is not a
promise that an unlimited number can remain simultaneously visible with live
GPU contexts. A layout that keeps more than the budget visible at once can
still trigger browser-side context eviction.

For dense dashboards:

- Virtualize or paginate panels that are not visible.
- Prefer facets when panels share one data and layout contract.
- Give each chart an explicit height so responsive layout does not collapse.
- Inspect `memory_report()` and avoid retaining unbounded streaming history.
- Test scroll recovery and interaction on the browsers used in production.
