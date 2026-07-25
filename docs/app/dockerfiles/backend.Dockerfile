FROM rust:1.97.0-slim-bookworm AS rust-toolchain

FROM python:3.13-slim-bookworm AS builder

ENV CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH=/usr/local/cargo/bin:${PATH} \
    UV_LINK_MODE=copy \
    XY_REQUIRE_CARGO=1

COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup

RUN apt-get update && \
    apt-get install --yes --no-install-recommends build-essential ca-certificates git && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv==0.11.15

COPY . /app
WORKDIR /app

RUN uv sync --project docs/app --frozen --no-dev && \
    docs/app/.venv/bin/python -c \
      "import xy.kernels as kernels; assert kernels.BACKEND == 'native', kernels.BACKEND" && \
    find target/release -mindepth 1 -maxdepth 1 ! -name 'libxy_core.so' -exec rm -rf {} +

FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false \
    XY_NATIVE_LIB=/app/target/release/libxy_core.so

RUN apt-get update && \
    apt-get install --yes --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app
WORKDIR /app/docs/app

ENTRYPOINT ["/app/docs/app/.venv/bin/reflex", "run", "--env", "prod", "--backend-only", "--backend-port", "8000", "--loglevel", "info"]
