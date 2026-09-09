const token = new URLSearchParams(location.search).get("token") || sessionStorage.getItem("bpx.serverToken") || "";
sessionStorage.setItem("bpx.serverToken", token);
const el = (id) => document.getElementById(id);
const activeStatuses = new Set(["queued", "running", "cancelling"]);
const persisted = ["openpiRoot", "hfLerobotHome", "checkpointRoot", "hfHome", "hfDatasetsCache", "tmpdir", "uvCacheDir", "auditDataset", "auditReport", "auditWorkers", "auditVideoCheck", "spikeSource", "thresholdsPath", "spikeReport", "cleanOutput", "spikeWorkers", "normConfig", "normWorkers", "exportSource", "exportOutput", "exportWorkers", "exportCompression", "compressionLevel", "trainConfig", "expName", "cudaDevices", "memoryFraction", "batchSize", "fsdpDevices", "trainSteps", "saveInterval", "keepPeriod", "trainMode"];
let jobs = [];
let selectedJobId = null;
let toastTimer = null;

for (const id of persisted) {
  const saved = localStorage.getItem(`bpx.server.${id}`);
  if (saved !== null) el(id).value = saved;
  el(id).addEventListener("input", () => localStorage.setItem(`bpx.server.${id}`, el(id).value));
}

