# Protocol conformance and mutation policy

Status: **implemented** for TST-NI-028.

[`protocol-catalog.json`](protocol-catalog.json) is the executable catalog for
every request dispatched by `xy.channel.handle_message` and every reply it can
return. The catalog is deliberately data, not a second dispatcher: tests derive
the implementation's request branches from the `handle_message` AST and require
an exact match. Adding or removing a branch without updating the catalog fails.

Each request has five generated cases: a valid message, a missing-field or
missing-discriminator message, a wrong-type message, a boundary message, and a
callback case. The callback case records exact hook order. Reply entries declare
required fields and buffer cardinality and carry committed `XYBF` frames. Python
must reproduce and decode those bytes exactly; the shipped JavaScript
`decodeFrame` consumes the same base64 frames without copies.

The required Hypothesis suite mutates every structural class in batches:
magic/version/flags/header size, metadata and total lengths, buffer count,
metadata bytes, metadata padding, buffer lengths, and buffer padding. For every
mutation Python and the shipped JavaScript decoder must either both reject it or
produce the same metadata and buffers. Rejection is the normal result for
structural corruption; an accidental mutation that remains valid is acceptable
only when the decoded results preserve cross-language parity.

`make check-protocol` is the stable local entry point. Main CI runs the same
catalog, golden-frame, handwritten framing, and property-mutation suites as a
hard step and retains JUnit evidence even on failure. Node and Hypothesis are
required lane dependencies; missing either is a collection or command failure,
never a skip.
