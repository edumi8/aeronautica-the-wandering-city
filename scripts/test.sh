#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  # `command -v` only checks that a name resolves to *something* executable;
  # on Windows, `python3`/`python` can resolve to the Microsoft Store's
  # install-nag stub even when no real interpreter is present, so actually
  # invoke each candidate and check it runs.
  for candidate in python3 python py; do
    if "$candidate" --version >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: no working Python 3 interpreter was found on PATH (checked python3, python, py)." >&2
    exit 2
  fi
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/test_pipeline.py" "$@"
