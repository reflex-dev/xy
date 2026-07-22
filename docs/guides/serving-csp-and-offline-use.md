---
title: Serving, CSP, and Offline Use
description: Serve bundled XY assets under CSP and operate without a CDN or network access.
---

# Serving, CSP, and Offline Use

Published XY wheels contain the Python package, native core, and versioned
JavaScript/WebGL client. Notebook display, standalone export, and the Reflex
adapter do not load XY from a CDN.

## Offline Environments

Once the required wheels are installed, normal chart construction, notebook
display, native PNG, SVG, and standalone HTML export need no network access.
Prepare compatible platform wheels in advance for an air-gapped installation;
a source build still requires the Rust toolchain.

Chromium PNG export needs a supported browser installed locally, but does not
fetch one. The default native PNG engine has no browser requirement.

## Standalone HTML Policy

`chart.to_html()` creates one portable file containing its data, styles, and
render client. The document emits a defensive `Content-Security-Policy` that
blocks external connections, objects, forms, and base-URL changes. Density
refinement can start a worker from the bundled source, so the policy allows
`worker-src blob:`; it does not allow an external worker script.

Portable single-file output necessarily uses inline script and style blocks.
Its policy therefore includes `script-src 'unsafe-inline'` and
`style-src 'unsafe-inline'`. `custom_css=` is added to that inline author
stylesheet.

~~~md alert warning
### Strict Nonce or Hash Policies

Do not embed standalone HTML unchanged in a host that forbids inline scripts
or styles. A nonce/hash-only deployment needs an application wrapper that
serves the bundled JavaScript separately and injects chart data and styles
through the host's nonce- or hash-aware path.
~~~

## Reflex Deployment

A fixed `xy.Chart` passed directly as `reflex_xy.chart(chart)` compiles to local
static client and binary payload assets and works with `reflex export`. This is
the static tier.

For fixed data that still needs kernel round-trips, create
`token = reflex_xy.inline(chart)` at module scope and mount it with
`reflex_xy.chart(token)`. That `inline()` token is live, as is an
`@reflex_xy.figure` var, so both require the Reflex backend and its existing
Socket.IO connection. The adapter does not create a second service or websocket
endpoint.

Account for the application's own script, style, worker, asset, and websocket
directives when writing a host CSP. XY's lack of a CDN dependency does not make
a live state-backed application backend-free.

## Self-Contained Does Not Mean Live

A standalone HTML file remains interactive in its browser, but it is a
snapshot. It cannot call Python event handlers or receive future
`chart.append(...)` calls. Use a notebook widget or framework adapter when the
browser must communicate with a Python process.
