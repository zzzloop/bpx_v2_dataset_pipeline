#!/usr/bin/env bash
set -Eeuo pipefail
readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly PYTHON_BIN="${PROJECT_DIR}/.venv-ros1/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo '[ERROR] First run: bash scripts/install_ros1_collector_once.sh' >&2
  exit 2
fi
if [[ -r /opt/ros/noetic/setup.bash ]]; then
  set +u
  source /opt/ros/noetic/setup.bash
  set -u
fi
if [[ -n "${BPX_ROBOT_SETUP:-}" ]]; then
  if [[ ! -r "${BPX_ROBOT_SETUP}" ]]; then
    echo '[ERROR] BPX_ROBOT_SETUP is not readable.' >&2
    exit 2
  fi
  set +u
  source "${BPX_ROBOT_SETUP}"
  set -u
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo '[ERROR] ffmpeg/ffprobe missing. Install system ffmpeg once while online.' >&2
  exit 2
fi
"${PYTHON_BIN}" -c 'import rospy, numpy, pyarrow; from sensor_msgs.msg import Image, JointState' || {
  echo '[ERROR] ROS1 or recorder dependencies unavailable; check Noetic setup and .venv-ros1.' >&2
  exit 2
}
"${PYTHON_BIN}" -c 'import socket,rosgraph; socket.setdefaulttimeout(3); rosgraph.Master("/bpx_v1_collector_probe").getPid()' || {
  echo '[ERROR] ROS master is unavailable. Start the existing robot/ROS master first; this recorder never starts hardware.' >&2
  exit 2
}
cd "${PROJECT_DIR}"
exec "${PYTHON_BIN}" -m ros1_collector.app "$@"
