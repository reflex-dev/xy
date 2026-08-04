"""External-consumer assertions for the lazy ``xy`` root API.

This module is checked by ty but is not a pytest test.  Keep the imports rooted
at ``xy``: importing the implementation modules directly would miss regressions
where a lazy root export silently falls back to ``Any``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, assert_type

import xy


def _build_plugin(context: xy.MarkContext) -> Sequence[xy.Mark]:
    del context
    return ()


def check_root_typing_surface() -> None:
    """Type-check the public root without executing or mutating the registry."""
    if TYPE_CHECKING:
        assert_type(xy.__version__, str)

        assert_type(xy.Animation(), xy.Animation)
        assert_type(xy.ExportConfig(), xy.ExportConfig)
        assert_type(xy.Spring(), xy.Spring)
        assert_type(xy.MarkContext(columns={}, options={}), xy.MarkContext)
        assert_type(xy.MarkPlugin(name="consumer_fixture", build=_build_plugin), xy.MarkPlugin)

        assert_type(xy.animation(), xy.Animation)
        assert_type(xy.export_config(), xy.ExportConfig)
        assert_type(xy.mark("plugin"), xy.Mark)
        assert_type(xy.segments(), xy.Mark)
        assert_type(xy.segments_chart(), xy.Chart)
        assert_type(xy.spring(), xy.Spring)
        assert_type(xy.triangle_mesh(), xy.Mark)
        assert_type(xy.triangle_mesh_chart(), xy.Chart)

        plugin = xy.MarkPlugin(name="consumer_fixture", build=_build_plugin)
        assert_type(xy.register_mark(plugin), xy.MarkPlugin)
        assert_type(xy.registered_marks(), tuple[str, ...])
        assert_type(xy.unregister_mark("consumer_fixture"), None)
