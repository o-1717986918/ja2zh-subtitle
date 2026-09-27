const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const ui = {
  form: $("#job-form"),
  file: $("#video-file"),
  drop: $("#drop-frame"),
  fileTitle: $("#file-title"),
  fileMeta: $("#file-meta"),
  sourcePath: $("#source-path"),
  outputDir: $("#output-dir"),
  key: $("#api-key"),
  keyState: $("#key-state"),
  keyNote: $("#key-note"),
  apiSection: $("#api-section"),
  start: $("#start-button"),
  cancel: $("#cancel-button"),
  openOutput: $("#open-output"),
  jobTitle: $("#job-title"),
  jobStage: $("#job-stage"),
  progressLabel: $("#progress-label"),
  transport: $("#transport"),
  log: $("#job-log"),
  results: $("#results-panel"),
  empty: $("#empty-result"),
  resultCount: $("#result-count"),
  fileList: $("#file-list"),
  preview: $("#video-preview"),
  toast: $("#toast"),
};

let selectedFile = null;
let uploadedPath = "";
let currentJobId = "";
let pollTimer = null;
let toastTimer = null;
let displayedLogs = "";

function formatBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function toast(message, isError = false) {
  clearTimeout(toastTimer);
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", isError);
  ui.toast.classList.add("visible");
  toastTimer = setTimeout(() => ui.toast.classList.remove("visible"), 3200);
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try { payload = await response.json(); } catch { /* response has no JSON */ }
  if (!response.ok) throw new Error(payload.detail || `请求失败：HTTP ${response.status}`);
  return payload;
}

function setValue(id, value) {
  const element = $(`#${id}`);
  if (!element || value === undefined || value === null) return;
  if (element.type === "checkbox") element.checked = Boolean(value);
  else element.value = String(value);
}

function updateRangeLabels() {
  $("#vad-threshold-value").textContent = Number($("#vad-threshold").value).toFixed(2);
  $("#min-gap-value").textContent = `${Number($("#min-gap").value).toFixed(1)}s`;
  $("#max-chars-value").textContent = $("#max-chars").value;
  $("#font-size-value").textContent = $("#font-size").value;
  $("#video-crf-value").textContent = $("#video-crf").value;
}

function setKeyStatus(status) {
  ui.keyState.classList.toggle("ready", status.set);
  ui.keyState.querySelector("b").textContent = status.set ? "密钥已就绪" : "未设置密钥";
  const labels = {
    session: "当前会话",
    environment: "环境变量",
    credential_vault: "系统凭据库",
  };
  if (status.set && labels[status.source]) ui.keyNote.textContent = `密钥来源：${labels[status.source]}。页面不会读取或回显密钥内容。`;
}

function subtitleMode() {
  return document.querySelector('input[name="subtitle-mode"]:checked').value;
}

function updateMode() {
  const japanese = subtitleMode() === "ja";
  ui.apiSection.classList.toggle("disabled", japanese);
  $("#polish-option").style.opacity = japanese ? "0.45" : "1";
  $("#no-polish").disabled = japanese;
  ui.start.querySelector("span").textContent = japanese ? "生成日语原文成片" : "生成中文字幕成片";
}

function chooseFile(file) {
  if (!file) return;
  selectedFile = file;
  uploadedPath = "";
  ui.sourcePath.value = "";
  ui.fileTitle.textContent = file.name;
  ui.fileMeta.textContent = `${formatBytes(file.size)} · 等待上传`;
}

async function uploadSelectedFile() {
  if (!selectedFile) return ui.sourcePath.value.trim();
  if (uploadedPath) return uploadedPath;
  ui.start.disabled = true;
  ui.start.querySelector("span").textContent = "正在上传素材…";
  const data = new FormData();
  data.append("file", selectedFile);
  const payload = await request("/api/uploads", { method: "POST", body: data });
  uploadedPath = payload.path;
  ui.fileMeta.textContent = `${formatBytes(payload.size)} · 已装载`;
  return uploadedPath;
}

