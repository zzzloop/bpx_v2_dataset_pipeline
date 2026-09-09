const el = (id) => document.getElementById(id);
const persistentFields = ["taskEn", "taskZh", "operator", "layout", "embodiment", "note"];
const sessionId = localStorage.getItem("bpx.sessionId") || crypto.randomUUID();
localStorage.setItem("bpx.sessionId", sessionId);

for (const id of persistentFields) {
  const saved = localStorage.getItem(`bpx.${id}`);
  if (saved !== null) el(id).value = saved;
  el(id).addEventListener("input", () => localStorage.setItem(`bpx.${id}`, el(id).value));
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

async function refresh() {
  try {
    const state = await request("/api/status");
    const recording = state.mode === "recording";
    el("mode").textContent = state.mode.toUpperCase();
    el("backend").textContent = `backend: ${state.backend}`;
    el("counter").textContent = recording ? `attempt ${state.active_attempt.attempt_id} · ${state.active_attempt.frame_count} frames` : "";
    el("start").disabled = recording;
    el("success").disabled = !recording;
    el("failure").disabled = !recording;
    el("attempts").replaceChildren(...state.recent_attempts.map((item) => {
      const row = document.createElement("tr");
      for (const key of ["attempt_id", "status", "task_en", "operator_id", "layout_id", "embodiment"]) {
        const cell = document.createElement("td");
        cell.textContent = item[key];
        row.appendChild(cell);
      }
      return row;
    }));
  } catch (error) {
    el("message").textContent = error.message;
  }
}

el("start").onclick = async () => {
  try {
    const result = await request("/api/attempts/start", {
      task_en: el("taskEn").value,
      task_zh: el("taskZh").value,
      operator_id: el("operator").value,
      layout_id: el("layout").value,
      embodiment: el("embodiment").value,
      note: el("note").value,
      session_id: sessionId,
    });
    el("message").textContent = `attempt ${result.attempt_id} 已开始`;
    await refresh();
  } catch (error) { el("message").textContent = error.message; }
};

async function finish(status) {
  try {
    const result = await request("/api/attempts/finish", { status, failure_reason: el("failureReason").value, note: el("note").value });
    el("message").textContent = `attempt ${result.attempt_id}: ${result.status}`;
    await refresh();
  } catch (error) { el("message").textContent = error.message; }
}

el("success").onclick = () => finish("success");
el("failure").onclick = () => finish("failure");
setInterval(refresh, 1000);
refresh();
