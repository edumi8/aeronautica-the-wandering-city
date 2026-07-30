#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

python3 "$SCRIPT_DIR/validate.py" --build --verify-downloads "$@"

echo "Release artifacts are available in $ROOT_DIR/releases"
