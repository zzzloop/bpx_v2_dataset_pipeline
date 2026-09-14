# 数据契约

## 数据集隔离

项目使用 LeRobot 内置元数据字段 `robot_type` 标识机器人本体或末端类型。但该字段不会自动
让不同的动作空间相互兼容，因此夹爪和灵巧手数据必须使用独立的 schema、数据集、归一化
统计和模型。

## 每次录制必须包含的元数据

- `attempt_id`：本机单调递增整数，分配后永不复用；
- `session_id`：本轮采集会话的 UUID；
- `task_en`：用于 VLA 训练的权威英文指令；
- `task_zh`：可选中文说明，不能在后台静默替换 `task_en`；
- `operator_id`：稳定且不直接暴露姓名的操作者编号；
- `layout_id`：可复现的场景或布局编号；
- `embodiment`：`gripper` 或 `dexterous_hand`；
- `status`：`recording`、`success`、`failure` 或 `interrupted`；
- `note` 和 `failure_reason`：可选备注和失败原因；
- 时间戳、软件版本和 schema 版本。

`attempt_id` 记录真实采集历史。例如第 5 次失败，重录必须使用第 6 号。训练数据发布时，
可以仅对通过筛选的 episode 重新生成连续的 `episode_index`，但不能改写原始
`attempt_id`。

## 已冻结的逐帧契约

每个通过验收的帧包最终应包含：

- 四路同步图像：左眼、右眼、左腕和右腕；
- 机器人实际关节反馈；
- 遥操作系统下发的目标动作；
- 单调递增的本机采集时间戳。

图像只允许在 ROS2 输入边界执行一次明确的颜色转换。四路均为 640×480、30FPS；具体
RGB/BGR 由消息 `encoding` 决定。训练状态和动作为 18D：左臂 7、右臂 7、头部 2、夹爪 2。
头部由 degree 转 rad，夹爪由 0..100 转 0..1。原始消息时间戳、工控机接收时间戳和夹爪
原始值一并写入 LeRobot 审计特征。详细顺序与同步策略见 `ros2-hardware-contract.md`。

## 语言指令规范

训练使用简短、准确的英文祈使句，例如：

```text
Pick up the red block and place it in the bucket.
```

英文通常更接近基础 VLA 模型的语言分布，因此作为权威训练文本；中文可作为便于团队查看的
辅助元数据。指令必须保留颜色、对象类别、数量和空间关系等真实属性。同一条轨迹不得随意
生成语义并不完全成立的改写。
