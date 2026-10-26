# BPX v2 Dataset Pipeline

**一代 ROS1 的最简数采入口现已单独提供：**
见 [一代ROS1数采说明](ros1_collector/README.md)，使用 `scripts/start_ros1_collector.sh`。
三路640×360、目标30Hz，保存一代18维state/action和独立MP4；不使用下文的ROS2环境或复杂页面。
二代ROS2入口保持不变，两代的数据集、映射和环境不能混用。

面向第二代半人型机器人的数据工程仓库。硬件契约已经冻结：四路 640×480@30Hz 图像、
双臂 14D、头部 2D 和双夹爪 2D。ROS2 Jazzy 后端只订阅数据，不创建任何机器人控制
publisher；成功示教直接保存为带 MP4 的 LeRobot v2.1 episode。

## 工程边界

```text
工控机 / ROS2 Jazzy
  Web UI -> Collector service -> CaptureBackend -> ROS2 Jazzy 纯订阅 adapter
                 |
                 +-> 单次 attempt 事务、状态数据库、LeRobot v2.1 MP4 episode

服务器
  入库审计 -> 按末端合并 -> 多进程毛刺扫描/清洗 -> 数据版本发布
                                              |
                                              +-> OpenPI 训练 + 在线视觉增强
                                              +-> HDF5/其他只读导出器
```

夹爪和灵巧手共用代码、网页和元数据规范，但使用独立的 `robot_type`、动作 schema、数据集、
归一化统计和模型：

- `bpx_v2_gripper`
- `bpx_v2_dexhand`

不要通过 padding 把两种末端强行放进同一个动作向量。

## 为什么失败重录不会覆盖编号

数据库维护单调递增的 `attempt_id`。开始录制即分配编号；无论成功、失败、手动中止或程序
崩溃，该编号都不会再次使用。例如 attempt 5 失败，下一次一定是 attempt 6。训练数据合并时
再给成功 episode 建立连续的 `episode_index`，二者互不混淆。

## 安装与运行

开发机运行测试：

```bash
uv sync --extra collector --extra server --extra dev
uv run pytest -q
```

启动无硬件模拟控制台：

```bash
uv run bpx-v2-collector --mock --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765`。模拟模式只验证交互与恢复逻辑，不发布机器人命令，也不生成
正式训练数据。

ROS2 Jazzy 工控机首次在线安装（只需一次）：

```bash
bash scripts/install_collector_once.sh
```

该脚本创建可读取系统 ROS2 包的 `.venv`，安装网页依赖，并把 LeRobot 固定到 OpenPI 当前
使用的 v2.1 commit。之后启动不使用 `uv run`，不会联网、解析或下载依赖：

```bash
# 自定义消息若位于机器人工作空间，填其 install/setup.bash
export BPX_ROBOT_SETUP=/path/to/robot_ws/install/setup.bash
bash scripts/start_collector.sh
```

默认数据目录为 `recordings/lerobot/bpx_v2_humanoid_raw`。可以用
`BPX_RECORDINGS_DIR=/data/...` 覆盖。正式模式只有四路相机、状态和 command 全部就绪后才允许
点击开始；触觉当前明确排除。

## 项目内 DeepSeek 翻译

中文自定义任务可通过 DeepSeek V4 Flash 翻译成简洁的英文 VLA 指令。密钥只从仓库根目录的
`.env.local` 读取，不读取或修改系统环境变量，也不会进入 Git：

```bash
cp .env.example .env.local
# 仅在 .env.local 中填写 DEEPSEEK_API_KEY
```

每次翻译都是独立的无状态请求，只发送固定翻译约束和当前一条中文任务；不会发送历史指令、
操作者、布局、备注或采集记录。标准预设和可确定的常见表达优先使用本地规则，不消耗 API。
模型翻译仍必须由操作者核对英文并勾选确认后才能开始录制。

点击“结束并标记失败”会立即停止录制并将 attempt 落库为失败，随后才显示可选的失败原因。
原因可以保存或跳过，不会延长录制；成功或中断记录的失败原因由数据库强制为空。
“中断录制并作废本条”同样会立即停止，但状态记为 `interrupted`，保留审计记录和不会复用的
attempt 编号，不作为成功训练 episode 使用。

详细设计见 [architecture.md](docs/architecture.md)、[data-contract.md](docs/data-contract.md) 和
[operations.md](docs/operations.md)。正式 Topic、单位、同步策略及 URDF 校验值见
[ros2-hardware-contract.md](docs/ros2-hardware-contract.md)。
