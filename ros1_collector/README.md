# 一代 ROS1：最简 LeRobot + MP4 数采

这是**一代 ROS Noetic 的独立入口**，不使用项目原有 ROS2 页面，不导入 ROS2、不改变原来的推理控制台。
只保留：任务指令、开始录制、停止并保存、丢弃本条。无翻译、训练控制或电机控制功能。

## 1. 工控机下载与首次安装

硬件同学仍按原方式启动 ROS master、相机、关节反馈和遥操程序；本程序只订阅，绝不发布指令。
**不需要启动 OpenPI 推理服务或策略，不需要启动/使能 eyou。** 遥操的实际 command 必须持续发布。

```bash
cd /home/nvidia/ROS
git clone https://github.com/zzzloop/bpx_v2_dataset_pipeline.git
cd bpx_v2_dataset_pipeline

# 首次缺少这两个系统组件时安装一次，不需要则跳过
sudo apt-get install python3-venv ffmpeg

bash scripts/install_ros1_collector_once.sh
```

已经 clone 过则进入原项目目录执行 `git pull --ff-only origin main`，不要再 clone 第二份。
安装只创建本项目 `.venv-ros1`，不修改 ROS/系统 Python，不碰二代 `.venv`，也不安装 OpenPI、torch 或 JAX。
使用 ROS1 对应的 `/usr/bin/python3`（一代目前 Python 3.8）；不在一代上执行二代的 `uv sync`。
NumPy/Arrow 用预编译 wheel；没有匹配 wheel 时明确失败，不偷偷开始长时间源码编译。