function collectJob(sourcePath) {
  return {
    source_path: sourcePath,
    output_dir: ui.outputDir.value.trim(),
    preset: $("#preset").value,
    device: $("#device").value,
    quality_mode: $("#quality-mode").value,
    japanese_only: subtitleMode() === "ja",
    subtitle_only: $("#subtitle-only").checked,
    no_polish: $("#no-polish").checked,
    force: $("#force").checked,
    vad_filter: $("#vad-filter").checked,
    gap_recovery: $("#gap-recovery").checked,
    vad_threshold: Number($("#vad-threshold").value),
    min_gap_seconds: Number($("#min-gap").value),
    model: $("#model").value,
    batch_size: Number($("#batch-size").value),
    max_chars_per_line: Number($("#max-chars").value),
    font_size: Number($("#font-size").value),
    video_codec: $("#video-codec").value,
    video_crf: Number($("#video-crf").value),
    video_preset: $("#video-preset").value,
  };
}

function statusLabel(status) {
  return { queued: "等待运行", running: "正在处理", completed: "处理完成", failed: "处理失败", cancelled: "已取消" }[status] || status;
}

function renderFiles(files) {
  ui.fileList.replaceChildren();
  ui.preview.hidden = true;
  ui.preview.removeAttribute("src");
  if (!files.length) {
    ui.empty.hidden = false;
    ui.resultCount.textContent = "未生成文件";
    return;
  }
  ui.empty.hidden = true;
  ui.resultCount.textContent = `${files.length} 个文件`;
  const video = files.find((file) => file.kind === "video" && file.name.endsWith("_sub.mp4"));
  if (video) {
    ui.preview.src = video.url;
    ui.preview.hidden = false;
  }
  for (const file of files) {
    const link = document.createElement("a");
    link.className = "file-item";
    link.href = file.url;
    if (file.kind !== "video") link.download = file.name;
    link.innerHTML = `<span><b></b><small></small></span><em>↗</em>`;
    link.querySelector("b").textContent = file.name;
    link.querySelector("small").textContent = `${file.kind.toUpperCase()} · ${formatBytes(file.size)}`;
    ui.fileList.append(link);
  }
}

function renderJob(job) {
  ui.jobTitle.textContent = job.source_name;
  ui.jobStage.textContent = `${statusLabel(job.status)} · ${job.stage}`;
  ui.progressLabel.textContent = `${job.progress}%`;
  ui.transport.style.setProperty("--progress", `${job.progress}%`);
  ui.transport.classList.toggle("running", job.status === "running");
  $$(".stage-list li").forEach((stage) => stage.classList.toggle("done", job.progress >= Number(stage.dataset.threshold)));
  const nextLogs = job.logs.join("\n");
  if (nextLogs !== displayedLogs) {
    displayedLogs = nextLogs;
    ui.log.textContent = nextLogs || "任务已创建，等待运行。";
    ui.log.scrollTop = ui.log.scrollHeight;
  }
  const active = ["queued", "running"].includes(job.status);
  ui.start.disabled = active;
  ui.cancel.hidden = !active;
  ui.openOutput.hidden = !["completed", "failed"].includes(job.status);
  if (job.status === "completed") renderFiles(job.files);
  if (job.status === "failed" && job.error) toast(job.error, true);
}

async function pollJob() {
  if (!currentJobId) return;
  try {
    const job = await request(`/api/jobs/${currentJobId}`);
    renderJob(job);
    if (["queued", "running"].includes(job.status)) pollTimer = setTimeout(pollJob, 850);
    else {
      pollTimer = null;
      ui.start.disabled = false;
      updateMode();
      toast(job.status === "completed" ? "处理完成，输出文件已就绪。" : statusLabel(job.status), job.status === "failed");
    }
  } catch (error) {
    toast(error.message, true);
    pollTimer = setTimeout(pollJob, 1800);
  }
}

async function startJob(event) {
  event.preventDefault();
  try {
    let source = ui.sourcePath.value.trim();
    if (selectedFile) source = await uploadSelectedFile();
    if (!source) throw new Error("请先选择视频或填写本机视频路径。");
    const job = await request("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectJob(source)),
    });
    currentJobId = job.id;
    displayedLogs = "";
    renderFiles([]);
    renderJob(job);
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) {
    toast(error.message, true);
    ui.start.disabled = false;
    updateMode();
  }
}

