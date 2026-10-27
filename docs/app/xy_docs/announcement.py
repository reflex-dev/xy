"""Marketing presentation and persistence around the shared announcement."""

import json

import reflex as rx

# Match reflex-marketing so dismissals carry across the same-origin sites.
ANNOUNCEMENT_RELEASE = "build-vs-buy-internal-software-v1"
ANNOUNCEMENT_TITLE = "Build vs. Buy for Internal Software"
ANNOUNCEMENT_URL = "https://reflex.dev/blog/build-vs-buy-internal-software/"


def match_marketing_announcement(component: rx.Component) -> None:
    """Adapt shared markup to reflex-marketing without copying its banner body."""
    if "data-announcement" in component.custom_attrs:
        link, dismiss = component.children
        link.href = rx.Var.create(ANNOUNCEMENT_URL)
        link.custom_attrs["aria-label"] = (
            f"New: {ANNOUNCEMENT_TITLE} — Read more (opens in a new tab)"
        )
        link.children = link.children[:1]
        link.children[0].children[0].custom_attrs["aria-hidden"] = True
        message = link.children[0].children[1]
        message.children = rx.fragment(ANNOUNCEMENT_TITLE).children
        message.custom_attrs["data-shimmer-text"] = ANNOUNCEMENT_TITLE
        dismiss.custom_attrs["data-announcement-dismiss"] = ""
        component.children.insert(
            0,
            rx.el.div(
                *[rx.el.span() for _ in range(5)],
                class_name="docs-announcement-glass",
                aria_hidden=True,
            ),
        )
        return
    for child in component.children:
        match_marketing_announcement(child)


def announcement_visibility_script() -> str:
    """Restore marketing's release-scoped dismissal before the page paints."""
    return """(() => {
  const release = __RELEASE__;
  const key = 'reflex_announcement_dismissed_release';
  const sync = () => {
    let dismissed = false;
    try { dismissed = localStorage.getItem(key) === release; } catch (_) {}
    if (dismissed) document.documentElement.dataset.announcementDismissed = 'true';
    else delete document.documentElement.dataset.announcementDismissed;
  };
  sync();
  if (window.__xyAnnouncementVisibilityInstalled) return;
  window.__xyAnnouncementVisibilityInstalled = true;
  document.addEventListener('click', (event) => {
    if (!(event.target instanceof Element) ||
        !event.target.closest('.docs-nav-frame [data-announcement-dismiss]')) return;
    try { localStorage.setItem(key, release); } catch (_) {}
    document.documentElement.dataset.announcementDismissed = 'true';
  }, true);
  window.addEventListener('storage', (event) => {
    if (event.key === key || event.key === null) sync();
  });
})();""".replace("__RELEASE__", json.dumps(ANNOUNCEMENT_RELEASE))
