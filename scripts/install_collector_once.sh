#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

uv venv --system-site-packages --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -e '.[collector]'
uv pip install --python .venv/bin/python \
  'lerobot @ git+https://github.com/huggingface/lerobot@0cf864870cf29f4738d3ade893e6fd13fbd7cdb5'

echo "[PASS] Collector installed. Runtime startup uses .venv directly and never downloads packages."
