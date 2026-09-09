# Architecture

## Two runtime environments

### Industrial computer

- Ubuntu with ROS2 Jazzy.
- Subscribes only; the collector never sends motor commands.
- Web UI controls metadata and recording lifecycle.
- Each recording attempt is isolated and recoverable.
- A hardware-independent `CaptureBackend` feeds synchronized frames to the writer.

### Server

- Treats accepted LeRobot shards as immutable inputs.
- Audits before merging.
- Produces versioned cleaned datasets instead of editing canonical input in place.
- Uses process-level parallelism per episode for CPU-bound audit/clean/export work.
- OpenPI consumes one fixed dataset version and its matching normalization statistics.

## Plugin boundary

`CaptureBackend` is the only component allowed to know ROS2 topic names, message types, QoS, image encoding,
and synchronization policy. The mock implementation exercises the same service API without ROS. When hardware
details are ready, `Ros2JazzyBackend` will be added without changing the UI, attempt database, server tools, or
training integration.

## Crash model

The SQLite registry uses WAL mode and full synchronization. Starting an attempt commits its ID before frame
capture starts. A clean finish transitions it to `success` or `failure`. On application restart, all remaining
`recording` attempts become `interrupted`; IDs are never reused.

Formal data publication will use a staging directory and an atomic rename on the same filesystem. Partially
written shards never appear in the canonical dataset index.

