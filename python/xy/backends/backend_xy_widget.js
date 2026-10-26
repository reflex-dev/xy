const SPECIAL_KEYS = {
  Alt: "alt",
  AltGraph: "alt",
  CapsLock: "caps_lock",
  Control: "control",
  Meta: "super",
  NumLock: "num_lock",
  ScrollLock: "scroll_lock",
  Shift: "shift",
  Enter: "enter",
  Tab: "tab",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  End: "end",
  Home: "home",
  PageDown: "pagedown",
  PageUp: "pageup",
  Backspace: "backspace",
  Delete: "delete",
  Insert: "insert",
  Escape: "escape",
  Pause: "pause",
  F1: "f1",
  F2: "f2",
  F3: "f3",
  F4: "f4",
  F5: "f5",
  F6: "f6",
  F7: "f7",
  F8: "f8",
  F9: "f9",
  F10: "f10",
  F11: "f11",
  F12: "f12",
};

const CSS_CURSORS = {
  pointer: "default",
  hand: "pointer",
  select_region: "crosshair",
  move: "move",
  wait: "wait",
  resize_horizontal: "ew-resize",
  resize_vertical: "ns-resize",
};

const TOOLBAR_ACTIONS = [
  ["home", "Home"],
  ["back", "Back"],
  ["forward", "Forward"],
  ["pan", "Pan"],
  ["zoom", "Zoom"],
];

function modifiers(event) {
  const result = [];
  if (event.ctrlKey) result.push("ctrl");
  if (event.altKey) result.push("alt");
  if (event.metaKey) result.push("super");
  if (event.shiftKey) result.push("shift");
  return result;
}

function matplotlibKey(event) {
  let value = SPECIAL_KEYS[event.key] || event.key;
  const prefix = [];
  if (event.ctrlKey && event.key !== "Control") prefix.push("ctrl");
  if (event.altKey && event.key !== "Alt") prefix.push("alt");
  if (event.metaKey && event.key !== "Meta") prefix.push("super");
  // Browser key values already carry shift for printable characters ("A").
  if (event.shiftKey && event.key !== "Shift" && value.length > 1) prefix.push("shift");
  return [...prefix, value].join("+");
}

function listen(target, name, callback, options) {
  target.addEventListener(name, callback, options);
  return () => target.removeEventListener(name, callback, options);
}

