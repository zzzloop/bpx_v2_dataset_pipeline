const el = (id) => document.getElementById(id);
const persistentFields = ["taskEn", "taskZh", "operator", "layout", "embodiment", "note"];
const sessionId = localStorage.getItem("bpx.sessionId") || crypto.randomUUID();
let recording = false;
let finishing = false;
let pendingFailedAttemptId = null;
let catalog = { tasks: [], operators: [], layouts: [] };

localStorage.setItem("bpx.sessionId", sessionId);
el("sessionShort").textContent = sessionId.slice(0, 8);

function persist(id) {
  localStorage.setItem(`bpx.${id}`, el(id).value);
}

for (const id of persistentFields) {
  const saved = localStorage.getItem(`bpx.${id}`);
  if (saved !== null) el(id).value = saved;
  el(id).addEventListener("input", () => {
    persist(id);
    updateControls();
  });
}

function setTask(zh, en, message = "已载入标准双语任务，请确认英文后开始录制。") {
  el("taskZh").value = zh;
  el("taskEn").value = en;
  persist("taskZh");
  persist("taskEn");
  el("taskConfirmed").checked = false;
  setTranslationStatus(message, "good");
  updateControls();
}

function setTranslationStatus(message, tone) {
  const status = el("translationStatus");
  status.textContent = message;
  status.className = `translation-status ${tone}`;
}

function savedOptions(kind) {
  try {
    return JSON.parse(localStorage.getItem(`bpx.${kind}History`) || "[]");
  } catch (_error) {
    return [];
  }
}

function rememberOption(kind, value) {
  const clean = value.trim();
  if (!clean) return;
  const values = [clean, ...savedOptions(kind).filter((item) => item !== clean)].slice(0, 30);
  localStorage.setItem(`bpx.${kind}History`, JSON.stringify(values));
  renderOptions(kind, catalog[`${kind}s`] || []);
}

function renderOptions(kind, serverValues) {
  const values = [...new Set([...savedOptions(kind), ...serverValues])];
  const list = el(`${kind}Options`);
  list.replaceChildren(...values.map((value) => {
    const option = document.createElement("option");
    option.value = value;
    return option;
  }));
}

async function request(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function renderCatalog() {
  const select = el("taskPreset");
  const first = select.firstElementChild;
  const groups = new Map();
  for (const task of catalog.tasks) {
    if (!groups.has(task.category)) groups.set(task.category, []);
    groups.get(task.category).push(task);
  }
  const children = [first];
  for (const [category, tasks] of groups) {
    const group = document.createElement("optgroup");
    group.label = category;
    for (const task of tasks) {
      const option = document.createElement("option");
      option.value = task.id;
      option.textContent = `${task.zh}  /  ${task.en}`;
      group.appendChild(option);
    }
    children.push(group);
  }
  select.replaceChildren(...children);

  el("presetGrid").replaceChildren(...catalog.tasks.slice(0, 6).map((task) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset-chip";
    button.textContent = task.zh.replace("。", "");
    button.onclick = () => {
      select.value = task.id;
      setTask(task.zh, task.en);
    };
    return button;
  }));
  renderOptions("operator", catalog.operators);
  renderOptions("layout", catalog.layouts);
  const translator = catalog.translator || {};
  el("translatorInfo").textContent = translator.enabled
    ? `${translator.model} · 无历史上下文`
    : "本地规则 · DeepSeek 未配置";
}

async function loadCatalog() {
  try {
    catalog = await request("/api/catalog");
    renderCatalog();
  } catch (error) {
    el("message").textContent = `任务目录加载失败：${error.message}`;
  }
}

el("taskPreset").addEventListener("change", () => {
  const task = catalog.tasks.find((item) => item.id === el("taskPreset").value);
  if (task) setTask(task.zh, task.en);
});

el("translate").onclick = async () => {
  try {
    const result = await request("/api/translate", { chinese: el("taskZh").value });
    if (!result.english) {
      setTranslationStatus("该表达不在本地规则范围内。请人工填写英文，或选择上方标准任务。", "warn");
      el("taskEn").focus();
      return;
    }
    el("taskEn").value = result.english;
    persist("taskEn");
    el("taskConfirmed").checked = false;
    const labels = {
      high: "标准任务精确匹配",
      medium: "本地模板翻译",
      model: "DeepSeek V4 Flash 单次翻译",
    };
    const label = labels[result.confidence] || "翻译完成";
    setTranslationStatus(`${label}：请核对右侧英文，确认后方可录制。`, result.confidence === "high" ? "good" : "warn");
    updateControls();
  } catch (error) {
    setTranslationStatus(error.message, "bad");
  }
};

for (const id of ["taskEn", "taskZh"]) {
  el(id).addEventListener("input", () => {
    el("taskConfirmed").checked = false;
    setTranslationStatus("任务文字已修改，请重新确认英文语义。", "neutral");
    updateControls();
  });
}
el("taskConfirmed").addEventListener("change", updateControls);

