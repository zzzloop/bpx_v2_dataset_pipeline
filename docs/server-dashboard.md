# 服务器数据工程与训练仪表盘

## 定位

服务器仪表盘是实时操作界面，不替代命令行，也不修改 OpenPI 的训练实现。它只通过经过校验的
参数数组启动以下固定任务：

1. LeRobot 数据集只读审计；
2. 毛刺扫描以及生成独立清洗版本；
3. OpenPI 全量归一化统计；
4. LeRobot v2.1 视频数据集导出为 episode HDF5；
5. OpenPI 新训练或断点续训。

界面不提供任意 Shell 输入框。训练参数会被结构化验证，例如 CUDA 设备数必须与 FSDP 设备数
一致，global batch 必须能被 FSDP 设备数整除，`overwrite` 与 `resume` 互斥。

审计的视频检查分三级：`none` 只核对模板对应的 MP4 路径集合；`headers`（默认）逐个打开容器并
核对视频流、分辨率和 FPS；`full` 进一步解码全部视频帧并逐 episode 核对帧数。正式发布数据集
时应至少执行一次 `full`，日常快速复审可使用 `headers`。

## 安装与启动

在 `bpx_v2_dataset_pipeline` 仓库中：

```bash
uv sync --extra server --extra dev

uv run bpx-v2-server \
  --host 127.0.0.1 \
  --port 8866 \
  --state-dir state \
  --openpi-root ../openpi-bpx-pi05-finetune
```

启动日志会打印带随机控制令牌的网页地址。服务默认只监听回环地址；从另一台电脑访问时建议
使用 SSH 端口转发，而不是把可启动训练的接口直接暴露到局域网：

```bash
ssh -L 8866:127.0.0.1:8866 <server-user>@<server-host>
```

然后在本机打开服务打印的 `http://127.0.0.1:8866/?token=...`。令牌只保存在
`state/.server-token`，权限设为当前用户可读写。

## 任务持久化与恢复

每次任务的数据位于 `state/server_jobs/<job-id>/`：

- `job.json`：状态、PID、受控命令、进度和最新指标；
- `spec.json`：不含密钥的参数数组、工作目录和数据路径环境变量；
- `job.log`：完整标准输出和错误输出；
- `metrics.jsonl`：从 OpenPI `Step N` 日志提取的训练指标；
- `exit.json`：独立 runner 原子写入的退出码。

runner 以独立进程组运行。仪表盘重启后，如果 runner 仍然存在，会重新监视同一任务；已完成
任务从 `exit.json` 恢复。为避免多次归一化、磁盘导出和训练互相争抢 IO/GPU，当前默认同一
时间只运行一个重任务。

## 归一化

界面执行的核心命令等价于：

```bash
uv run scripts/compute_norm_stats.py \
  --config-name <config-name> \
  --num-workers 32
```

默认 `32` workers 可修改。该参数只影响 DataLoader 并行读取，不更改帧集合、数据变换、
batch size 或 RunningStats 算法。仪表盘不会添加 `--max-frames`，因此默认计算全部训练帧。

## 训练

训练页面显式记录 CUDA 编号、XLA 显存比例、global batch、总 steps、FSDP 设备数、checkpoint
目录、保存间隔和长期保留间隔。选择 `resume` 时仅把 `--overwrite` 替换为 `--resume`；其他
参数仍取页面当前值，操作者必须保证它们与原实验一致。

页面解析 OpenPI 的定期日志并显示：

- 当前 step 和完成比例；
- loss、gradient norm 和 learning rate；
- loss 曲线；
- gradient/update norm 曲线；
- 完整日志和实际受控命令；
- GPU 显存、利用率、温度以及目标磁盘剩余容量。

`HF_LEROBOT_HOME`、`HF_HOME`、`HF_DATASETS_CACHE`、`TMPDIR` 和 `UV_CACHE_DIR` 均可在运行环境
区域配置，并和 CUDA/XLA 参数一起显示在任务的“本次受控命令”中，便于复现实验并避免系统盘
被缓存占满。

OpenPI 自身产生的 checkpoint、监控图和 W&B 数据仍由 OpenPI 配置负责，仪表盘不改写这些
产物。

## HDF5 派生导出

HDF5 导出只支持已经转为 MP4-backed 的 LeRobot v2.1 数据集。每个 episode 写出一个文件：

```text
episode_000000.hdf5
├── action
└── observations
    ├── qpos
    ├── timestamp
    └── images/<camera>
```

视频逐帧流式解码，避免把四路完整 episode 同时载入内存。导出目录通过 `.partial` 暂存后
原子发布，并包含记录每个文件 SHA-256、字节数、帧数和任务文本的 `manifest.json`。
LeRobot 权威源始终只读；导出目录已存在时任务会拒绝覆盖。
