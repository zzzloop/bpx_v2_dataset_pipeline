#!/usr/bin/env bash
set -Eeuo pipefail
readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"
readonly ROS1_PYTHON="${BPX_ROS1_PYTHON:-/usr/bin/python3}"
if [[ -e .venv-ros1 ]]; then
  echo '[ERROR] .venv-ros1 already exists; not overwriting it. Use its pip to install ros1_collector/requirements.txt if needed.' >&2
  exit 2
fi
"${ROS1_PYTHON}" -c 'import sys; assert (3,8) <= sys.version_info[:2] <= (3,11), "Use the ROS1 Python 3.8-3.11 interpreter"'
"${ROS1_PYTHON}" -m venv --system-site-packages .venv-ros1
.venv-ros1/bin/python -m pip install --only-binary=:all: -r ros1_collector/requirements.txt
echo '[PASS] ROS1 collector dependencies installed in .venv-ros1 only.'
echo 'Runtime startup is offline. It never installs OpenPI, torch, LeRobot, or ROS2.'
