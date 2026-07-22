PYTHON ?= .venv/bin/python
CHROMIUM ?=
UV_CACHE_DIR ?= /tmp/xy_uv_cache
WHEEL_EXPECT ?=
SDIST ?=
WHEEL ?=
BENCHMARK_JSON ?= benchmark.json
BENCHMARK_KIND ?= auto
BENCHMARK_PROFILE ?= baseline
COVERAGE_JSON ?= coverage/python/coverage.json
COVERAGE_BASE ?= origin/main
COVERAGE_HEAD ?= HEAD
COVERAGE_REPORT ?= coverage/python/ratchet.json

.PHONY: help setup setup-browser check check-full check-browser check-labels check-pan-zoom check-conformance check-docs check-examples check-security check-errors check-api check-import check-ci check-claims check-testing-spec check-benchmark-harness check-coverage check-pyplot check-pyplot-speed check-sdist check-wheel check-artifacts check-benchmark-report list-checks test lint format typecheck public-api python-floor js-check js-test rust-check abi-smoke

help:
	@printf '%s\n' \
		'xy developer shortcuts' \
		'' \
		'  make setup            create .venv, install .[dev], and build the native core' \
		'  make setup-browser    install the pinned Playwright browser-test driver' \
		'  make check            run the fast local verification gate' \
		'  make check-full       run JS, Rust, and ABI gates too' \
		'  make check-browser    run browser smokes, including every chart kind, runtime security, animation, and pick boundaries (set CHROMIUM=/path/to/chrome)' \
		'  make check-labels     run strict formatter units and rendered-label DOM oracles' \
		'  make check-pan-zoom   run the complete Chromium pan/zoom acceptance matrix (set CHROMIUM=/path/to/chrome)' \
		'  make check-conformance run the bounded accessibility/DPR/motion matrix in Chromium, Firefox, and WebKit' \
		'  make check-docs       run docs examples and public claim guardrails' \
		'  make check-examples   run README/API examples and Reflex asset registry checks' \
		'  make check-security   run standalone HTML safety and client text-sink checks' \
		'  make check-errors     run public error, LOD, and mutation-safety tests' \
		'  make check-api        run lazy public API and type-surface checks' \
		'  make check-import     run import-time and dependency-boundary checks' \
		'  make check-ci         run CI/release workflow invariant checks' \
		'  make check-claims     run public performance-claim guardrails' \
		'  make check-testing-spec validate all specifications, evidence, and public claims' \
		'  make check-benchmark-harness run benchmark metadata/report/regression tests' \
		'  make check-coverage    validate a branch-aware COVERAGE_JSON against package/module and COVERAGE_BASE..COVERAGE_HEAD diff floors' \
		'  make check-pyplot      run the matplotlib-shim suite and compatibility corpus' \
		'  make check-pyplot-speed enforce the per-family 10x static-PNG target (requires .[bench])' \
		'  make check-sdist      build and verify the source distribution' \
		'  make check-wheel      build and verify a wheel (set WHEEL_EXPECT=--expect-native)' \
		'  make check-artifacts  verify prebuilt artifacts (set SDIST=... WHEEL=...)' \
		'  make check-benchmark-report validate BENCHMARK_JSON (scatter-vs, pyplot-vs-matplotlib, line-decimation, install-footprint, core-2d, scatter-native, heatmap-native, kernel-native, interaction-browser, dashboard-browser, workflow-native); set BENCHMARK_PROFILE=strict for dashboard release health' \
		'                        override UV_CACHE_DIR if your uv cache lives elsewhere' \
		'  make list-checks      list verifier check names' \
		'  make test             run pytest' \
		'  make lint             run ruff check' \
		'  make format           run ruff format --check' \
		'  make typecheck        run ty over the shippable package' \
		'  make js-check         verify committed JS bundles are fresh' \
		'  make js-test          run dependency-free JS semantic units with coverage' \
		'  make rust-check       run cargo test and clippy'

setup:
	uv venv
	uv pip install -e ".[dev]"
	cargo build --release

setup-browser:
	npm install
	npx playwright install chromium

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

check-labels:
	@node -e "require.resolve('playwright')" >/dev/null 2>&1 || { \
		echo 'Playwright is required. Run: make setup-browser' >&2; \
		exit 2; \
	}
	npm run test:labels

check-pan-zoom:
	@if [ -z "$(CHROMIUM)" ]; then \
		echo 'Set CHROMIUM=/path/to/chrome for the pan/zoom matrix.' >&2; \
		exit 2; \
	fi
	@node -e "require.resolve('playwright')" >/dev/null 2>&1 || { \
		echo 'Playwright is required. Run: make setup-browser' >&2; \
		exit 2; \
	}
	node scripts/pan_zoom_matrix.mjs --profile full --browsers chromium \
		--executable-path "$(CHROMIUM)" --evidence /tmp/xy-pan-zoom-matrix-evidence.json

check-conformance:
	@node -e "require.resolve('playwright')" >/dev/null 2>&1 || { \
		echo 'Playwright is required. Run: make setup-browser && npx playwright install chromium firefox webkit' >&2; \
		exit 2; \
	}
	node scripts/browser_conformance.mjs
	node scripts/pan_zoom_matrix.mjs --profile focused \
		--browsers chromium,firefox,webkit \
		--evidence /tmp/xy-pan-zoom-cross-engine-evidence.json

check-docs:
	$(PYTHON) scripts/verify_local.py --only examples,claim_guardrails,testing_spec

check-examples:
	$(PYTHON) scripts/verify_local.py --only examples

check-pyplot:
	$(PYTHON) scripts/check_pyplot_options.py
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

check-testing-spec:
	$(PYTHON) scripts/verify_local.py --only testing_spec,claim_guardrails

check-benchmark-harness:
	$(PYTHON) scripts/verify_local.py --only benchmark_harness

check-coverage:
	$(PYTHON) scripts/coverage_ratchet.py \
		--coverage-json "$(COVERAGE_JSON)" \
		--base "$(COVERAGE_BASE)" --head "$(COVERAGE_HEAD)" \
		--report "$(COVERAGE_REPORT)"

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
	$(PYTHON) scripts/verify_benchmark_report.py "$(BENCHMARK_JSON)" --kind "$(BENCHMARK_KIND)" --profile "$(BENCHMARK_PROFILE)"

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
	node js/build.mjs --check

js-test:
	node --test --experimental-test-coverage \
		--test-coverage-include=python/xy/static/index.js \
		--test-coverage-lines=15 --test-coverage-branches=60 \
		--test-coverage-functions=10 js/test/*.test.mjs

rust-check:
	cargo test
	cargo clippy --all-targets -- -D warnings

abi-smoke:
	$(PYTHON) scripts/abi_smoke.py
