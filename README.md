# BPX v2 Dataset Pipeline

面向第二代半人型机器人的数据工程仓库。当前版本先固定工程边界、元数据契约、故障恢复、
网页工作流、数值毛刺算法和在线视觉增强；ROS2 topic、关节顺序、动作维度和相机规格等硬件
契约明确后，再增加真机 adapter 与正式 LeRobot writer。

## 工程边界

```text
工控机 / ROS2 Jazzy
  Web UI -> Collector service -> CaptureBackend -> ROS2 adapter（待硬件契约）
                 |
                 +-> 单次 attempt 事务、状态数据库、LeRobot episode shard

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

## 当前可运行内容

安装开发环境：

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

## 尚需硬件组提供的契约

正式 ROS2 adapter 开发前必须冻结：

1. 四路图像 topic、message type、encoding、分辨率、帧率和 QoS；
2. qpos 与遥操 action 的 topic、message type、关节名称、顺序、单位和时间戳来源；
3. 夹爪及因时灵巧手分别的动作维度、反馈维度、耦合关系与有效范围；
4. 同步容差、掉帧规则、episode 开始/结束定义；
5. URDF/SRDF 与标定文件版本（用于名字、范围和未来 FK/仿真验证）；
6. 是否保留可选的 ROS2 MCAP 影子记录作为原始证据。

详细设计见 [architecture.md](docs/architecture.md)、[data-contract.md](docs/data-contract.md) 和
[operations.md](docs/operations.md)。