export function render({ model, el }) {
  const shell = document.createElement("div");
  shell.className = "xy-matplotlib-widget";
  Object.assign(shell.style, {
    boxSizing: "border-box",
    display: "inline-flex",
    flexDirection: "column",
    maxWidth: "100%",
    verticalAlign: "top",
  });

  const toolbar = document.createElement("div");
  toolbar.className = "xy-matplotlib-toolbar";
  toolbar.setAttribute("role", "toolbar");
  toolbar.setAttribute("aria-label", "Matplotlib navigation");
  Object.assign(toolbar.style, {
    alignItems: "center",
    boxSizing: "border-box",
    flexWrap: "wrap",
    gap: "4px",
    minHeight: "30px",
    padding: "3px 4px",
  });
  const toolbarButtons = new Map();
  for (const [action, label] of TOOLBAR_ACTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = label;
    button.dataset.xyToolbarAction = action;
    if (action === "pan" || action === "zoom") {
      button.setAttribute("aria-pressed", "false");
    }
    Object.assign(button.style, {
      border: "1px solid #9ca3af",
      borderRadius: "3px",
      background: "#f8fafc",
      color: "#111827",
      cursor: "pointer",
      font: "12px/1.4 system-ui, sans-serif",
      padding: "2px 7px",
    });
    toolbar.appendChild(button);
    toolbarButtons.set(action, button);
  }

  const root = document.createElement("div");
  root.className = "xy-matplotlib-canvas";
  root.dataset.xyBackendWidget = "live";
  root.tabIndex = 0;
  Object.assign(root.style, {
    boxSizing: "border-box",
    display: "block",
    maxWidth: "100%",
    minHeight: "1px",
    minWidth: "1px",
    outline: "none",
    overflow: "hidden",
    resize: "both",
    touchAction: "none",
  });

  const status = document.createElement("div");
  status.className = "xy-matplotlib-status";
  status.dataset.xyToolbarStatus = "";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  Object.assign(status.style, {
    boxSizing: "border-box",
    color: "#374151",
    font: "12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace",
    minHeight: "22px",
    overflowWrap: "anywhere",
    padding: "3px 4px",
  });
  shell.append(toolbar, root, status);
  el.appendChild(shell);

  let logicalWidth = Number(model.get("width")) || 1;
  let logicalHeight = Number(model.get("height")) || 1;
  let observedWidth = logicalWidth;
  let observedHeight = logicalHeight;
  let closed = false;
  let timerHandle = null;
  const removers = [];

  for (const [action] of TOOLBAR_ACTIONS) {
    const button = toolbarButtons.get(action);
    removers.push(
      listen(button, "click", () => {
        if (!Boolean(model.get("toolbar_enabled"))) return;
        model.send({ type: "toolbar", action });
      }),
    );
  }

  const updateSize = () => {
    logicalWidth = Number(model.get("width")) || 1;
    logicalHeight = Number(model.get("height")) || 1;
    observedWidth = logicalWidth;
    observedHeight = logicalHeight;
    root.style.width = `${logicalWidth}px`;
    root.style.height = `${logicalHeight}px`;
  };
  const updateGeneration = () => {
    root.dataset.xyGeneration = String(model.get("generation") || 0);
  };
  const updateToolbar = () => {
    const enabled = Boolean(model.get("toolbar_enabled"));
    const mode = String(model.get("toolbar_mode") || "");
    toolbar.style.display = enabled ? "flex" : "none";
    toolbar.dataset.xyToolbarMode = mode;
    shell.dataset.xyToolbarEnabled = String(enabled);
    for (const [action] of TOOLBAR_ACTIONS) {
      const button = toolbarButtons.get(action);
      button.disabled =
        !enabled ||
        (action === "back" && !Boolean(model.get("toolbar_can_back"))) ||
        (action === "forward" && !Boolean(model.get("toolbar_can_forward")));
      if (action === "pan" || action === "zoom") {
        const pressed =
          (action === "pan" && mode === "pan/zoom") ||
          (action === "zoom" && mode === "zoom rect");
        button.setAttribute("aria-pressed", String(pressed));
        button.style.background = pressed ? "#dbeafe" : "#f8fafc";
      }
    }
  };
  const updateStatus = () => {
    const message = String(model.get("toolbar_message") || "");
    status.textContent = message || "\u00a0";
    status.dataset.xyToolbarStatus = message;
  };
  const updateCursor = () => {
    const name = String(model.get("cursor") || "pointer");
    root.dataset.xyCursor = name;
    root.style.cursor = CSS_CURSORS[name] || CSS_CURSORS.pointer;
  };
  const updateTimer = () => {
    if (timerHandle !== null) {
      clearInterval(timerHandle);
      timerHandle = null;
    }
    const configured = Math.round(Number(model.get("timer_interval")) || 0);
    if (configured <= 0 || closed) return;
    // Promptly wake Python once when a timer becomes active. Python owns the
    // deadline and will not run it early; this avoids waiting a whole browser
    // interval after animation setup or a background-tab throttle.
    model.send({ type: "event_loop" });
    // Browser comms cannot usefully sustain sub-frame timer traffic. The
    // Python timer keeps the authoritative deadline, so a heartbeat that is a
    // little late advances correctly without running callbacks early.
    const interval = Math.max(10, Math.min(1000, configured));
    timerHandle = setInterval(() => {
      model.send({ type: "event_loop" });
    }, interval);
  };
  const updateSvg = () => {
    root.innerHTML = String(model.get("svg") || "").replace(/^<\?xml[^>]*>\s*/i, "");
    const svg = root.querySelector(":scope > svg");
    if (svg) {
      svg.setAttribute("width", "100%");
      svg.setAttribute("height", "100%");
      svg.style.display = "block";
      svg.style.pointerEvents = "none";
    }
  };
  updateSize();
  updateGeneration();
  updateSvg();
  updateTimer();
  updateToolbar();
  updateStatus();
  updateCursor();
  for (const [trait, update] of [
    ["svg", updateSvg],
    ["width", updateSize],
    ["height", updateSize],
    ["generation", updateGeneration],
    ["timer_interval", updateTimer],
    ["toolbar_enabled", updateToolbar],
    ["toolbar_mode", updateToolbar],
    ["toolbar_can_back", updateToolbar],
    ["toolbar_can_forward", updateToolbar],
    ["toolbar_message", updateStatus],
    ["cursor", updateCursor],
  ]) {
    const name = `change:${trait}`;
    model.on(name, update);
    removers.push(() => model.off?.(name, update));
  }

  const coordinates = (event) => {
    const bounds = root.getBoundingClientRect();
    const width = bounds.width || logicalWidth;
    const height = bounds.height || logicalHeight;
    return {
      x: ((event.clientX - bounds.left) * logicalWidth) / width,
      y: logicalHeight - ((event.clientY - bounds.top) * logicalHeight) / height,
    };
  };

  const sendLocation = (name, event, extra = {}) => {
    const point = coordinates(event);
    model.send({
      type: "event",
      name,
      x: point.x,
      y: point.y,
      button: Number.isInteger(event.button) ? event.button : null,
      buttons: Number(event.buttons) || 0,
      modifiers: modifiers(event),
      ...extra,
    });
  };

  const pointerNames =
    typeof window.PointerEvent === "function"
      ? {
          down: "pointerdown",
          up: "pointerup",
          move: "pointermove",
          enter: "pointerenter",
          leave: "pointerleave",
        }
      : {
          down: "mousedown",
          up: "mouseup",
          move: "mousemove",
          enter: "mouseenter",
          leave: "mouseleave",
        };
  removers.push(
    listen(root, pointerNames.down, (event) => {
      root.focus({ preventScroll: true });
      try {
        root.setPointerCapture?.(event.pointerId);
      } catch {
        // Synthetic browser tests and some touch implementations do not
        // create an active pointer that can be captured.
      }
      sendLocation("button_press_event", event);
      event.preventDefault();
    }),
    listen(root, pointerNames.up, (event) => {
      sendLocation("button_release_event", event);
      try {
        root.releasePointerCapture?.(event.pointerId);
      } catch {
        // The pointer may already have been released by the browser.
      }
      event.preventDefault();
    }),
    listen(root, pointerNames.move, (event) => {
      sendLocation("motion_notify_event", event);
    }),
    listen(root, pointerNames.enter, (event) => {
      sendLocation("figure_enter_event", event);
    }),
    listen(root, pointerNames.leave, (event) => {
      sendLocation("figure_leave_event", event);
    }),
    listen(root, "dblclick", (event) => {
      sendLocation("button_press_event", event, { dblclick: true });
      event.preventDefault();
    }),
    listen(
      root,
      "wheel",
      (event) => {
        if (event.deltaY === 0) return;
        sendLocation("scroll_event", event, { step: event.deltaY < 0 ? 1 : -1 });
        event.preventDefault();
      },
      { passive: false },
    ),
    listen(root, "keydown", (event) => {
      model.send({ type: "event", name: "key_press_event", key: matplotlibKey(event) });
      event.preventDefault();
    }),
    listen(root, "keyup", (event) => {
      model.send({ type: "event", name: "key_release_event", key: matplotlibKey(event) });
      event.preventDefault();
    }),
  );

  const close = () => {
    if (closed) return;
    closed = true;
    if (timerHandle !== null) {
      clearInterval(timerHandle);
      timerHandle = null;
    }
    model.send({ type: "event", name: "close_event" });
  };
  removers.push(listen(root, "xy-close", close));

  const resizeObserver = new ResizeObserver((entries) => {
    const bounds = entries[entries.length - 1]?.contentRect;
    const width = Math.round(bounds?.width || 0);
    const height = Math.round(bounds?.height || 0);
    if (width <= 0 || height <= 0) return;
    if (Math.abs(width - observedWidth) < 1 && Math.abs(height - observedHeight) < 1) return;
    observedWidth = width;
    observedHeight = height;
    model.send({ type: "event", name: "resize_event", width, height });
  });
  resizeObserver.observe(root);

  return () => {
    resizeObserver.disconnect();
    if (timerHandle !== null) clearInterval(timerHandle);
    for (const remove of removers) remove();
    close();
    shell.remove();
  };
}

export default { render };
