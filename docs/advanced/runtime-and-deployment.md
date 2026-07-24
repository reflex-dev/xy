---
title: Choosing a Runtime and Deployment Mode
description: XY applications run on Reflex. Choose a Reflex data tier for apps, and a notebook, HTML file, or static image for everything that is not an app.
---

# Choosing a Runtime and Deployment Mode

If you are building an application, the runtime is Reflex. XY does not ship a
second application runtime and does not embed into another web framework. The
choice you actually make is *inside* Reflex: which data tier a chart uses.

Everything else here — notebooks, standalone HTML, PNG, SVG — is not an
application runtime. Those are exploration and output.

## Applications run on Reflex

XY charts are first-class Reflex components in an all-Python app. Reflex owns
UI, state, events, and deployment; XY owns transport, rendering, and
interaction math.

- Compose XY charts with normal Reflex components in Python.
- Drive charts from per-session state with `@reflex_xy.figure`.
- Connect hover, click, selection, and view changes to Reflex event handlers,
  then stream updates with `reflex_xy.append`.
- Reuse the app's existing websocket and XY's binary data plane instead of
  deploying a separate chart service.

`reflex-xy` is experimental and is **not a published package**. Install it from
the matching XY Git tag, and do not put `pip install reflex-xy` in production
automation. See [Deployment Recipes](/docs/xy/guides/deployment-recipes/).

## Choose a data tier

The chart definition is identical in every tier. What changes is where its data
comes from, and therefore what the chart can still do after you deploy.

| Tier | Data comes from | Live Python | Events | `append()` | Exact row selection | `reflex export` |
| --- | --- | --- | --- | --- | --- | --- |
| `reflex_xy.chart(chart)` | fixed, compiled into an asset | no | browser-local | no | no | yes |
| `reflex_xy.inline(chart)` | fixed, kept in the XY registry | yes | yes | yes | yes | no |
| `@reflex_xy.figure` | per-session Reflex state | yes | yes | yes | yes | no |

Browser-local means hover, pan, zoom, and selection still work in the page;
they just cannot reach Python.

Start at the top. A fixed `xy.Chart` becomes a content-addressed asset that
needs no backend connection and survives `reflex export`. Move down only when
the chart must answer with data it did not ship with — a drill-down, a fresh
query, the exact rows behind a lasso.

Despite its name, `inline()` is the live, kernel-backed fixed-data tier; passing
a `Chart` directly is the static tier. Call `inline()` at module scope so every
backend worker registers the same content-addressed token.

There is also `reflex_xy.register()`, an imperative dev-tier escape hatch. Its
figure lives only in the registering process and cannot be rebuilt after a
worker restart or on another node, so do not deploy it.

## Moving down a tier is a wrapper change

The chart definition does not change; only its source does.

~~~python
# Fixed asset tier
def page():
    return rx.vstack(
        reflex_xy.chart(
            xy.scatter_chart(xy.scatter(x="orders", y="revenue", data=daily))
        )
    )


# Session-backed tier — same chart, now driven by state
class Dashboard(rx.State):
    channel: str = "web"

    @reflex_xy.figure
    def revenue(self) -> xy.Chart:
        rows = daily[daily.channel == self.channel]
        return xy.scatter_chart(xy.scatter(x="orders", y="revenue", data=rows))


def page():
    return rx.vstack(reflex_xy.chart(Dashboard.revenue))
~~~

See the [Reflex integration guide](/docs/xy/integrations/reflex/) for component
props, event payloads, and the API boundary.

## Outside an application

Not every chart belongs in an app. The same definition runs in a notebook and
exports to files.

~~~python
chart = xy.scatter_chart(xy.scatter(x="orders", y="revenue", data=daily))

chart.show()                 # notebook widget — live Python, dies with the kernel
chart.to_html("out.html")    # one portable interactive file, no server
chart.to_png("out.png")      # static raster
chart.to_svg("out.svg")      # static vector
~~~

| Output | Best for | Live Python |
| --- | --- | --- |
| Notebook widget | Exploration, callbacks, streaming, exact refinement | yes |
| Standalone HTML | A portable interactive file that works without a server | no |
| Static images | Reports, tests, thumbnails, batch output | no |

For formats beyond PNG and SVG — JPEG, WebP, PDF, and batch `write_images` —
and for the native-versus-Chromium engine choice, see
[Display and Export](/docs/xy/guides/display-and-export/).

## Know what each choice costs you

| Choice | The catch |
| --- | --- |
| Fixed Reflex chart | No Python round-trip: no drill-down, no exact selection resolution. |
| `register()` | Not rebuildable after a worker restart or on another node. Dev only. |
| Notebook widget | Dies with the kernel; not shareable as-is. |
| Standalone HTML | A snapshot — later `append()` calls never reach it. It needs inline script and style plus a `blob:` worker under its emitted CSP, and anyone who downloads it can read the embedded data. |
| Native PNG | Cannot apply author `custom_css`. Use renderable chart and mark styles, or `Engine.chromium`. |
| Chromium PNG | Requires a browser on the machine that renders. |
| SVG | Density and heatmap layers embed raster data, so output is not fully vector. Requesting SVG from the browser engine raises `ValueError`. |
| Any streaming tier | `append()` covers scatter and line traces only, and facets support neither append nor pick. |

Full list: [Limitations and Alpha Status](/docs/xy/api-reference/limitations-and-alpha-status/).

## Where to go next

- Applications → [Reflex integration](/docs/xy/integrations/reflex/)
- Exploration → [Notebooks](/docs/xy/integrations/notebooks/)
- Files and static output → [Display and Export](/docs/xy/guides/display-and-export/)
- Hosting, CSP, offline → [Serving, CSP, and offline use](/docs/xy/guides/serving-csp-and-offline-use/)
