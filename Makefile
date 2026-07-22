PYTHON ?= .venv/bin/python
CHROMIUM ?=
UV_CACHE_DIR ?= /tmp/xy_uv_cache
WHEEL_EXPECT ?=
SDIST ?=
WHEEL ?=
BENCHMARK_JSON ?= benchmark.json
BENCHMARK_KIND ?= auto

.PHONY: help setup setup-browser check check-full check-browser check-conformance check-docs check-examples check-security check-errors check-api check-import check-ci check-claims check-benchmark-harness check-pyplot check-pyplot-speed check-sdist check-wheel check-artifacts check-benchmark-report list-checks test lint format typecheck public-api python-floor js-check rust-check abi-smoke

help:
	@printf '%s\n' \
		'xy developer shortcuts' \
		'' \
		'  make setup            create .venv, install .[dev], and build the native core' \
		'  make setup-browser    install the pinned Playwright browser-test driver' \
		'  make check            run the fast local verification gate' \
		'  make check-full       run JS, Rust, and ABI gates too' \
		'  make check-browser    run browser smokes (set CHROMIUM=/path/to/chrome)' \
		'  make check-conformance run accessibility + Chromium/Firefox/WebKit conformance' \
		'  make check-docs       run docs examples and public claim guardrails' \
		'  make check-examples   run README/API examples and Reflex asset registry checks' \
		'  make check-security   run standalone HTML safety and client text-sink checks' \
		'  make check-errors     run public error, LOD, and mutation-safety tests' \
		'  make check-api        run lazy public API and type-surface checks' \
		'  make check-import     run import-time and dependency-boundary checks' \
		'  make check-ci         run CI/release workflow invariant checks' \
		'  make check-claims     run public performance-claim guardrails' \
		'  make check-benchmark-harness run benchmark metadata/report/regression tests' \
		'  make check-pyplot      run the matplotlib-shim suite and compatibility corpus' \
		'  make check-pyplot-speed enforce the per-family 10x static-PNG target (requires .[bench])' \
		'  make check-sdist      build and verify the source distribution' \
		'  make check-wheel      build and verify a wheel (set WHEEL_EXPECT=--expect-native)' \
		'  make check-artifacts  verify prebuilt artifacts (set SDIST=... WHEEL=...)' \
		'  make check-benchmark-report validate BENCHMARK_JSON (scatter-vs, pyplot-vs-matplotlib, line-decimation, install-footprint, core-2d, scatter-native, heatmap-native, kernel-native, interaction-browser, dashboard-browser, workflow-native)' \
		'                        override UV_CACHE_DIR if your uv cache lives elsewhere' \
		'  make list-checks      list verifier check names' \
		'  make test             run pytest' \
		'  make lint             run ruff check' \
		'  make format           run ruff format --check' \
		'  make typecheck        run ty over the shippable package' \
		'  make js-check         build the render client from source' \
		'  make rust-check       run cargo test and clippy'

setup:
	uv venv
	uv pip install -e ".[dev]"
	cargo build --release

setup-browser:
	npm install

check:
	$(PYTHON) scripts/verify_local.py --quick

check-full:
	$(PYTHON) scripts/verify_local.py --full

check-browser:
	@if [ -z "$(CHROMIUM)" ]; then \
		echo 'Set CHROMIUM=/path/to/chrome for browser smoke checks.' >&2; \
		exit 2; \
	fi
	@node -e "require.resolve('playwright')" >/dev/null 2>&1 || { \
		echo 'Playwright is required for the standalone worker probe. Run: make setup-browser' >&2; \
		exit 2; \
	}
	$(PYTHON) scripts/verify_local.py --browser --chromium "$(CHROMIUM)"

check-conformance:
	@node -e "require.resolve('playwright')" >/dev/null 2>&1 || { \
		echo 'Playwright is required. Run: make setup-browser && npx playwright install chromium firefox webkit' >&2; \
		exit 2; \
	}
	node scripts/browser_conformance.mjs

check-docs:
	$(PYTHON) scripts/verify_local.py --only examples,claim_guardrails

check-examples:
	$(PYTHON) scripts/verify_local.py --only examples

check-pyplot:
	$(PYTHON) -m pytest tests/pyplot -q

check-security:
	$(PYTHON) scripts/verify_local.py --only security_export

check-errors:
	$(PYTHON) scripts/verify_local.py --only error_safety

check-api:
	$(PYTHON) scripts/verify_local.py --only public_api,api_surface

check-import:
	$(PYTHON) scripts/verify_local.py --only public_api,import_budget

check-ci:
	$(PYTHON) scripts/verify_local.py --only ci_workflow

check-claims:
	$(PYTHON) scripts/verify_local.py --only claim_guardrails

check-benchmark-harness:
	$(PYTHON) scripts/verify_local.py --only benchmark_harness

check-pyplot-speed:
	PYTHONPATH=python $(PYTHON) benchmarks/bench_pyplot_vs_matplotlib.py \
		--profile standard --reps 21 --warmups 3 --target-speedup 10 --require-target

check-sdist:
	@set -e; \
	OUT=$$(mktemp -d); \
	echo "building sdist in $$OUT"; \
	UV_CACHE_DIR="$(UV_CACHE_DIR)" uv build --sdist --out-dir "$$OUT"; \
	$(PYTHON) scripts/verify_sdist.py "$$OUT"/xy-*.tar.gz

check-wheel:
	@set -e; \
	OUT=$$(mktemp -d); \
	echo "building wheel in $$OUT"; \
	UV_CACHE_DIR="$(UV_CACHE_DIR)" uv build --wheel --out-dir "$$OUT"; \
	$(PYTHON) scripts/verify_wheel.py "$$OUT"/xy-*.whl $(WHEEL_EXPECT)

check-artifacts:
	@if [ -z "$(SDIST)" ]; then \
		echo 'Set SDIST=/path/to/xy.tar.gz for artifact verification.' >&2; \
		exit 2; \
	fi
	@if [ -z "$(WHEEL)" ]; then \
		echo 'Set WHEEL=/path/to/xy.whl for artifact verification.' >&2; \
		exit 2; \
	fi
	$(PYTHON) scripts/verify_local.py --packaging --sdist "$(SDIST)" --wheel "$(WHEEL)" $(WHEEL_EXPECT)

check-benchmark-report:
	$(PYTHON) scripts/verify_benchmark_report.py "$(BENCHMARK_JSON)" --kind "$(BENCHMARK_KIND)"

list-checks:
	$(PYTHON) scripts/verify_local.py --list

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m ty check python

public-api:
	$(PYTHON) scripts/check_public_api.py

python-floor:
	$(PYTHON) scripts/check_python_floor.py

js-check:
	node js/build.mjs

rust-check:
	cargo test
	cargo clippy --all-targets -- -D warnings

abi-smoke:
	$(PYTHON) scripts/abi_smoke.py