为避免旧 Python 无法安装当前 LeRobot SDK，写入器直接遵循 OpenPI 锁定的
[LeRobot v2.1 格式源码](https://github.com/huggingface/lerobot/tree/0cf864870cf29f4738d3ade893e6fd13fbd7cdb5/lerobot/common/datasets)。
这是标准磁盘格式，不是自定义视频包；服务器另有真正的 LeRobot SDK 读取验证入口。

## 2. 每次启动

```bash
cd /home/nvidia/ROS/bpx_v2_dataset_pipeline
bash scripts/start_ros1_collector.sh
```

打开 **http://127.0.0.1:8766**。启动完全离线，不解析或下载依赖。ROS master不可达时会明确退出，不一直卡在连接重试。
需要额外工作空间环境时，可先 source 它的 devel/setup.bash，或设置 BPX_ROBOT_SETUP 指向该文件。
本程序只用标准 sensor_msgs，不依赖一代的自定义驱动包。

远程查看时在自己的电脑终端建立 SSH 转发：

```bash
ssh -N -L 18766:127.0.0.1:8766 nvidia@工控机IP
```

打开 http://127.0.0.1:18766 即可；不向公网开放采集接口。

## 3. 录制

1. 看“话题就绪状态”确认输入有消息。填写本轮英文任务，后续多条自动沿用，空闲时可以改。
2. 点“开始录制”，再进行遥操示教；录完整的一次任务，包含接近、抓取、放置和结束。
3. 点“停止并保存”：立即停止取样，在后台关闭 MP4、检查帧数、写 Parquet 和元数据。
4. 等待回到“空闲”，再录下一条。失败示教点“丢弃本条”，只删除这一条未保存的临时数据。

不需要每次新建目录。成功保存的 episode 连续编号，绝不覆盖旧 episode。每次尝试另有 UUID，失败重录不会覆盖原尝试。
保存失败的条目不进入正式元数据；部分写入发生中断时，已校验完成的事务在下次启动恢复。
没有完成校验的中断文件留在数据集 `.bpx_pending`，不会当作训练数据读取。
同一数据集有排他锁，不能同时启动两份录制器。**不要一边向同一目录采集、一边训练；先停止采集并复制快照。**

## 4. 频率、图像与同步

- **目标 30Hz，三路 RGB 图像 640×360，不裁剪、不拉伸、不缩放。** 自动识别 rgb8/bgr8，并处理行填充。
- 三路相机每条消息最多使用一次；以左眼为锚，在接收时钟上匹配腕部相机（默认最大偏差40ms）。
- 状态与动作采用锚点之前最新的有效消息，默认最多150ms，不用未来值，不以反馈冒充 action。
- 常规视频与 LeRobot timestamp 为 `frame_index/30`，便于现有训练按30Hz读取；**实际取样时间另行逐帧保留**。
- 不复制旧图像伪造30Hz。页面显示真实有效采样率，保存报告保留真实时间间隔；默认允许27–33Hz这一近30Hz范围，低于28/高于32会额外提示。
- 帧间断超过100ms、输入持续缺失、编码阻塞或保存时频率不合格，会拒绝将本条作为正常训练 episode 发布。只影响采集，不停止机器人。
- “接收时钟配对”不是硬件曝光同步。`bpx.source_time_ns` 和 `bpx.receive_time_ns` 保留每路真实时间，供后续审计。
- MP4 为 H.264/yuv420p、CRF18，有损压缩；不声称像素逐点无损。编码限制每路2线程，避免抢占遥操全部CPU。

采集和硬件仍共享CPU/磁盘，首次短录制时请观察遥操和相机频率。这里不承诺对硬件调度零影响。

默认配置在 `ros1_collector/config.json`。只需在硬件话题变动时修改 topics；不要套用二代的头部角度/夹爪百分比规则。

## 5. 一代训练契约

| 输入 | 消息类型 | 长度/含义 |
|---|---|---|
| `/data/left_eye_image` | sensor_msgs/Image | 640×360，rgb8或bgr8 |
| `/data/left_wrist_image` | sensor_msgs/Image | 同上 |
| `/data/right_wrist_image` | sensor_msgs/Image | 同上 |
| `/feedback_damiao_joint_states` | sensor_msgs/JointState | position固定8维 |
| `/feedback_feetech_joint_states` | sensor_msgs/JointState | position固定10维 |
| `/command_joint_states` | sensor_msgs/JointState | 原真机21电机顺序；不订阅策略的内部32维张量 |

双臂和头部关节沿用一代反馈/控制桥的弧度值。记录顺序是：

```text
左臂7 + 左夹爪1 + 右臂7 + 右夹爪1 + 头部2 = 18
```

与现有一代 `BpxInputs` 的 effective18 顺序一致，**不是二代的 arm14 + head2 + gripper2 顺序**。
夹爪沿用旧训练数据两指槽位之和：`0.08 - 电机角度 / 0.8923 × 0.08`，单位为旧数据的米制1DoF值。
这个量不能直接与二代0–100或0–1夹爪值混用，也不要重新解释成另一种夹爪宽度定义。
action 保存绝对关节目标；需要的 delta 转换仍由训练 transforms 处理，采集器不提前做差分、不平滑或裁限。
不采腰部/eyou，腰部不进入有效18维。另存原始电机反馈与原始21维命令，便于核对映射。

## 6. 输出与服务器验证

默认保存位置：

```text
/home/nvidia/ROS/bpx_v2_dataset_pipeline/recordings/lerobot/bpx_v1_humanoid_raw/
  meta/info.json                 # codebase_version=v2.1，fps=30
  meta/tasks.jsonl               # 任务文本与task_index
  meta/episodes.jsonl
  meta/episodes_stats.jsonl
  meta/bpx_capture.jsonl          # 实际Hz、最大间隔、配置、尝试ID
  data/chunk-000/episode_000000.parquet
  videos/chunk-000/observation.images.left_eye/episode_000000.mp4
  videos/chunk-000/observation.images.left_wrist/episode_000000.mp4
  videos/chunk-000/observation.images.right_wrist/episode_000000.mp4
```

可以用启动参数 `--output-dir /其他盘/新数据集目录` 修改输出；不允许往非本采集器创建的已有数据集硬追加。
无逐帧PNG缓存，不在Parquet内嵌图像。Parquet保存state/action、索引和诊断时间，视频独立保存。
内置LeRobot图像统计是对每30个采集帧抽1帧做真实RGB统计，和官方v2.1采样统计同类；不改变保存的图像。
**这些不是 OpenPI 的 norm_stats.json**，训练前仍需用训练集重新计算归一化。

先录一条10秒左右的短样本，拷贝完整目录到服务器 `/scratch/bpx_datasets/lerobot/bpx/bpx_v1_humanoid_raw`。
服务器拉取本仓库代码，然后借用原来 OpenPI 环境执行真正的LeRobot读取校验：

```bash
cd ~/zzk_data/bpx_v2_dataset_pipeline
~/zzk_data/openpi-bpx-pi05-finetune/.venv/bin/python -m ros1_collector.validate \
  /scratch/bpx_datasets/lerobot/bpx/bpx_v1_humanoid_raw
```

这里 `cd` 是为了读取**采集仓库的校验脚本**，并没有把训练项目搬到采集仓库。
看到 `LEROBOT V2.1 READ/VIDEO PASS` 才确认服务器SDK实际能读取该批样本。校验每条Parquet与首/中/末视频帧，不是假装完成全帧内容审查。
后续复用服务器仪表盘的审计和毛刺扫描；训练配置 repo_id 需要绑定 `bpx/bpx_v1_humanoid_raw`，再计算新归一化后训练。
数据结构兼容一代映射，不等于可以让旧配置继续读取另一个旧数据集却声称在训练新数据。

本地遵照用户要求未运行测试、未安装环境、未连接机器人。回归规格在 `ros1_collector/test_contract.py`；
可在服务器执行 `.venv/bin/python -m pytest /采集仓库/ros1_collector/test_contract.py -q`，先验证映射和同步逻辑，再做真机短录制。
