let sessionToken = "";
const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (options.body) {
    headers["Content-Type"] = "application/json";
    headers["X-Wechat-Console"] = sessionToken;
  }
  const response = await fetch(path, {...options, headers});
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
  return data;
}

function fields(form) {
  const raw = Object.fromEntries(new FormData(form).entries());
  for (const key of ["latest", "max_pages"]) {
    if (raw[key]) raw[key] = Number(raw[key]); else delete raw[key];
  }
  for (const key of ["date", "since", "until", "output"]) if (!raw[key]) delete raw[key];
  if (raw.date || raw.since) delete raw.latest;
  raw.formats = String(raw.formats || "").split(",").map(v => v.trim()).filter(Boolean);
  raw.assets = form.elements.assets.checked;
  return raw;
}

async function submit(path, form) {
  $("#notice").textContent = "任务已提交，正在本机处理……";
  try {
    const result = await api(path, {method: "POST", body: JSON.stringify(fields(form))});
    $("#notice").textContent = `任务 ${result.job.id.slice(0, 8)} 已进入队列。`;
    await refresh();
  } catch (error) {
    $("#notice").textContent = `提交失败：${error.message}`;
  }
}

async function refresh() {
  const [overview, jobs] = await Promise.all([api("/api/overview"), api("/api/jobs")]);
  const status = overview.status;
  $("#metrics").innerHTML = [
    ["版本", status.version],
    ["运行时间", `${status.uptime_seconds}s`],
    ["内存", `${(status.memory_rss_bytes / 1048576).toFixed(1)} MiB`],
    ["历史任务", status.history_count],
  ].map(([name, value]) => `<div class="metric">${name}<b>${value}</b></div>`).join("");
  $("#pipeline").innerHTML = overview.pipeline.map(item => `<li>${escapeHtml(item)}</li>`).join("");
  $("#sources").innerHTML = overview.sources.map(item => `<li><b>${escapeHtml(item.name)}</b><br>${escapeHtml(item.endpoint)} · ${escapeHtml(item.mode)}</li>`).join("");
  $("#security").textContent = JSON.stringify(overview.security, null, 2);
  $("#parity").innerHTML = `<p><span class="tag">${overview.parity.count} 个参数条目</span></p>` +
    Object.entries(overview.parity.dispositions).map(([k,v]) => `<p>${escapeHtml(k)}：${v}</p>`).join("");
  const rows = [
    ...jobs.jobs.map(job => ({time:job.created_at,kind:job.kind,state:job.state,detail:job.error?.message || job.result?.manifest || job.id})),
    ...overview.history.slice().reverse().map(item => ({time:item.started_at,kind:item.kind,state:item.result,detail:item.error?.message || item.id})),
  ].slice(0, 30);
  $("#jobs").innerHTML = rows.map(item => `<tr><td>${escapeHtml(item.time || "")}</td><td>${escapeHtml(item.kind || "")}</td><td>${escapeHtml(item.state || "")}</td><td>${escapeHtml(item.detail || "")}</td></tr>`).join("");
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value);
  return node.innerHTML;
}

$("#article-form").addEventListener("submit", event => {event.preventDefault(); submit("/api/article", event.currentTarget);});
$("#account-form").addEventListener("submit", event => {event.preventDefault(); submit("/api/account", event.currentTarget);});

(async () => {
  sessionToken = (await api("/api/session")).token;
  await refresh();
  setInterval(refresh, 3000);
})().catch(error => {$("#notice").textContent = `控制台初始化失败：${error.message}`;});
