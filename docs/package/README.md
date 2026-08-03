# reflex-xy-docs-bundle

The XY charting-library documentation bundled as a redistributable Python
wheel. Built on demand; not published to PyPI.

```python
from reflex_xy_docs_bundle import DOCS_DIR, get_doc, list_docs

list_docs()  # ["charts/bar.md", ...]
get_doc("charts/bar.md")  # markdown source as a string
DOCS_DIR / "charts" / "bar.md"
```
