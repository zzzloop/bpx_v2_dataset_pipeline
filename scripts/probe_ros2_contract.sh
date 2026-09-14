#!/usr/bin/env bash
set -Eeuo pipefail

# Passive inspection only: this script never publishes to any ROS 2 topic.
readonly OUTPUT_DIR="${1:-state/ros2-contract-probe}"
readonly DURATION_SEC="${BPX_PROBE_DURATION_SEC:-6}"
readonly TOPICS=(
  /arm_joint_command
  /head_joint_command
  /gripper_move
  /arm_joint_feedback
  /head_joint_feedback
  /gripper_status
  /data/left_eye_image
  /data/right_eye_image
  /data/left_wrist_image
  /data/right_wrist_image
)

if ! command -v ros2 >/dev/null 2>&1; then
  echo "[ERROR] ros2 is not available; source the ROS 2 Jazzy environment first." >&2
  exit 2
fi

mkdir -p "${OUTPUT_DIR}"
ros2 topic list -t >"${OUTPUT_DIR}/topic-list.txt"
ros2 node list >"${OUTPUT_DIR}/node-list.txt"

for topic in "${TOPICS[@]}"; do
  safe_name="${topic//\//_}"
  topic_type="$(ros2 topic type "${topic}" 2>/dev/null || true)"
  if [[ -z "${topic_type}" ]]; then
    echo "MISSING ${topic}" | tee -a "${OUTPUT_DIR}/summary.txt"
    continue
  fi
  echo "FOUND ${topic} ${topic_type}" | tee -a "${OUTPUT_DIR}/summary.txt"
  ros2 topic info -v "${topic}" >"${OUTPUT_DIR}/${safe_name}.info.txt" 2>&1 || true
  timeout "${DURATION_SEC}s" ros2 topic hz --window 30 "${topic}" \
    >"${OUTPUT_DIR}/${safe_name}.hz.txt" 2>&1 || true
done

echo "[PASS] Passive ROS 2 report written to ${OUTPUT_DIR}"
echo "Review topic-list.txt, summary.txt and the *.info.txt/*.hz.txt files before formal collection."