function formProblems() {
  const problems = [];
  if (!el("taskEn").value.trim()) problems.push("英文任务");
  if (!el("operator").value.trim()) problems.push("操作者编号");
  if (!el("layout").value.trim()) problems.push("场景布局编号");
  if (!el("taskConfirmed").checked) problems.push("英文确认");
  return problems;
}

function updateControls() {
  const problems = formProblems();
  el("start").disabled = recording || finishing || pendingFailedAttemptId !== null || problems.length > 0;
  el("success").disabled = !recording || finishing;
  el("failure").disabled = !recording || finishing;
  el("discard").disabled = !recording || finishing;
  el("formHint").textContent = recording
    ? "正在录制：请根据结果选择成功或失败。"
    : problems.length ? `还需完成：${problems.join("、")}` : "信息完整，可以开始新的录制。";
}

function statusLabel(status) {
  const labels = { recording: "录制中", success: "成功", failure: "失败", interrupted: "中断" };
  return labels[status] || status;
}

async function refresh() {
  try {
    const state = await request("/api/status");
    recording = state.mode === "recording";
    el("mode").textContent = recording ? "正在录制" : "等待录制";
    el("modeDot").className = recording ? "live" : "";
    el("backend").textContent = state.backend;
    el("attemptNumber").textContent = recording ? `#${state.active_attempt.attempt_id}` : "—";
    el("frameCount").textContent = recording ? state.active_attempt.frame_count.toLocaleString() : "0";
    el("attempts").replaceChildren(...state.recent_attempts.map((item) => {
      const row = document.createElement("tr");
      const values = [item.attempt_id, item.status, item.task_en, item.operator_id, item.layout_id, item.embodiment];
      for (const [index, value] of values.entries()) {
        const cell = document.createElement("td");
        if (index === 1) {
          const badge = document.createElement("span");
          badge.className = `status-badge ${value}`;
          badge.textContent = statusLabel(value);
          cell.appendChild(badge);
        } else {
          cell.textContent = value;
        }
        row.appendChild(cell);
      }
      return row;
    }));
    updateControls();
  } catch (error) {
    el("message").textContent = `服务连接失败：${error.message}`;
    el("mode").textContent = "连接失败";
    el("modeDot").className = "fault";
  }
}

el("start").onclick = async () => {
  try {
    rememberOption("operator", el("operator").value);
    rememberOption("layout", el("layout").value);
    const result = await request("/api/attempts/start", {
      task_en: el("taskEn").value,
      task_zh: el("taskZh").value,
      operator_id: el("operator").value,
      layout_id: el("layout").value,
      embodiment: el("embodiment").value,
      note: el("note").value,
      session_id: sessionId,
    });
    el("message").textContent = `attempt ${result.attempt_id} 已开始录制。`;
    await refresh();
  } catch (error) {
    el("message").textContent = error.message;
  }
};

async function finish(status) {
  finishing = true;
  updateControls();
  try {
    const result = await request("/api/attempts/finish", {
      status,
      failure_reason: "",
      note: el("note").value,
    });
    if (status === "failure") {
      pendingFailedAttemptId = result.attempt_id;
      setFailurePanel(true);
      el("message").textContent = `attempt ${result.attempt_id} 已立即停止并标记为失败；失败原因可选。`;
    } else {
      el("message").textContent = `attempt ${result.attempt_id} 已标记为${statusLabel(result.status)}。`;
      setFailurePanel(false);
    }
    await loadCatalog();
    await refresh();
  } catch (error) {
    el("message").textContent = error.message;
  } finally {
    finishing = false;
    updateControls();
  }
}

el("success").onclick = () => finish("success");
el("discard").onclick = () => finish("interrupted");
function setFailurePanel(open) {
  el("failurePanel").hidden = !open;
  el("failureReason").disabled = !open;
  if (open) el("failureReason").focus();
}

el("failure").onclick = () => finish("failure");
el("confirmFailure").onclick = async () => {
  if (pendingFailedAttemptId === null) return;
  try {
    await request("/api/attempts/failure-reason", {
      attempt_id: pendingFailedAttemptId,
      failure_reason: el("failureReason").value,
    });
    el("message").textContent = `attempt ${pendingFailedAttemptId} 的失败原因已保存。`;
    pendingFailedAttemptId = null;
    el("failureReason").value = "";
    setFailurePanel(false);
    await refresh();
  } catch (error) {
    el("message").textContent = error.message;
  }
};
el("cancelFailure").onclick = () => {
  pendingFailedAttemptId = null;
  el("failureReason").value = "";
  setFailurePanel(false);
  updateControls();
};
loadCatalog();
refresh();
setInterval(refresh, 1000);
