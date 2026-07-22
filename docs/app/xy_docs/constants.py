"""Public XY documentation constants."""

import os

PUBLIC_DOCS_URL = "https://reflex.dev/docs/xy"
PUBLIC_XY_VERSION = os.getenv("XY_DOCS_PUBLIC_VERSION", "0.0.1").strip()
DOCS_CHANNEL = os.getenv("XY_DOCS_CHANNEL", "preview").strip().lower()
SOCIAL_IMAGE_URL = f"{PUBLIC_DOCS_URL}/xy-social-card.png"
LLMS_TXT_PATH = "/llms.txt"
LLMS_FULL_TXT_PATH = "/llms-full.txt"

if DOCS_CHANNEL not in {"preview", "stable"}:
    msg = "XY_DOCS_CHANNEL must be either 'preview' or 'stable'"
    raise ValueError(msg)

__all__ = [
    "DOCS_CHANNEL",
    "LLMS_FULL_TXT_PATH",
    "LLMS_TXT_PATH",
    "PUBLIC_DOCS_URL",
    "PUBLIC_XY_VERSION",
    "SOCIAL_IMAGE_URL",
]
