/* FlashServer local console — vanilla JS, no build step. */
(() => {
  const TOKEN = window.FLASHSERVER_TOKEN || "";
  const $ = (sel) => document.querySelector(sel);
  const state = { sys: null, models: [], loaded: [], storage: [], tab: "overview", lang: localStorage.getItem("fs.lang") || "zh", online: null };

  const I18N = {
    zh: {
      "status.checking": "检查中", "status.ok": "运行中", "status.bad": "离线",
      "tab.overview": "概览", "tab.models": "模型", "tab.loaded": "已加载", "tab.chat": "对话测试", "tab.logs": "日志", "tab.about": "关于",
      "ov.gpu": "算力资源", "ov.service": "服务状态", "ov.storage": "磁盘占用",
      "md.cached": "本地模型", "md.load": "加载模型", "md.ref": "引用", "md.bundle": "Bundle", "md.weights": "权重",
      "md.size": "大小", "md.source": "来源",
      "ld.title": "已加载模型", "ld.empty": "还没有加载模型。到「模型」页输入 ref 加载。",
      "ld.unload": "卸载", "ld.chat": "对话", "ld.copy": "复制地址", "ld.copied": "已复制",
      "chat.title": "对话测试", "chat.send": "发送", "chat.maxTokens": "最大 tokens", "chat.temp": "温度",
      "chat.placeholder": "输入消息，Enter 发送，Shift+Enter 换行",
      "chat.none": "请先加载一个支持 serve 的模型",
      "log.title": "日志", "log.server": "服务", "log.model": "模型", "log.auto": "自动刷新",
      "ab.title": "系统信息", "ab.api": "API 文档：/v1/* 接口为本地 HTTP API，健康检查 /health。",
      "common.loading": "加载中", "common.ready": "就绪", "common.missing": "缺失",
      "common.refresh": "刷新", "common.yes": "是", "common.no": "否",
      "toast.loading": "正在加载", "toast.loaded": "加载完成", "toast.unloaded": "已卸载",
      "toast.failed": "操作失败", "toast.copied": "已复制到剪贴板",
      "ov.uptime": "运行时长", "ov.version": "版本", "ov.host": "主机", "ov.kernel": "内核",
      "ov.driver": "驱动", "ov.os": "系统", "ov.auth": "鉴权", "ov.loadedCount": "已加载",
      "ov.vram": "显存", "ov.none": "无",
      "ab.auth": "API 鉴权", "ab.authOff": "关闭（本地使用）", "ab.authOn": "开启",
      "job.events": "进度",
    },
    en: {
      "status.checking": "Checking", "status.ok": "Running", "status.bad": "Offline",
      "tab.overview": "Overview", "tab.models": "Models", "tab.loaded": "Loaded", "tab.chat": "Chat", "tab.logs": "Logs", "tab.about": "About",
      "ov.gpu": "Compute", "ov.service": "Service", "ov.storage": "Disk usage",
      "md.cached": "Local models", "md.load": "Load model", "md.ref": "Ref", "md.bundle": "Bundle", "md.weights": "Weights",
      "md.size": "Size", "md.source": "Source",
      "ld.title": "Loaded models", "ld.empty": "No model loaded yet. Load one from the Models tab.",
      "ld.unload": "Unload", "ld.chat": "Chat", "ld.copy": "Copy endpoint", "ld.copied": "Copied",
      "chat.title": "Chat test", "chat.send": "Send", "chat.maxTokens": "Max tokens", "chat.temp": "Temperature",
      "chat.placeholder": "Type a message. Enter to send, Shift+Enter for newline.",
      "chat.none": "Load a serve-capable model first",
      "log.title": "Logs", "log.server": "Server", "log.model": "Model", "log.auto": "Auto refresh",
      "ab.title": "System", "ab.api": "API: local HTTP endpoints under /v1/*; health check at /health.",
      "common.loading": "loading", "common.ready": "ready", "common.missing": "missing",
      "common.refresh": "Refresh", "common.yes": "yes", "common.no": "no",
      "toast.loading": "Loading", "toast.loaded": "Loaded", "toast.unloaded": "Unloaded",
      "toast.failed": "Failed", "toast.copied": "Copied to clipboard",
      "ov.uptime": "Uptime", "ov.version": "Version", "ov.host": "Host", "ov.kernel": "Kernel",
      "ov.driver": "Driver", "ov.os": "OS", "ov.auth": "Auth", "ov.loadedCount": "Loaded",
      "ov.vram": "VRAM", "ov.none": "none",
      "ab.auth": "API auth", "ab.authOff": "off (local)", "ab.authOn": "on",
      "job.events": "Progress",
    },
  };
  const t = (k) => (I18N[state.lang] && I18N[state.lang][k]) || k;

  function applyLang() {
    document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
    $("#btn-lang").textContent = state.lang === "zh" ? "EN" : "中文";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $("#chat-text").placeholder = t("chat.placeholder");
    if (state.online === true) setStatus("ok");
    if (state.online === false) setStatus("bad");
    renderAll();
  }

  function setStatus(kind) {
    const pill = $("#status-pill");
    pill.classList.remove("ok", "bad");
    pill.classList.add(kind);
    pill.lastElementChild.textContent = kind === "ok" ? t("status.ok") : t("status.bad");
  }

  function api(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (TOKEN) headers["X-Flashcli-Token"] = TOKEN;
    if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    return fetch(path, Object.assign({}, opts, { headers }));
  }

  function fmtBytes(n) {
    if (!n && n !== 0) return "—";
    const u = ["B", "KiB", "MiB", "GiB", "TiB"];
    let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
  }
  function fmtUptime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}m`;
    return `${m}m ${sec % 60}s`;
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 6000);
  }

  async function refresh() {
    try {
      const [sys, models, loaded, storage] = await Promise.all([
        api("/v1/system").then((r) => r.json()),
        api("/v1/models").then((r) => r.json()),
        api("/v1/models/loaded").then((r) => r.json()),
        api("/v1/storage").then((r) => r.json()),
      ]);
      state.sys = sys;
      state.models = models.models || [];
      state.loaded = loaded.models || (models.loaded || []);
      state.storage = storage.areas || [];
      state.online = true;
      setStatus("ok");
      $("#version").textContent = "v" + (sys.version || "—");
      renderAll();
    } catch (err) {
      state.online = false;
      setStatus("bad");
      console.warn("refresh failed", err);
    }
  }

  function renderAll() {
    renderOverview();
    renderModels();
    renderLoaded();
    renderChatModels();
    renderLogRefs();
    renderAbout();
  }

  function renderOverview() {
    if (!state.sys) return;
    const gpus = state.sys.gpu || [];
    $("#gpu-list").innerHTML = gpus.length
      ? gpus.map((g) => {
          const total = g.memory_total_bytes || 1;
          const used = g.memory_used_bytes || 0;
          const pct = Math.min(100, (used / total) * 100);
          return `<div>
            <div class="gpu-name">${esc(g.name)}</div>
            <div class="bar"><span style="width:${pct.toFixed(1)}%"></span></div>
            <div class="gpu-meta"><span>${t("ov.vram")} ${fmtBytes(used)} / ${fmtBytes(total)}</span><span>${pct.toFixed(0)}%</span></div>
          </div>`;
        }).join("")
      : `<div class="muted">${esc(state.sys.gpu_error || t("ov.none"))}</div>`;

    const s = state.sys;
    $("#service-info").innerHTML = [
      [t("ov.uptime"), fmtUptime(s.uptime_seconds)],
      [t("ov.loadedCount"), `${s.loaded_count ?? state.loaded.length}${s.max_loaded ? " / " + s.max_loaded : ""}`],
      [t("ov.version"), esc(s.version)],
      [t("ov.driver"), esc(s.driver_version || "—")],
      [t("ov.os"), `${esc(s.os)}/${esc(s.arch)}${s.wsl ? " · WSL" : ""}`],
    ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");

    $("#storage-list").innerHTML = state.storage.length
      ? state.storage.map((a) => `<div class="row" style="justify-content:space-between;padding:5px 0">
          <span>${esc(a.name)}</span><span class="muted">${fmtBytes(a.bytes)}</span></div>`).join("")
      : `<div class="muted">—</div>`;
  }

  function renderModels() {
    const body = $("#models-body");
    $("#models-hint").textContent = `${state.models.length}`;
    if (!state.models.length) {
      body.innerHTML = `<tr><td colspan="6" class="muted">—</td></tr>`;
      return;
    }
    body.innerHTML = state.models.map((m) => {
      const loaded = state.loaded.some((l) => l.ref === m.ref);
      return `<tr>
        <td class="ref">${esc(m.ref)}</td>
        <td>${m.bundle_cached ? `<span class="badge ok">${t("common.ready")}</span>` : `<span class="badge bad">${t("common.missing")}</span>`}</td>
        <td>${m.weights_cached ? `<span class="badge ok">${t("common.ready")}</span>` : `<span class="badge bad">${t("common.missing")}</span>`}</td>
        <td>${fmtBytes((m.bundle_bytes || 0) + (m.weights_bytes || 0))}</td>
        <td class="muted">${esc(m.weights_source || "")}${m.weights_repo ? " · " + esc(m.weights_repo) : ""}</td>
        <td style="text-align:right">${loaded ? `<button class="mini" data-chat="${esc(m.ref)}">${t("ld.chat")}</button>` : `<button class="mini" data-load="${esc(m.ref)}">${t("md.load")}</button>`}</td>
      </tr>`;
    }).join("");
    body.querySelectorAll("[data-load]").forEach((b) => b.addEventListener("click", () => loadModel(b.dataset.load)));
    body.querySelectorAll("[data-chat]").forEach((b) => b.addEventListener("click", () => { switchTab("chat"); $("#chat-model").value = b.dataset.chat; }));
  }

  function renderLoaded() {
    $("#loaded-hint").textContent = `${state.loaded.length}`;
    const box = $("#loaded-list");
    if (!state.loaded.length) { box.innerHTML = `<div class="muted">${t("ld.empty")}</div>`; return; }
    box.innerHTML = state.loaded.map((m) => `<div class="loaded-item">
      <div class="head">
        <div class="ref">${esc(m.ref)}</div>
        <div class="actions">
          <button class="mini" data-copy="${esc(m.endpoint)}">${t("ld.copy")}</button>
          <button class="mini" data-chat="${esc(m.ref)}">${t("ld.chat")}</button>
          <button class="danger" data-unload="${esc(m.ref)}">${t("ld.unload")}</button>
        </div>
      </div>
      <div class="meta">
        <span>${esc(m.endpoint)}</span>
        ${m.pid ? `<span>PID ${m.pid}</span>` : ""}
        ${m.loaded_at ? `<span>${esc(new Date(m.loaded_at).toLocaleString())}</span>` : ""}
      </div>
    </div>`).join("");
    box.querySelectorAll("[data-unload]").forEach((b) => b.addEventListener("click", () => unloadModel(b.dataset.unload)));
    box.querySelectorAll("[data-chat]").forEach((b) => b.addEventListener("click", () => { switchTab("chat"); $("#chat-model").value = b.dataset.chat; }));
    box.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); toast(t("toast.copied"), "ok"); } catch { toast(b.dataset.copy); }
    }));
  }

  function renderChatModels() {
    const sel = $("#chat-model");
    const prev = sel.value;
    sel.innerHTML = state.loaded.length
      ? state.loaded.map((m) => `<option value="${esc(m.ref)}">${esc(m.ref)}</option>`).join("")
      : `<option value="">${t("chat.none")}</option>`;
    if (prev && state.loaded.some((m) => m.ref === prev)) sel.value = prev;
  }

  function renderLogRefs() {
    const sel = $("#log-ref");
    const prev = sel.value;
    const refs = Array.from(new Set([...state.loaded.map((m) => m.ref), ...state.models.map((m) => m.ref)]));
    sel.innerHTML = refs.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`).join("");
    if (prev && refs.includes(prev)) sel.value = prev;
  }

  function renderAbout() {
    if (!state.sys) return;
    const s = state.sys;
    $("#about-info").innerHTML = [
      ["FlashServer", esc(s.version)],
      [t("ov.os"), `${esc(s.os)}/${esc(s.arch)}`],
      [t("ov.host"), esc(s.hostname || "—")],
      [t("ov.kernel"), esc(s.kernel || "—")],
      [t("ov.driver"), esc(s.driver_version || "—")],
      [t("ov.uptime"), fmtUptime(s.uptime_seconds)],
      [t("ab.auth"), s.auth ? t("ab.authOn") : t("ab.authOff")],
    ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  }

  function switchTab(name) {
    state.tab = name;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
    if (name === "logs") refreshLogs();
  }

  async function loadModel(refStr) {
    if (!refStr) refStr = $("#load-ref").value.trim();
    if (!refStr) return;
    const jobBox = $("#load-job");
    jobBox.classList.remove("hidden");
    jobBox.innerHTML = `<span class="spinner"></span>${t("toast.loading")} <span class="ref">${esc(refStr)}</span>`;
    $("#btn-load").disabled = true;
    try {
      const res = await api("/v1/models/load", { method: "POST", body: JSON.stringify({ ref: refStr, async: true }) });
      if (!res.ok) throw new Error(await readError(res));
      const job = await res.json();
      await pollJob(job.job_id, refStr);
      await refresh();
    } catch (err) {
      jobBox.innerHTML = `<span style="color:var(--danger)">${esc(err.message)}</span>`;
      toast(t("toast.failed") + ": " + err.message, "err");
    } finally {
      $("#btn-load").disabled = false;
    }
  }

  async function pollJob(id, refStr) {
    const jobBox = $("#load-job");
    for (let i = 0; i < 3600; i++) {
      const res = await api("/v1/jobs/" + encodeURIComponent(id));
      if (!res.ok) throw new Error(await readError(res));
      const job = await res.json();
      const last = (job.events || []).slice(-1)[0];
      if (job.state === "done") {
        jobBox.innerHTML = `<span style="color:var(--accent-2)">✓</span> ${t("toast.loaded")} <span class="ref">${esc(refStr)}</span>`;
        toast(t("toast.loaded") + ": " + refStr, "ok");
        setTimeout(() => jobBox.classList.add("hidden"), 4000);
        return;
      }
      if (job.state === "failed") throw new Error(job.error || "load failed");
      jobBox.innerHTML = `<span class="spinner"></span>${t("toast.loading")} <span class="ref">${esc(refStr)}</span>` +
        (last ? `<div class="muted" style="margin-top:6px">${esc(last.phase)} ${esc(last.message || "")}</div>` : "");
      await new Promise((r) => setTimeout(r, 800));
    }
    throw new Error("load timed out");
  }

  async function unloadModel(refStr) {
    try {
      const res = await api("/v1/models/unload", { method: "POST", body: JSON.stringify({ ref: refStr }) });
      if (!res.ok) throw new Error(await readError(res));
      toast(t("toast.unloaded") + ": " + refStr, "ok");
      await refresh();
    } catch (err) {
      toast(t("toast.failed") + ": " + err.message, "err");
    }
  }

  async function readError(res) {
    try {
      const j = await res.json();
      return j.error || j.detail || JSON.stringify(j);
    } catch {
      return (await res.text()) || `HTTP ${res.status}`;
    }
  }

  async function sendChat() {
    const refStr = $("#chat-model").value;
    const text = $("#chat-text").value.trim();
    if (!text) return;
    if (!refStr) { toast(t("chat.none"), "err"); return; }
    const log = $("#chat-log");
    const user = document.createElement("div");
    user.className = "msg user";
    user.textContent = text;
    log.appendChild(user);
    $("#chat-text").value = "";
    const bot = document.createElement("div");
    bot.className = "msg assistant";
    bot.textContent = "";
    log.appendChild(bot);
    log.scrollTop = log.scrollHeight;
    $("#btn-send").disabled = true;
    try {
      const body = {
        ref: refStr,
        body: {
          model: refStr,
          messages: [{ role: "user", content: text }],
          max_tokens: Number($("#chat-max-tokens").value) || 128,
          temperature: Number($("#chat-temp").value) || 0,
          stream: true,
        },
      };
      const res = await api("/v1/ui/chat", { method: "POST", body: JSON.stringify(body) });
      if (!res.ok) throw new Error(await readError(res));
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          const s = line.trim();
          if (!s.startsWith("data:")) continue;
          const payload = s.slice(5).trim();
          if (payload === "[DONE]") continue;
          try {
            const j = JSON.parse(payload);
            const delta = j.choices && j.choices[0] && (j.choices[0].delta || j.choices[0].message);
            if (delta && delta.content) {
              bot.textContent += delta.content;
              log.scrollTop = log.scrollHeight;
            }
          } catch { /* ignore keep-alives */ }
        }
      }
      if (!bot.textContent) bot.textContent = "(empty response)";
    } catch (err) {
      bot.className = "msg error";
      bot.textContent = err.message;
    } finally {
      $("#btn-send").disabled = false;
    }
  }

  let logTimer = null;
  async function refreshLogs() {
    if (state.tab !== "logs") return;
    const kind = $("#log-kind").value;
    const ref = $("#log-ref").value;
    const q = new URLSearchParams({ kind, lines: "300" });
    if (kind === "model" && ref) q.set("ref", ref);
    try {
      const res = await api("/v1/logs?" + q.toString());
      if (!res.ok) throw new Error(await readError(res));
      const j = await res.json();
      const view = $("#log-view");
      view.textContent = (j.lines || []).join("\n");
      view.scrollTop = view.scrollHeight;
    } catch (err) {
      $("#log-view").textContent = String(err.message);
    }
  }

  function bind() {
    $("#tabs").addEventListener("click", (e) => {
      const b = e.target.closest(".tab");
      if (b) switchTab(b.dataset.tab);
    });
    $("#btn-refresh").addEventListener("click", refresh);
    $("#btn-lang").addEventListener("click", () => {
      state.lang = state.lang === "zh" ? "en" : "zh";
      localStorage.setItem("fs.lang", state.lang);
      applyLang();
    });
    $("#btn-load").addEventListener("click", () => loadModel());
    $("#load-ref").addEventListener("keydown", (e) => { if (e.key === "Enter") loadModel(); });
    $("#btn-send").addEventListener("click", sendChat);
    $("#chat-text").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    $("#log-kind").addEventListener("change", () => {
      $("#log-ref").classList.toggle("hidden", $("#log-kind").value !== "model");
      refreshLogs();
    });
    $("#log-ref").addEventListener("change", refreshLogs);
    logTimer = setInterval(() => {
      if ($("#log-auto").checked) refreshLogs();
    }, 2000);
  }

  bind();
  applyLang();
  refresh();
  setInterval(() => {
    if (!document.hidden && ["overview", "models", "loaded", "about"].includes(state.tab)) refresh();
  }, 3000);
})();
