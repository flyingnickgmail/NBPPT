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
NBPPT_TEST_RUN="$(mktemp -d "$NBPPT_TEST_ROOT/run.XXXXXX")"
python -m pytest -q --basetemp "$NBPPT_TEST_RUN/pytest" --junitxml "$NBPPT_TEST_RUN/junit.xml" "$@"
node --test tests/*.cjs tools/report_studio/tests/*.cjs
git diff --check
