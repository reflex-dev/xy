#!/usr/bin/env bash
# Full UX ladder, smallest first, one invocation per size.
#
# Per-size invocation (rather than one call with every size) buys three
# things: each size's video and JSON land the moment that size finishes so
# results are inspectable while the rest runs; a size that hangs or dies
# cannot take the remaining ladder with it; and per-size timeouts can scale
# with N instead of one worst-case value applied everywhere.
#
#   ./benchmarks/run_ux_suite.sh <output-dir>
set -uo pipefail

OUT="${1:?usage: run_ux_suite.sh <output-dir>}"
ARMS="xy,xy-exact,plotly,matplotlib,datashader"
SIZES=(10000 100000 500000 1000000 2500000 5000000 10000000 25000000 50000000 100000000)
PY="$(cd "$(dirname "$0")/.." && pwd)/.venv/bin/python"
BENCH="$(cd "$(dirname "$0")" && pwd)/bench_ux.py"

mkdir -p "$OUT"
: "${CHROME:=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
export CHROME

label() {  # 10000 -> 10k, 2500000 -> 2.5M
  "$PY" -c "n=$1; print(f'{n/1e6:g}M' if n>=1e6 else f'{n//1000}k')"
}

echo "ladder: ${SIZES[*]}"
echo "output: $OUT"
echo

for n in "${SIZES[@]}"; do
  tag="$(label "$n")"
  # Big sizes need room for the server arms: WebAgg re-rasterizes every row on
  # each of 7 box zooms, so its settle alone scales with N.
  if   [ "$n" -le 1000000 ];  then t=180
  elif [ "$n" -le 10000000 ]; then t=420
  elif [ "$n" -le 50000000 ]; then t=900
  else                             t=1500
  fi

  echo "=== $tag (timeout ${t}s) — $(date +%H:%M:%S) ==="
  "$PY" "$BENCH" \
    --sizes "$n" --arms "$ARMS" \
    --timeout "$t" --memory-gib 40 \
    --out "$OUT/ux-$tag.json" 2>&1 \
    | grep -E '"arm"|grid video' || echo "  (size $tag produced no rows)"

  # The grid's PNG staging is large and single-use; the mp4 is the artifact.
  rm -rf "$OUT/ux-$tag-grid-$n-frames"
  echo
done

echo "=== ladder complete — $(date +%H:%M:%S) ==="
ls -1 "$OUT"/*.mp4 2>/dev/null || echo "(no grid videos)"
