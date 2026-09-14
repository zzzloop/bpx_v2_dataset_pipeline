# ROS2 Jazzy 真机采集契约

本契约于 2026-09-14 根据硬件组的 ROS2 MCAP、URDF 和命令文档闭合，机器可读版本为
`configs/ros2-jazzy-hardware.toml`。采集节点是**纯订阅者**：不会创建 publisher，也不会发布
使能、关节、夹爪、腰部或底盘命令。

## 训练帧

每帧包含四路 `640×480`、30 FPS 图像，以及 18 维状态和动作：

```text
[左臂 7, 右臂 7, head_pan, head_tilt, 左夹爪, 右夹爪]
```

- 手臂位置直接按消息索引读取，单位 rad；索引 `0..6` 为左臂，`7..13` 为右臂。
- 头部消息单位为 degree，写入数据集前显式转换为 rad。
- 夹爪 `grippers[0]` 是左、`grippers[1]` 是右；原始范围 `0..100`，训练值为 `0..1`。
- 遥操 command 是本项目的权威 action。采集端不增加限位、平滑或轨迹改写。
- 触觉尚未完成，当前 schema 不记录 `/gripper_tactile`。

## Topic

| 数据 | Topic | ROS message | 频率 |
| --- | --- | --- | --- |
| 手臂状态 | `/arm_joint_feedback` | `stm32_ros_bridge_msgs/msg/ArmJointFeedback` | 当前约 109Hz，目标 100Hz |
| 头部状态 | `/head_joint_feedback` | `stm32_ros_bridge_msgs/msg/HeadJointFeedback` | 当前约 109Hz，目标 100Hz |
| 夹爪状态 | `/gripper_status` | `stm32_ros_bridge_msgs/msg/GripperStatus` | 10Hz |
| 手臂动作 | `/arm_joint_command` | `stm32_ros_bridge_msgs/msg/ArmJointCommand` | ≥50Hz |
| 头部动作 | `/head_joint_command` | `stm32_ros_bridge_msgs/msg/HeadJointCommand` | ≥50Hz |
| 夹爪动作 | `/gripper_move` | `stm32_ros_bridge_msgs/msg/GripperMove` | ≥50Hz |
| 左/右眼 | `/data/left_eye_image`, `/data/right_eye_image` | `sensor_msgs/msg/Image` | 30Hz |
| 左/右腕 | `/data/left_wrist_image`, `/data/right_wrist_image` | `sensor_msgs/msg/Image` | 30Hz |

四路图像必须为 `640×480`。采集端读取每条消息的 `encoding`，支持 `rgb8`、`bgr8`、
`rgba8`、`bgra8` 和 `mono8`，统一写为 RGB；尺寸或字节布局不符时拒绝该帧，不做静默缩放。

## 同步

左眼接收时间是 30Hz 数据集主时间轴；其余三路相机取 20ms 内最近帧。双臂和头部状态/动作
取 50ms 内最近帧。10Hz 夹爪状态采用主时间点之前 250ms 内的最近值保持，不向未来取样，
也不做虚构插值。所有判定使用工控机 `monotonic_ns` 接收时钟；ROS header 时间戳原样写入
审计列，零时间戳记为 `-1`。

数据集额外保留每个流的接收时间、来源时间以及夹爪原始 `0..100` 值。这些字段不参与模型
动作空间，但可在服务器审计同步质量和单位转换。

## 来源版本

URDF：`AM-DP123.urdf`，SHA256：
`0247596FEEEC4647B30BE10055B880CFD9E7AF15C2497766B43986957AE1B2E1`。

提供的 6.26 秒 MCAP 中没有四路相机和 command topic，因此它用于验证反馈消息定义及频率；
正式录制前，仪表盘仍必须显示所有十路输入已收到且未过期。

## 被动探测

加载 ROS2 Jazzy 和机器人消息工作空间后运行：

```bash
bash scripts/probe_ros2_contract.sh
```

脚本只执行 `ros2 topic list/type/info/hz`，不会发布任何消息。
