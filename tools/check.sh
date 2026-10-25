#!/usr/bin/env bash
# Shared local/CI entry point. All temporary test output stays under this task.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${NBPPT_TEST_ROOT:?Set NBPPT_TEST_ROOT to a dedicated task directory}"
mkdir -p "$NBPPT_TEST_ROOT"
NBPPT_TEST_ROOT="$(cd "$NBPPT_TEST_ROOT" && pwd)"
for program in python node ffmpeg ffprobe; do
  command -v "$program" >/dev/null || { echo "Required test dependency missing: $program" >&2; exit 1; }
done
# Keep numerical-library threads inside the production media subprocess budget.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python -B tools/quality_gate.py --output "$NBPPT_TEST_ROOT" "$@"