for (const button of document.querySelectorAll(".tabs button")) {
  button.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === button.dataset.tab));
  };
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "X-BPX-Token": token, ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function notify(message) {
  el("toast").textContent = message;
  el("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el("toast").classList.remove("show"), 4200);
}

function envPayload() {
  return {
    openpi_root: el("openpiRoot").value,
    hf_lerobot_home: el("hfLerobotHome").value,
    hf_home: el("hfHome").value,
    hf_datasets_cache: el("hfDatasetsCache").value,
    tmpdir: el("tmpdir").value,
    uv_cache_dir: el("uvCacheDir").value,
  };
}

async function startJob(path, payload) {
  try {
    const job = await request(path, { method: "POST", body: JSON.stringify(payload) });
    selectedJobId = job.id;
    notify(`任务 ${job.id} 已启动`);
    await refreshJobs();
  } catch (error) {
    notify(error.message);
  }
}

el("startAudit").onclick = () => startJob("/api/jobs/audit", {
  dataset_root: el("auditDataset").value,
  report_path: el("auditReport").value,
  workers: Number(el("auditWorkers").value),
  video_check: el("auditVideoCheck").value,
});
el("scanSpikes").onclick = () => startJob("/api/jobs/spikes/scan", {
  source_root: el("spikeSource").value,
  thresholds_path: el("thresholdsPath").value,
  report_path: el("spikeReport").value,
  output_root: el("cleanOutput").value,
  workers: Number(el("spikeWorkers").value),
});
el("cleanSpikes").onclick = () => startJob("/api/jobs/spikes/clean", {
  source_root: el("spikeSource").value,
  thresholds_path: el("thresholdsPath").value,
  report_path: el("spikeReport").value,
  output_root: el("cleanOutput").value,
  workers: Number(el("spikeWorkers").value),
});
el("startNormalize").onclick = () => startJob("/api/jobs/normalize", {
  ...envPayload(), config_name: el("normConfig").value, workers: Number(el("normWorkers").value),
});
el("startExport").onclick = () => startJob("/api/jobs/export/hdf5", {
  source_root: el("exportSource").value,
  output_root: el("exportOutput").value,
  workers: Number(el("exportWorkers").value),
  compression: el("exportCompression").value,
  compression_level: Number(el("compressionLevel").value),
});
el("startTrain").onclick = () => startJob("/api/jobs/train", {
  ...envPayload(),
  config_name: el("trainConfig").value,
  exp_name: el("expName").value,
  checkpoint_base_dir: el("checkpointRoot").value,
  cuda_devices: el("cudaDevices").value,
  memory_fraction: Number(el("memoryFraction").value),
  batch_size: Number(el("batchSize").value),
  fsdp_devices: Number(el("fsdpDevices").value),
  num_train_steps: Number(el("trainSteps").value),
  save_interval: Number(el("saveInterval").value),
  keep_period: Number(el("keepPeriod").value),
  mode: el("trainMode").value,
});

function formatBytes(value) {
  if (!Number.isFinite(value)) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(amount >= 100 ? 0 : 1)} ${units[unit]}`;
}

async function refreshSystem() {
  try {
    const path = el("checkpointRoot").value;
    const data = await request(`/api/system?path=${encodeURIComponent(path)}`);
    const disk = data.disk;
    if (disk.error) {
      el("diskUsage").textContent = "路径不可用";
      el("diskMeter").style.width = "0";
    } else {
      const percent = disk.total ? (100 * disk.used / disk.total) : 0;
      el("diskUsage").textContent = `${formatBytes(disk.free)} 可用 · ${percent.toFixed(1)}% 已用`;
      el("diskMeter").style.width = `${percent}%`;
    }
    el("gpuGrid").replaceChildren(...(data.gpus.length ? data.gpus.map((gpu) => {
      const card = document.createElement("div");
      card.className = "gpu-card";
      card.innerHTML = `<div><strong>GPU ${gpu.index} · ${gpu.name}</strong><span>${gpu.temperature_c}°C</span></div><div><span>显存 ${gpu.memory_used_mib} / ${gpu.memory_total_mib} MiB</span><span>利用率 ${gpu.utilization_percent}%</span></div>`;
      return card;
    }) : [Object.assign(document.createElement("p"), { className: "muted", textContent: "未检测到 nvidia-smi" })]));
  } catch (error) { notify(error.message); }
}

function jobLabel(kind) {
  return ({ audit: "数据审计", spike_scan: "毛刺扫描", spike_clean: "毛刺清洗", normalize: "归一化", hdf5_export: "HDF5 导出", train: "模型训练" })[kind] || kind;
}

function renderJobs() {
  const list = el("jobList");
  if (!jobs.length) {
    list.innerHTML = '<p class="muted">暂无任务</p>';
    return;
  }
  list.replaceChildren(...jobs.map((job) => {
    const button = document.createElement("button");
    button.className = `job-item ${job.id === selectedJobId ? "active" : ""}`;
    button.innerHTML = `<header><strong>${jobLabel(job.kind)}</strong><span class="job-state ${job.status}">${job.status}</span></header><small>${job.id} · ${job.created_at.slice(0,19).replace("T"," ")}</small>`;
    button.onclick = () => { selectedJobId = job.id; renderJobs(); renderSelected(); };
    return button;
  }));
}

function number(value) {
  return Number.isFinite(Number(value)) ? Number(value).toExponential(3) : "—";
}

function drawChart(svg, points, keys) {
  svg.replaceChildren();
  const width = 620, height = 180, pad = 18;
  for (let i = 0; i <= 4; i += 1) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", pad); line.setAttribute("x2", width - pad);
    line.setAttribute("y1", pad + i * (height - 2 * pad) / 4); line.setAttribute("y2", pad + i * (height - 2 * pad) / 4);
    line.setAttribute("class", "chart-grid"); svg.appendChild(line);
  }
  const series = keys.map((key) => points.map((point) => [point.current, point.metrics?.[key]]).filter((pair) => Number.isFinite(pair[1])));
  const all = series.flat();
  if (!all.length) return;
  const xs = all.map((item) => item[0]), ys = all.map((item) => item[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const scaleX = (x) => pad + (x - minX) / Math.max(1, maxX - minX) * (width - 2 * pad);
  const scaleY = (y) => height - pad - (y - minY) / Math.max(Number.EPSILON, maxY - minY) * (height - 2 * pad);
  series.forEach((values, index) => {
    if (!values.length) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", values.map((item, i) => `${i ? "L" : "M"}${scaleX(item[0]).toFixed(2)},${scaleY(item[1]).toFixed(2)}`).join(" "));
    path.setAttribute("class", `chart-line ${index ? "secondary" : ""}`); svg.appendChild(path);
  });
}

async function renderSelected() {
  const job = jobs.find((item) => item.id === selectedJobId);
  if (!job) return;
  el("selectedKind").textContent = job.kind.toUpperCase();
  el("selectedTitle").textContent = `${jobLabel(job.kind)} · ${job.id}`;
  const progress = job.progress || {};
  const percent = Number(progress.percent || 0);
  el("progressText").textContent = `${progress.current || 0} / ${progress.total || "—"}`;
  el("progressPercent").textContent = `${percent.toFixed(1)}%`;
  el("progressBar").style.width = `${Math.min(100, percent)}%`;
  el("metricLoss").textContent = number(job.metrics?.loss);
  el("metricGrad").textContent = number(job.metrics?.grad_norm);
  el("metricLr").textContent = number(job.metrics?.learning_rate);
  el("metricStatus").textContent = job.status;
  const environment = Object.entries(job.environment || {}).map(([key, value]) => `${key}=${value}`).join(" \\\n  ");
  el("commandText").textContent = `cd ${job.cwd}\n${environment ? `${environment} \\\n  ` : ""}${job.command}`;
  el("cancelJob").hidden = !activeStatuses.has(job.status);
  try {
    const [log, metrics] = await Promise.all([request(`/api/jobs/${job.id}/log`), request(`/api/jobs/${job.id}/metrics`)]);
    el("jobLog").textContent = log.text || "任务尚未输出日志。";
    el("jobLog").scrollTop = el("jobLog").scrollHeight;
    drawChart(el("lossChart"), metrics, ["loss"]);
    drawChart(el("normChart"), metrics, ["grad_norm", "update_norm"]);
  } catch (error) { notify(error.message); }
}

async function refreshJobs() {
  try {
    jobs = await request("/api/jobs");
    if (!selectedJobId && jobs.length) selectedJobId = jobs[0].id;
    renderJobs();
    await renderSelected();
    el("connection").className = "status-pill good";
    el("connection").innerHTML = "<i></i>服务在线";
  } catch (error) {
    el("connection").className = "status-pill bad";
    el("connection").innerHTML = "<i></i>连接失败";
  }
}

el("cancelJob").onclick = async () => {
  if (!selectedJobId || !confirm("确认终止当前任务？已写入的数据不会自动删除。")) return;
  try { await request(`/api/jobs/${selectedJobId}/cancel`, { method: "POST" }); await refreshJobs(); } catch (error) { notify(error.message); }
};
el("refreshJobs").onclick = refreshJobs;
el("refreshSystem").onclick = refreshSystem;

async function initialize() {
  try {
    const config = await request("/api/config");
    if (!el("openpiRoot").value && config.default_openpi_root) el("openpiRoot").value = config.default_openpi_root;
  } catch (error) { notify(error.message); }
  await Promise.all([refreshJobs(), refreshSystem()]);
}

setInterval(() => { el("clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false }); }, 1000);
setInterval(refreshJobs, 1500);
setInterval(refreshSystem, 15000);
initialize();
