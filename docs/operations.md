# Operations

## Collector recovery

1. Start the web console and verify it reports `mock` or the expected ROS2 adapter.
2. Select end effector, enter English task, operator ID and layout ID.
3. Start an attempt; the ID is allocated immediately.
4. Stop and label success/failure. Notes and failure reason are optional.
5. After a process or power interruption, restart the service. Previous `recording` attempts are automatically
   marked `interrupted`; the next attempt receives a new ID.

## Server publication gates

Before a dataset version may train a model, record and verify:

- schema version and robot type;
- episode/task/operator/layout distributions;
- exact frame, video and episode counts;
- timestamp monotonicity, synchronization skew and missing frames;
- finite state/action values, ranges and joint ordering;
- video decode samples and RGB contract;
- spike report and every repaired coordinate;
- input/output hashes and immutable manifest;
- held-out evaluation split defined before training.

Cleaning never mutates the only copy. Write a new version, validate it, then atomically publish it.

## Online augmentation

Use photometric augmentation only on the training split. One sampled transform is shared by all camera views and
temporal frames in a training item. Default policy changes brightness, contrast and gamma without hue rotation,
horizontal flip, arbitrary crop or geometric warp. This preserves left/right camera meaning and color-conditioned
language. Keep an augmentation-off run for ablation.