async function initialize() {
  try {
    const state = await request("/api/state");
    const map = {
      "output-dir": "output_dir", preset: "preset", device: "device", "quality-mode": "quality_mode",
      "subtitle-only": "subtitle_only", "no-polish": "no_polish", force: "force", "vad-filter": "vad_filter",
      "gap-recovery": "gap_recovery", "vad-threshold": "vad_threshold", "min-gap": "min_gap_seconds",
      model: "model", "batch-size": "batch_size", "max-chars": "max_chars_per_line", "font-size": "font_size",
      "video-codec": "video_codec", "video-crf": "video_crf", "video-preset": "video_preset",
    };
    Object.entries(map).forEach(([id, key]) => setValue(id, state.settings[key]));
    if (state.packaged && state.bundled_presets?.length) {
      const allowed = new Set(state.bundled_presets);
      $$("#preset option").forEach((option) => {
        option.disabled = !allowed.has(option.value);
        if (option.disabled && !option.textContent.includes("未内置")) option.textContent += " · 未内置";
      });
      if (!allowed.has($("#preset").value)) $("#preset").value = state.bundled_presets[0];
      $("#preset").title = "安装包内置 Whisper-medium，确保首次运行无需下载模型。";
    }
    const mode = state.settings.japanese_only ? "ja" : "zh";
    document.querySelector(`input[name="subtitle-mode"][value="${mode}"]`).checked = true;
    setKeyStatus(state.api_key);
    updateRangeLabels();
    updateMode();
  } catch (error) { toast(error.message, true); }
}

ui.drop.addEventListener("click", () => ui.file.click());
ui.file.addEventListener("change", () => chooseFile(ui.file.files[0]));
["dragenter", "dragover"].forEach((name) => ui.drop.addEventListener(name, (event) => { event.preventDefault(); ui.drop.classList.add("dragging"); }));
["dragleave", "drop"].forEach((name) => ui.drop.addEventListener(name, (event) => { event.preventDefault(); ui.drop.classList.remove("dragging"); }));
ui.drop.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
ui.sourcePath.addEventListener("input", () => {
  if (ui.sourcePath.value.trim()) {
    selectedFile = null;
    uploadedPath = "";
    ui.fileTitle.textContent = "使用本机路径";
    ui.fileMeta.textContent = ui.sourcePath.value.trim();
  }
});

$("#toggle-key").addEventListener("click", () => {
  const visible = ui.key.type === "text";
  ui.key.type = visible ? "password" : "text";
  $("#toggle-key").textContent = visible ? "显示" : "隐藏";
});
$("#save-key").addEventListener("click", async () => {
  try {
    if (!ui.key.value.trim()) throw new Error("请输入 DeepSeek API Key。");
    const status = await request("/api/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: ui.key.value.trim(), remember: $("#remember-key").checked }),
    });
    ui.key.value = "";
    setKeyStatus(status);
    ui.keyNote.textContent = status.message;
    toast(status.message);
  } catch (error) { toast(error.message, true); }
});
$("#clear-key").addEventListener("click", async () => {
  try {
    const status = await request("/api/api-key", { method: "DELETE" });
    setKeyStatus(status);
    ui.keyNote.textContent = status.message;
    toast(status.message);
  } catch (error) { toast(error.message, true); }
});

$$('input[name="subtitle-mode"]').forEach((radio) => radio.addEventListener("change", updateMode));
$$('input[type="range"]').forEach((range) => range.addEventListener("input", updateRangeLabels));
ui.form.addEventListener("submit", startJob);
ui.cancel.addEventListener("click", async () => {
  if (!currentJobId) return;
  try { renderJob(await request(`/api/jobs/${currentJobId}/cancel`, { method: "POST" })); }
  catch (error) { toast(error.message, true); }
});
ui.openOutput.addEventListener("click", async () => {
  if (!currentJobId) return;
  try { await request(`/api/jobs/${currentJobId}/open-output`, { method: "POST" }); }
  catch (error) { toast(error.message, true); }
});
$("#clear-log").addEventListener("click", () => { displayedLogs = ""; ui.log.textContent = "日志显示已清空；任务仍在后台运行。"; });
$("#doctor-button").addEventListener("click", async () => {
  ui.log.textContent = "正在检查 Python、FFmpeg、CUDA 和在线 API 配置…";
  try {
    const result = await request("/api/doctor");
    displayedLogs = result.output;
    ui.log.textContent = result.output;
    toast(result.ok ? "运行环境检查通过。" : "环境检查发现缺项。", !result.ok);
    const state = await request("/api/state");
    setKeyStatus(state.api_key);
  } catch (error) { toast(error.message, true); }
});

initialize();
