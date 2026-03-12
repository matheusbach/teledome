#!/usr/bin/env bash
set -euo pipefail

# Resolve project root (directory containing this script)
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' not found. Install from https://github.com/astral-sh/uv" >&2
  exit 1
fi

VENV="$ROOT/.venv"
PYTHON_VERSION="3.12"

# Create venv with uv if missing
if [ ! -d "$VENV" ]; then
  # uv will auto-download Python if the specified version is missing.
  uv venv --python "$PYTHON_VERSION" "$VENV"
fi

# Activate venv
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Install deps
uv pip install -r "$ROOT/requirements.txt"

# Run the downloader
python -m src.main "$@"
