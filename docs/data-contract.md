# Data Contract

## Dataset separation

LeRobot's `robot_type` is the built-in embodiment identifier used here. It does not make incompatible action
spaces interoperable. Gripper and dexterous-hand recordings therefore use separate schemas and datasets.

## Required attempt metadata

- `attempt_id`: monotonic local integer, never reused;
- `session_id`: collection session UUID;
- `task_en`: canonical English instruction used for VLA training;
- `task_zh`: optional Chinese description, never silently substituted for `task_en`;
- `operator_id`: stable pseudonymous operator identifier;
- `layout_id`: reproducible scene/layout identifier;
- `embodiment`: `gripper` or `dexterous_hand`;
- `status`: recording/success/failure/interrupted;
- `note` and `failure_reason`: optional;
- timestamps and software/schema versions.

## Frame contract to be frozen later

Every accepted frame bundle will contain four synchronized RGB images, actual joint feedback, commanded action,
and a monotonic acquisition timestamp. Color conversion occurs once at the ROS boundary. Original encoding,
message timestamps, receipt timestamps, synchronization skew, and dropped-frame counters remain in provenance.

## Language

Use a concise English imperative as the canonical training task, for example `Pick up the red block and place it
in the bucket.` Preserve object attributes and spatial relations. Store a Chinese explanation only as auxiliary
metadata. Do not create several paraphrases for the same trajectory unless the instruction remains exactly true.

