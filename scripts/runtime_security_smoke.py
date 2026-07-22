#!/usr/bin/env python3
"""Real-browser standalone DOM-XSS, CSP, and network-isolation gate.

This is deliberately separate from Chromium's *process sandbox* policy.  It
loads a production ``Chart.to_html()`` document and observes the page-content
boundary in a browser:

* hostile strings traverse every public text surface and remain literal text;
* no user string creates executable DOM, runs script, or opens a dialog;
* hostile author CSS is applied, while its external URL is stopped by the
  shipped standalone CSP before it reaches a loopback request sentinel; and
* the browser reports the expected CSP violation and no network API attempts.

The JSON evidence is retained by CI on success and failure.  Browser launch
uses its sandbox by default; ``--no-sandbox`` is an explicit fixture-level
opt-out for constrained CI runners, never an automatic retry.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402

CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)

REPORT_ID = "xy-runtime-security-report"


def find_chromium(explicit: str | None = None) -> str:
    """Resolve an explicit browser without silently falling back."""
    if explicit:
        resolved = explicit if Path(explicit).is_file() else shutil.which(explicit)
        if resolved:
            return str(resolved)
        raise RuntimeError(f"configured chromium not found: {explicit}")
    for candidate in CHROMIUM_CANDIDATES:
        resolved = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if resolved:
            return str(resolved)
    raise RuntimeError("no chromium found; pass its path as the first argument")


class _SentinelHandler(BaseHTTPRequestHandler):
    server: "_SentinelServer"

    def _record(self) -> None:
        self.server.requests.append(
            {"method": self.command, "path": self.path, "client": self.client_address[0]}
        )
        self.send_response(204)
        self.end_headers()

    do_GET = _record
    do_HEAD = _record

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _SentinelServer(ThreadingHTTPServer):
    requests: list[dict[str, str]]


@contextmanager
def network_sentinel() -> Iterator[tuple[str, list[dict[str, str]]]]:
    """Yield a loopback URL and a list populated only by real HTTP requests."""
    server = _SentinelServer(("127.0.0.1", 0), _SentinelHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, name="xy-security-sentinel")
    thread.daemon = True
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/xy-runtime-security-probe", server.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _attack(label: str, sentinel_url: str) -> str:
    """A recognizable payload that would execute, navigate, and fetch if parsed."""
    return (
        f"XY_{label}::</script><script>globalThis.__xyRuntimeExecuted=true;"
        f"alert('{label}')</script><img src=\"{sentinel_url}?from={label}\" "
        'onerror="globalThis.__xyRuntimeExecuted=true">'
        '<svg onload="globalThis.__xyRuntimeExecuted=true"></svg>'
    )


def _surface_values(sentinel_url: str) -> dict[str, str]:
    names = (
        "TITLE",
        "X_AXIS",
        "Y_AXIS",
        "X_TICK",
        "Y_TICK",
        "TRACE_LINE",
        "TRACE_COLOR",
        "CATEGORY",
        "ANNOTATION",
        "LEGEND_TITLE",
        "COLORBAR_TITLE",
        "TOOLTIP_TITLE",
        "FIELD_X",
        "FIELD_Y",
        "FIELD_CATEGORY",
        "FIELD_COLOR",
    )
    return {name.casefold(): _attack(name, sentinel_url) for name in names}


_MONITOR = r"""
<script>
(() => {
  const state = window.__xyRuntimeSecurity = {
    apiAttempts: [], cspViolations: [], dialogs: [], errors: [], transientUnsafeNodes: []
  };
  globalThis.__xyRuntimeExecuted = false;
  const describe = (node) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return "";
    return node.tagName.toLowerCase() +
      (node.id ? `#${node.id}` : "") +
      (node.getAttribute("data-xy-slot") ? `[slot=${node.getAttribute("data-xy-slot")}]` : "");
  };
  const unsafe = (node) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE || !node.closest("#chart")) return;
    const nodes = [node, ...node.querySelectorAll("*")];
    for (const candidate of nodes) {
      const tag = candidate.tagName.toLowerCase();
      const eventAttribute = candidate.getAttributeNames().find((name) => name.startsWith("on"));
      const fixedSvg = tag === "svg" && candidate.closest(
        '[data-xy-slot="modebar"], [data-xy-slot="legend_swatch"], ' +
        '[data-xy-selection-lasso-overlay]');
      if (["script", "img", "iframe", "object", "embed", "form", "base", "link"].includes(tag)
          || (tag === "svg" && !fixedSvg) || eventAttribute) {
        state.transientUnsafeNodes.push(describe(candidate) + (eventAttribute ? `@${eventAttribute}` : ""));
      }
    }
  };
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) unsafe(node);
      if (record.type === "attributes") unsafe(record.target);
    }
  }).observe(document, {subtree: true, childList: true, attributes: true});
  document.addEventListener("securitypolicyviolation", (event) => {
    state.cspViolations.push({
      blockedURI: event.blockedURI,
      effectiveDirective: event.effectiveDirective,
      violatedDirective: event.violatedDirective,
    });
  });
  window.addEventListener("error", (event) => state.errors.push(String(event.message || event.error)));
  window.addEventListener("unhandledrejection", (event) => state.errors.push(String(event.reason)));
  for (const name of ["alert", "confirm", "prompt"]) {
    window[name] = (...args) => { state.dialogs.push({name, args: args.map(String)}); return false; };
  }
  window.open = (...args) => { state.dialogs.push({name: "open", args: args.map(String)}); return null; };
  const wrap = (owner, name) => {
    const original = owner && owner[name];
    if (typeof original !== "function") return;
    owner[name] = function (...args) {
      state.apiAttempts.push({name, target: String(args[0])});
      return Reflect.apply(original, this, args);
    };
  };
  wrap(window, "fetch");
  for (const name of ["WebSocket", "EventSource", "Worker", "SharedWorker"]) wrap(window, name);
  const xhrOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    state.apiAttempts.push({name: "XMLHttpRequest", target: String(url)});
    return Reflect.apply(xhrOpen, this, [method, url, ...rest]);
  };
})();
</script>
"""


_PROBE = rf"""
<script>
setTimeout(() => {{
  const config = JSON.parse(atob(window.__xyRuntimeSecurityConfig));
  const state = window.__xyRuntimeSecurity;
  const failures = [];
  const fail = (message) => failures.push(message);
  try {{
    const view = window.__xyRuntimeSecurityView;
    if (!view) throw new Error("standalone render did not return a ChartView");
    view._drawNow();
    view.canvas.dispatchEvent(new KeyboardEvent("keydown", {{
      key: "Home", bubbles: true, cancelable: true
    }}));
    const root = document.querySelector('#chart [data-xy-slot="root"]');
    if (!root) throw new Error("chart root did not mount");

    const surfaces = config.expectations.map((expected) => {{
      const nodes = [...root.querySelectorAll(expected.selector)];
      const matched = nodes.some((node) => node.textContent.includes(expected.text));
      if (!matched) fail(`${{expected.name}} did not render as literal text`);
      return {{...expected, matched, observed: nodes.map((node) => node.textContent)}};
    }});

    const unsafeNodes = [];
    for (const node of root.querySelectorAll("*")) {{
      const tag = node.tagName.toLowerCase();
      const eventAttributes = node.getAttributeNames().filter((name) => name.startsWith("on"));
      const fixedSvg = tag === "svg" && node.closest(
        '[data-xy-slot="modebar"], [data-xy-slot="legend_swatch"], ' +
        '[data-xy-selection-lasso-overlay]');
      if (["script", "img", "iframe", "object", "embed", "form", "base", "link"].includes(tag)
          || (tag === "svg" && !fixedSvg) || eventAttributes.length) {{
        unsafeNodes.push({{tag, eventAttributes, fixedSvg: Boolean(fixedSvg)}});
      }}
    }}
    if (unsafeNodes.length) fail(`unsafe chart DOM nodes: ${{JSON.stringify(unsafeNodes)}}`);
    if (state.transientUnsafeNodes.length) {{
      fail(`transient unsafe chart DOM nodes: ${{state.transientUnsafeNodes.join(", ")}}`);
    }}
    if (globalThis.__xyRuntimeExecuted) fail("hostile user script or event handler executed");
    if (state.dialogs.length) fail(`dialogs or popups opened: ${{JSON.stringify(state.dialogs)}}`);
    if (state.apiAttempts.length) fail(`network APIs called: ${{JSON.stringify(state.apiAttempts)}}`);
    if (state.errors.length) fail(`page errors: ${{JSON.stringify(state.errors)}}`);

    const csp = document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content || "";
    for (const directive of ["default-src 'none'", "connect-src 'none'", "img-src data:",
                             "object-src 'none'", "base-uri 'none'", "form-action 'none'"]) {{
      if (!csp.includes(directive)) fail(`standalone CSP missing ${{directive}}`);
    }}
    const css = getComputedStyle(root);
    const cssApplied = css.getPropertyValue("--xy-runtime-security-probe").trim() === "applied";
    const hostileBackground = css.backgroundImage.includes(config.sentinelUrl);
    if (!cssApplied || !hostileBackground) fail("hostile custom CSS was not exercised by the browser");
    const cspBlockedCss = state.cspViolations.some((event) =>
      event.effectiveDirective === "img-src" && event.blockedURI.startsWith(config.sentinelUrl));
    if (!cspBlockedCss) fail(`CSP did not report the hostile CSS URL: ${{JSON.stringify(state.cspViolations)}}`);
    // Chromium exposes a PerformanceResourceTiming entry for a CSP-blocked
    // CSS URL even though no HTTP request leaves the process.  Retain that
    // browser-side evidence, reject any unrelated external URL here, and let
    // the Python loopback sentinel make the definitive wire-level assertion.
    const externalResources = performance.getEntriesByType("resource")
      .filter((entry) => /^(?:https?|wss?):/i.test(entry.name))
      .map((entry) => ({{
        name: entry.name,
        initiatorType: entry.initiatorType,
        transferSize: entry.transferSize,
        encodedBodySize: entry.encodedBodySize,
      }}));
    const unexpectedExternalResources = externalResources.filter(
      (entry) => !entry.name.startsWith(config.sentinelUrl));
    if (unexpectedExternalResources.length) {{
      fail(`unexpected external resources: ${{JSON.stringify(unexpectedExternalResources)}}`);
    }}

    const report = {{
      failures, surfaces, unsafeNodes,
      transientUnsafeNodes: state.transientUnsafeNodes,
      executed: globalThis.__xyRuntimeExecuted,
      dialogs: state.dialogs,
      apiAttempts: state.apiAttempts,
      pageErrors: state.errors,
      csp,
      cspViolations: state.cspViolations,
      cssApplied,
      hostileBackground,
      externalResources,
      unexpectedExternalResources,
    }};
    const output = document.createElement("pre");
    output.id = "{REPORT_ID}";
    output.hidden = true;
    output.textContent = JSON.stringify(report);
    document.body.appendChild(output);
    document.title = failures.length ? "XY_RUNTIME_SECURITY_FAIL" : "XY_RUNTIME_SECURITY_OK";
  }} catch (error) {{
    const output = document.createElement("pre");
    output.id = "{REPORT_ID}";
    output.hidden = true;
    output.textContent = JSON.stringify({{failures: [String(error && error.stack || error)]}});
    document.body.appendChild(output);
    document.title = "XY_RUNTIME_SECURITY_FAIL";
  }}
}}, 150);
</script>
"""


def build_runtime_fixture(sentinel_url: str) -> tuple[str, list[dict[str, str]]]:
    """Build the instrumented production export and its DOM expectations."""
    value = _surface_values(sentinel_url)
    data = {
        value["field_x"]: [0.2, 0.8],
        value["field_y"]: [0.3, 0.7],
        value["field_category"]: [value["category"], "safe category"],
        value["field_color"]: [0.1, 0.9],
    }
    chart = xy.chart(
        xy.scatter(
            x=value["field_x"],
            y=value["field_y"],
            color=value["field_category"],
            data=data,
            name="categorical points",
            size=16,
        ),
        xy.line(x=[0.15, 0.85], y=[0.25, 0.75], name=value["trace_line"]),
        xy.scatter(
            x=value["field_x"],
            y=value["field_y"],
            color=value["field_color"],
            data=data,
            name=value["trace_color"],
            size=10,
        ),
        xy.text(0.5, 0.5, value["annotation"]),
        xy.x_axis(
            label=value["x_axis"],
            tick_values=[0.2, 0.8],
            tick_labels=[value["x_tick"], "safe x tick"],
        ),
        xy.y_axis(
            label=value["y_axis"],
            tick_values=[0.3, 0.7],
            tick_labels=[value["y_tick"], "safe y tick"],
        ),
        xy.legend(title=value["legend_title"]),
        xy.tooltip(
            fields=[value["field_x"], value["field_y"], value["field_category"]],
            title=value["tooltip_title"],
        ),
        xy.colorbar(title=value["colorbar_title"]),
        title=value["title"],
        width=960,
        height=560,
    )
    custom_css = (
        '.xy[data-xy-slot="root"] {'
        "--xy-runtime-security-probe: applied;"
        f'background-image: url("{sentinel_url}") !important;'
        "}"
    )
    document = chart.to_html(custom_css=custom_css)
    expectations = [
        {"name": "title", "selector": '[data-xy-slot="title"]', "text": value["title"]},
        {
            "name": "x-axis title",
            "selector": '[data-xy-slot="axis_title"]',
            "text": value["x_axis"],
        },
        {
            "name": "y-axis title",
            "selector": '[data-xy-slot="axis_title"]',
            "text": value["y_axis"],
        },
        {
            "name": "x tick label",
            "selector": '[data-xy-slot="tick_label"]',
            "text": value["x_tick"],
        },
        {
            "name": "y tick label",
            "selector": '[data-xy-slot="tick_label"]',
            "text": value["y_tick"],
        },
        {
            "name": "line trace name",
            "selector": '[data-xy-slot="legend"]',
            "text": value["trace_line"],
        },
        {
            "name": "continuous trace name",
            "selector": '[data-xy-slot="legend"]',
            "text": value["trace_color"],
        },
        {
            "name": "category",
            "selector": '[data-xy-slot="legend"]',
            "text": value["category"],
        },
        {
            "name": "annotation",
            "selector": '[data-xy-slot="annotation_label"]',
            "text": value["annotation"],
        },
        {
            "name": "legend title",
            "selector": '[data-xy-slot="legend"]',
            "text": value["legend_title"],
        },
        {
            "name": "colorbar title",
            "selector": '[data-xy-slot="colorbar_title"]',
            "text": value["colorbar_title"],
        },
        {
            "name": "tooltip title",
            "selector": '[data-xy-slot="tooltip"]',
            "text": value["tooltip_title"],
        },
        {
            "name": "tooltip x field",
            "selector": '[data-xy-slot="tooltip"]',
            "text": value["field_x"],
        },
        {
            "name": "tooltip y field",
            "selector": '[data-xy-slot="tooltip"]',
            "text": value["field_y"],
        },
        {
            "name": "tooltip category field",
            "selector": '[data-xy-slot="tooltip"]',
            "text": value["field_category"],
        },
        {
            "name": "tooltip category value",
            "selector": '[data-xy-slot="tooltip"]',
            "text": value["category"],
        },
    ]
    production_call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    if document.count(production_call) != 1:
        raise RuntimeError("production standalone render call changed; update security fixture")
    document = document.replace(
        production_call,
        "window.__xyRuntimeSecurityView = " + production_call,
        1,
    )
    if document.count("</title>") != 1 or document.count("</body>") != 1:
        raise RuntimeError("production standalone document structure changed")
    config = base64.b64encode(
        json.dumps({"sentinelUrl": sentinel_url, "expectations": expectations}).encode()
    ).decode("ascii")
    document = document.replace("</title>", "</title>" + _MONITOR, 1)
    document = document.replace(
        "</body>",
        f'<script>window.__xyRuntimeSecurityConfig="{config}";</script>{_PROBE}</body>',
        1,
    )
    return document, expectations


class _ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "pre" and dict(attrs).get("id") == REPORT_ID:
            self._inside = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "pre" and self._inside:
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.parts.append(data)


def _parse_browser_output(output: str) -> tuple[str, dict[str, Any] | None]:
    parser = _ReportParser()
    parser.feed(output)
    title_start = output.casefold().find("<title>")
    title_end = output.casefold().find("</title>", title_start + 7)
    title = "(no title)"
    if title_start >= 0 and title_end >= 0:
        title = html.unescape(output[title_start + 7 : title_end]).strip()
    report_text = "".join(parser.parts).strip()
    if not report_text:
        return title, None
    try:
        report = json.loads(report_text)
    except json.JSONDecodeError as exc:
        return title, {"failures": [f"invalid browser report JSON: {exc}"]}
    return title, report


def _run_browser(executable: str, page: Path, *, no_sandbox: bool) -> SimpleNamespace:
    command = [
        executable,
        "--headless=new",
        "--disable-dev-shm-usage",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--virtual-time-budget=10000",
        "--dump-dom",
        page.as_uri(),
    ]
    if no_sandbox:
        command.insert(2, "--no-sandbox")
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chromium", nargs="?", default=None)
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="explicitly disable Chromium's process sandbox for this CI fixture",
    )
    parser.add_argument("--evidence", type=Path, default=None)
    args = parser.parse_args(argv)

    evidence: dict[str, Any] = {
        "status": "failed",
        "launch_sandbox": "disabled-explicitly" if args.no_sandbox else "enabled",
        "timed_out": False,
        "chromium_returncode": None,
        "network_requests": [],
    }
    try:
        executable = find_chromium(args.chromium)
        evidence["chromium"] = executable
        with network_sentinel() as (sentinel_url, requests):
            document, expectations = build_runtime_fixture(sentinel_url)
            evidence["expected_surfaces"] = [item["name"] for item in expectations]
            with tempfile.TemporaryDirectory(prefix="xy-runtime-security-") as temp_dir:
                page = Path(temp_dir) / "runtime-security.html"
                page.write_text(document, encoding="utf-8")
                try:
                    completed = _run_browser(executable, page, no_sandbox=args.no_sandbox)
                except subprocess.TimeoutExpired as exc:
                    stderr = exc.stderr or ""
                    if isinstance(stderr, bytes):
                        stderr = stderr.decode(errors="replace")
                    evidence.update(
                        title="XY_RUNTIME_SECURITY_FAIL browser timeout after 120s",
                        timed_out=True,
                        stderr_tail=stderr[-4000:],
                    )
                else:
                    title, report = _parse_browser_output(completed.stdout)
                    evidence.update(
                        title=title,
                        chromium_returncode=completed.returncode,
                        stderr_tail=completed.stderr[-4000:],
                        browser_report=report,
                    )
            evidence["network_requests"] = list(requests)
    except (OSError, RuntimeError, ValueError) as exc:
        evidence["title"] = f"XY_RUNTIME_SECURITY_FAIL {exc}"

    report = evidence.get("browser_report")
    passed = (
        evidence.get("chromium_returncode") == 0
        and evidence.get("title") == "XY_RUNTIME_SECURITY_OK"
        and isinstance(report, dict)
        and report.get("failures") == []
        and evidence.get("network_requests") == []
    )
    evidence["status"] = "ok" if passed else "failed"
    if evidence.get("network_requests"):
        evidence.setdefault("failures", []).append(
            "standalone page reached the loopback network sentinel"
        )
    if args.evidence is not None:
        _write_evidence(args.evidence, evidence)
    if passed:
        print(
            "runtime security smoke OK: "
            f"{len(evidence['expected_surfaces'])} hostile text surfaces, "
            "CSP-blocked CSS, zero dialogs/requests"
        )
        return 0
    print(f"runtime security smoke FAILED: {evidence.get('title', '(no title)')}")
    if isinstance(report, dict):
        for failure in report.get("failures", []):
            print(f"- {failure}")
    for failure in evidence.get("failures", []):
        print(f"- {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
