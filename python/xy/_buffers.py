"""Internal binary-attachment types and zero-copy NumPy byte views.

Live update transports accept buffer-protocol objects, so an encoded ndarray
does not need to become an owned ``bytes`` object before it reaches the actual
wire boundary. A ``memoryview`` retains its ndarray owner for as long as the
transport needs the attachment.
"""

from __future__ import annotations

from typing import TypeAlias

import numpy as np

WireBuffer: TypeAlias = bytes | memoryview


def array_byte_view(array: np.ndarray) -> memoryview:
    """Return an owner-retaining byte view over a C-contiguous ndarray.

    Non-contiguous inputs are copied only to satisfy the wire's contiguous
    buffer contract. Dtype conversion, when required, stays explicit at the
    caller so the encoded scalar format remains visible there.
    """

    owner = np.ascontiguousarray(array)
    return owner.data.cast("B")
