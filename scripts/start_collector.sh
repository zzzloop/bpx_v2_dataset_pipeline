#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[ERROR] Collector .venv is missing. Run scripts/install_collector_once.sh once while online." >&2
  exit 2
fi
if [[ -r /opt/ros/jazzy/setup.bash ]]; then
  set +u
  source /opt/ros/jazzy/setup.bash
  set -u
fi
if [[ -n "${BPX_ROBOT_SETUP:-}" ]]; then
  if [[ ! -r "${BPX_ROBOT_SETUP}" ]]; then
    echo "[ERROR] BPX_ROBOT_SETUP is not readable: ${BPX_ROBOT_SETUP}" >&2
    exit 2
  fi
  set +u
  source "${BPX_ROBOT_SETUP}"
  set -u
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[ERROR] ffmpeg is required for LeRobot MP4 episode encoding." >&2
  exit 2
fi

cd "${PROJECT_DIR}"
exec "${PYTHON_BIN}" -m bpx_v2_dataset_pipeline.collector.api \
  --host "${BPX_COLLECTOR_HOST:-127.0.0.1}" \
  --port "${BPX_COLLECTOR_PORT:-8765}" \
  --state-dir "${BPX_STATE_DIR:-state}" \
  --recordings-dir "${BPX_RECORDINGS_DIR:-recordings/lerobot/bpx_v2_humanoid_raw}" \
  "$@"
