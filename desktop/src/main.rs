#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use eframe::egui;
use egui_extras::{Column, TableBuilder};
use serde::{Deserialize, Serialize};
use serde_json::Value;

static API_BASE: OnceLock<String> = OnceLock::new();

/// The setup engine picks a free Windows port when the default 8790 is in a
/// Hyper-V/WinNAT excluded range and records it here.
fn api_base() -> &'static str {
    API_BASE.get_or_init(|| {
        if let Some(dir) = std::env::var_os("LOCALAPPDATA") {
            let path = PathBuf::from(dir).join("FlashServer").join("api-url.txt");
            if let Ok(text) = std::fs::read_to_string(path) {
                let url = text.trim().trim_end_matches('/');
                if url.starts_with("http://") || url.starts_with("https://") {
                    return url.to_string();
                }
            }
        }
        "http://127.0.0.1:8790".to_string()
    })
}

fn api_addr() -> &'static str {
    api_base()
        .trim_start_matches("http://")
        .trim_start_matches("https://")
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tab {
    Overview,
    Models,
    Logs,
    Settings,
}

impl Tab {
    fn label(self) -> &'static str {
        match self {
            Tab::Overview => "概览",
            Tab::Models => "模型",
            Tab::Logs => "日志",
            Tab::Settings => "设置",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ModelTab {
    Local,
    Hub,
}

#[derive(Clone)]
struct ModelRow {
    name: String,
    bundle_ready: bool,
    weights_ready: bool,
    serve: bool,
    bundle_bytes: f64,
    runtime_id: String,
    runtime_bytes: f64,
    weights_bytes: f64,
    weights_key: String,
    loaded: bool,
    endpoint: String,
    pid: i64,
    loaded_at: String,
}

impl ModelRow {
    fn total_bytes(&self) -> f64 {
        self.bundle_bytes + self.runtime_bytes + self.weights_bytes
    }

    fn status(&self) -> &'static str {
        if self.loaded {
            "已启动"
        } else if self.bundle_ready && self.weights_ready {
            if self.serve {
                "就绪"
            } else {
                "仅 run"
            }
        } else if self.bundle_ready {
            "缺权重"
        } else {
            "缺 Bundle"
        }
    }

    fn ready(&self) -> bool {
        self.bundle_ready && self.weights_ready
    }
}

/// Weights keys used by more than one cached model. Their directories are
/// shared by `source/repo@revision`.
fn shared_weights_set(models: &[ModelRow]) -> HashSet<&str> {
    let mut seen: HashSet<&str> = HashSet::new();
    let mut shared: HashSet<&str> = HashSet::new();
    for model in models {
        if model.weights_key.is_empty() {
            continue;
        }
        if !seen.insert(model.weights_key.as_str()) {
            shared.insert(model.weights_key.as_str());
        }
    }
    shared
}

/// Sum bundle and per-model runtime bytes, counting each shared weights key
/// once. Two bundle versions using the same source/repo@revision share one
/// weights directory; runtime directories are per bundle/version.
fn unique_model_bytes(models: &[ModelRow]) -> f64 {
    let mut seen_weights: HashSet<&str> = HashSet::new();
    let mut seen_runtimes: HashSet<&str> = HashSet::new();
    let mut total = 0.0;
    for model in models {
        total += model.bundle_bytes;
        let weights_key = if model.weights_key.is_empty() {
            model.name.as_str()
        } else {
            model.weights_key.as_str()
        };
        if seen_weights.insert(weights_key) {
            total += model.weights_bytes;
        }
        if model.runtime_bytes > 0.0 {
            let runtime_key = if model.runtime_id.is_empty() {
                model.name.as_str()
            } else {
                model.runtime_id.as_str()
            };
            if seen_runtimes.insert(runtime_key) {
                total += model.runtime_bytes;
            }
        }
    }
    total
}

#[derive(Clone)]
struct HubRepo {
    id: i64,
    namespace: String,
    name: String,
    model_name: String,
    tags: Vec<String>,
    versions: i64,
    downloads: i64,
}

#[derive(Clone)]
struct HubVersion {
    version: String,
    size: f64,
    files: i64,
    status: String,
}

#[derive(Clone)]
struct HubDetail {
    repo_id: i64,
    versions: Vec<HubVersion>,
}

#[derive(Default, Serialize, Deserialize)]
struct Settings {
    dark: bool,
    #[serde(default)]
    wsl_ports: String,
}

#[derive(Clone)]
struct ServeOption {
    name: String,
    flag: String,
    kind: String,
    default: String,
    value: String,
    help: String,
}

#[derive(Clone)]
struct OptionsDialog {
    reference: String,
    host: String,
    default_host: String,
    public_host: String,
    port: String,
    options: Vec<ServeOption>,
    loading: bool,
    saving: bool,
    error: String,
    restart_required: bool,
    start_after_save: bool,
}

#[derive(Clone, Default)]
struct WslConfig {
    memory: String,
    processors: String,
    swap: String,
    mirrored: bool,
}

enum Event {
    System(Value),
    ServiceDown,
    Models(Value),
    Storage(Value),
    Mirror(Value),
    Logs(Option<String>),
    LogsNote(String),
    CleanNote(String),
    StorageNote(String),
    OpBusy(String),
    OpDone(Result<String, String>),
    Autostart(bool),
    Status(String),
    Job(JobEvent),
    Smoke(Result<Value, String>),
    SmokeJob(String),
    Catalog { repos: Vec<HubRepo>, total: i64 },
    CatalogTags(Vec<(i64, String)>),
    HubDetail(HubDetail),
    HubError(String),
    ModelOptions { reference: String, result: Result<Value, String> },
    ModelOptionsSaved { reference: String, result: Result<Value, String>, start: bool },
    WslApplied(Result<String, String>),
}

struct JobEvent {
    phase: String,
    message: String,
    state: String,
    verb: String,
    reference: String,
    kind: String,
    authoritative: bool,
}

enum Pending {
    StopService,
    DisableAutostart,
    Unload(String),
    Clean(Vec<String>),
    Smoke(String),
    ApplyWsl,
    Quit,
}

struct DialogState {
    title: String,
    message: String,
    action: Pending,
}

struct SmokeState {
    title: String,
    running: bool,
    ok: bool,
    cancelled: bool,
    job_id: String,
    log: String,
}

pub struct App {
    rx: Receiver<Event>,
    tx: Sender<Event>,
    tab: Tab,
    model_tab: ModelTab,
    dark: bool,
    system: Option<Value>,
    models: Vec<ModelRow>,
    model_detail: Option<ModelRow>,
    use_model: Option<ModelRow>,
    hub_query: String,
    hub_tag: i64,
    hub_tags: Vec<(i64, String)>,
    hub_repos: Vec<HubRepo>,
    hub_total: i64,
    hub_selected: Option<i64>,
    hub_detail: Option<HubDetail>,
    hub_busy: bool,
    hub_searched: bool,
    hub_error: String,
    storage: Vec<(String, String)>,
    storage_total: f64,
    storage_sizes: HashMap<String, f64>,
    storage_note: String,
    mirror_enabled: Option<bool>,
    cache_dialog: bool,
    cache_selected: HashSet<String>,
    logs: String,
    logs_busy: bool,
    logs_at: Option<Instant>,
    logs_since: Option<u64>,
    logs_ref: Option<String>,
    logs_note: String,
    autostart_known: Option<bool>,
    op_busy: Option<String>,
    op_note: Option<(String, bool, Instant)>,
    selected_models: HashSet<String>,
    known_models: HashSet<String>,
    models_note: String,
    load_ref: String,
    load_status: String,
    load_status_at: Option<Instant>,
    loading: bool,
    load_phase: String,
    load_message: String,
    load_pct: Option<f32>,
    job_ref: String,
    job_verb: String,
    dialog: Option<DialogState>,
    options_dialog: Option<OptionsDialog>,
    wsl: WslConfig,
    wsl_ports: String,
    wsl_pending: Option<WslConfig>,
    wsl_pending_ports: String,
    smoke: Option<SmokeState>,
    pending_smoke_cancel: bool,
    closing: bool,
    gpu_util: Vec<[f64; 2]>,
    gpu_mem: Vec<[f64; 2]>,
    cpu: Vec<[f64; 2]>,
    x: f64,
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        install_fonts(&cc.egui_ctx);
        let settings = load_settings();
        let dark = settings.dark;
        let wsl_ports = settings.wsl_ports.clone();
        apply_theme(&cc.egui_ctx, dark);

        let (tx, rx) = channel();
        start_ws(tx.clone(), cc.egui_ctx.clone());
        let wsl = load_wslconfig();

        Self {
            rx,
            tx,
            tab: Tab::Overview,
            model_tab: ModelTab::Local,
            dark,
            system: None,
            models: Vec::new(),
            model_detail: None,
            use_model: None,
            hub_query: String::new(),
            hub_tag: 0,
            hub_tags: Vec::new(),
            hub_repos: Vec::new(),
            hub_total: 0,
            hub_selected: None,
            hub_detail: None,
            hub_busy: false,
            hub_searched: false,
            hub_error: String::new(),
            storage: Vec::new(),
            storage_total: 0.0,
            storage_sizes: HashMap::new(),
            storage_note: String::new(),
            mirror_enabled: None,
            cache_dialog: false,
            cache_selected: HashSet::new(),
            logs: String::new(),
            logs_busy: false,
            logs_at: None,
            logs_since: None,
            logs_ref: None,
            logs_note: String::new(),
            autostart_known: None,
            op_busy: None,
            op_note: None,
            selected_models: HashSet::new(),
            known_models: HashSet::new(),
            models_note: String::new(),
            load_ref: String::new(),
            load_status: String::new(),
            load_status_at: None,
            loading: false,
            load_phase: String::new(),
            load_message: String::new(),
            load_pct: None,
            job_ref: String::new(),
            job_verb: String::new(),
            dialog: None,
            options_dialog: None,
            wsl,
            wsl_ports,
            wsl_pending: None,
            wsl_pending_ports: String::new(),
            smoke: None,
            pending_smoke_cancel: false,
            closing: false,
            gpu_util: Vec::new(),
            gpu_mem: Vec::new(),
            cpu: Vec::new(),
            x: 0.0,
        }
    }

    fn drain_events(&mut self, ctx: &egui::Context) {
        while let Ok(ev) = self.rx.try_recv() {
            match ev {
                Event::System(v) => {
                    self.autostart_known = match v["autostart"].as_str() {
                        Some("enabled") => Some(true),
                        Some("disabled") => Some(false),
                        _ => self.autostart_known,
                    };
                    let t = v["uptime_seconds"].as_f64().unwrap_or(self.x + 1.0);
                    if t + 0.5 < self.x {
                        // Service restarted: uptime went backwards, start new charts.
                        self.gpu_util.clear();
                        self.gpu_mem.clear();
                        self.cpu.clear();
                    }
                    if self.gpu_util.is_empty() || t - self.x >= 0.5 {
                        self.x = t;
                        let gpu = &v["gpu"][0];
                        let util = gpu["utilization_gpu_pct"].as_f64().unwrap_or(0.0) as f32;
                        let total = gpu["memory_total_bytes"].as_f64().unwrap_or(0.0);
                        let used = gpu["memory_used_bytes"].as_f64().unwrap_or(0.0);
                        let mem = if total > 0.0 {
                            (used / total * 100.0) as f32
                        } else {
                            0.0
                        };
                        let cpu = v["cpu"]["usage_pct"].as_f64().unwrap_or(0.0) as f32;
                        push_point(&mut self.gpu_util, t, util);
                        push_point(&mut self.gpu_mem, t, mem);
                        push_point(&mut self.cpu, t, cpu);
                    }
                    self.system = Some(v);
                }
                Event::Models(v) => {
                    self.models = parse_models(&v, self.system.as_ref());
                    self.sync_model_selection();
                }
                Event::ServiceDown => {
                    self.system = None;
                    for model in &mut self.models {
                        model.loaded = false;
                        model.endpoint.clear();
                        model.pid = 0;
                        model.loaded_at.clear();
                    }
                    self.sync_model_selection();
                    if self.loading {
                        self.loading = false;
                        self.load_pct = None;
                        self.load_message.clear();
                        self.load_status = "服务已停止".into();
                        self.load_status_at = Some(Instant::now());
                    }
                }
                Event::Storage(v) => {
                    let (areas, total, sizes) = parse_storage(&v);
                    self.storage = areas;
                    self.storage_total = total;
                    self.storage_sizes = sizes;
                }
                Event::Mirror(v) => {
                    self.mirror_enabled = v["enabled"].as_bool();
                }
                Event::Logs(text) => {
                    if let Some(text) = text {
                        self.logs = text;
                    }
                    self.logs_busy = false;
                    self.logs_at = Some(Instant::now());
                }
                Event::LogsNote(note) => self.logs_note = note,
                Event::CleanNote(note) => self.models_note = note,
                Event::StorageNote(note) => self.storage_note = note,
                Event::OpBusy(label) => {
                    self.op_busy = Some(label);
                    self.op_note = None;
                }
                Event::OpDone(result) => {
                    self.op_busy = None;
                    self.op_note = match result {
                        Ok(message) => Some((message, true, Instant::now())),
                        Err(error) => Some((error, false, Instant::now())),
                    };
                }
                Event::Autostart(enabled) => self.autostart_known = Some(enabled),
                Event::Status(text) => {
                    self.load_status = text;
                    self.load_status_at = Some(Instant::now());
                }
                Event::Job(job) => self.apply_job(job),
                Event::ModelOptions { reference, result } => {
                    if let Some(dlg) = self.options_dialog.as_mut() {
                        if dlg.reference == reference {
                            match result {
                                Ok(v) => {
                                    dlg.loading = false;
                                    dlg.error.clear();
                                    dlg.host = v["host"].as_str().unwrap_or("").to_string();
                                    dlg.default_host =
                                        v["default_host"].as_str().unwrap_or("127.0.0.1").to_string();
                                    dlg.public_host =
                                        v["public_host"].as_str().unwrap_or("").to_string();
                                    let port = v["port"].as_i64().unwrap_or(0);
                                    dlg.port = if port > 0 { port.to_string() } else { "0".to_string() };
                                    dlg.restart_required =
                                        v["restart_required"].as_bool().unwrap_or(false);
                                    dlg.options = v["options"]
                                        .as_array()
                                        .map(|items| {
                                            items
                                                .iter()
                                                .map(|o| ServeOption {
                                                    name: o["name"].as_str().unwrap_or("").to_string(),
                                                    flag: o["flag"].as_str().unwrap_or("").to_string(),
                                                    kind: o["type"].as_str().unwrap_or("string").to_string(),
                                                    default: json_text(&o["default"]),
                                                    value: o["value"].as_str().unwrap_or("").to_string(),
                                                    help: o["help"].as_str().unwrap_or("").to_string(),
                                                })
                                                .collect()
                                        })
                                        .unwrap_or_default();
                                }
                                Err(err) => {
                                    dlg.loading = false;
                                    dlg.error = err;
                                }
                            }
                        }
                    }
                }
                Event::ModelOptionsSaved { reference, result, start } => {
                    let mut close = false;
                    let mut note: Option<(String, bool, Instant)> = None;
                    let mut start_ref: Option<String> = None;
                    if let Some(dlg) = self.options_dialog.as_mut() {
                        if dlg.reference == reference {
                            dlg.saving = false;
                            match result {
                                Ok(v) => {
                                    let restart =
                                        v["restart_required"].as_bool().unwrap_or(false);
                                    if start {
                                        note = Some((
                                            "启动参数已保存，正在启动…".to_string(),
                                            true,
                                            Instant::now(),
                                        ));
                                        start_ref = Some(reference.clone());
                                    } else {
                                        note = Some((
                                            if restart {
                                                "启动参数已保存；模型正在运行，停止并重新启动后生效。".to_string()
                                            } else {
                                                "启动参数已保存，下次启动生效。".to_string()
                                            },
                                            true,
                                            Instant::now(),
                                        ));
                                    }
                                    close = true;
                                }
                                Err(err) => dlg.error = err,
                            }
                        }
                    }
                    if close {
                        self.options_dialog = None;
                    }
                    if note.is_some() {
                        self.op_note = note;
                    }
                    if let Some(reference) = start_ref {
                        self.model_detail = None;
                        self.spawn_job_ui(ctx, reference, false, "启动");
                    }
                }
                Event::WslApplied(result) => {
                    self.op_busy = None;
                    self.wsl = load_wslconfig();
                    self.op_note = Some(match result {
                        Ok(message) => (message, true, Instant::now()),
                        Err(error) => (error, false, Instant::now()),
                    });
                }
                Event::Smoke(result) => {
                    self.pending_smoke_cancel = false;
                    self.smoke = Some(match result {
                        Ok(v) => {
                            let kind = v["kind"].as_str().unwrap_or("");
                            let label = match kind {
                                "run" => "Run 冒烟测试",
                                "serve" => "请求测试",
                                _ => "模型测试",
                            };
                            let reference = v["ref"].as_str().unwrap_or("");
                            let mut log = v["log"].as_str().unwrap_or("").to_string();
                            if let Some(path) = v["log_path"].as_str().filter(|p| !p.is_empty()) {
                                log.push_str("\n\n日志文件: ");
                                log.push_str(path);
                            }
                            SmokeState {
                                title: if reference.is_empty() {
                                    label.to_string()
                                } else {
                                    format!("{label} · {reference}")
                                },
                                running: false,
                                ok: v["ok"].as_bool().unwrap_or(false),
                                cancelled: false,
                                job_id: String::new(),
                                log,
                            }
                        }
                        Err(error) => SmokeState {
                            title: "模型测试".into(),
                            running: false,
                            ok: false,
                            cancelled: false,
                            job_id: String::new(),
                            log: error,
                        },
                    });
                }
                Event::SmokeJob(id) => {
                    if let Some(smoke) = self.smoke.as_mut() {
                        smoke.job_id = id.clone();
                    }
                    if self.pending_smoke_cancel && !id.is_empty() {
                        self.pending_smoke_cancel = false;
                        spawn_cancel_job(ctx.clone(), id);
                    }
                }
                Event::Catalog { repos, total } => {
                    self.hub_repos = repos;
                    self.hub_total = total;
                    self.hub_busy = false;
                    self.hub_error.clear();
                }
                Event::CatalogTags(tags) => {
                    self.hub_tags = tags;
                    self.hub_busy = false;
                }
                Event::HubDetail(detail) => {
                    self.hub_selected = Some(detail.repo_id);
                    self.hub_detail = Some(detail);
                    self.hub_busy = false;
                }
                Event::HubError(err) => {
                    self.hub_error = err;
                    self.hub_busy = false;
                }
            }
        }
    }

    fn spawn_job_ui(
        &mut self,
        ctx: &egui::Context,
        ref_str: String,
        pull: bool,
        verb: &'static str,
    ) {
        self.job_ref = ref_str.clone();
        self.job_verb = verb.to_string();
        self.loading = true;
        self.load_status.clear();
        self.load_status_at = None;
        self.load_message.clear();
        self.load_pct = None;
        spawn_job(self.tx.clone(), ctx.clone(), ref_str, pull, verb);
    }

    fn start_smoke(&mut self, ctx: &egui::Context, name: String) {
        self.pending_smoke_cancel = false;
        self.smoke = Some(SmokeState {
            title: format!("Run 冒烟测试 · {name}"),
            running: true,
            ok: true,
            cancelled: false,
            job_id: String::new(),
            log: "测试运行中…\n".into(),
        });
        spawn_smoke(self.tx.clone(), ctx.clone(), name);
    }

    fn apply_job(&mut self, job: JobEvent) {
        if job.kind == "smoke" {
            if self.smoke.is_none() {
                return;
            }
            let reference = job.reference.clone();
            let smoke = self.smoke.get_or_insert_with(|| SmokeState {
                title: if reference.is_empty() {
                    "模型测试".into()
                } else {
                    format!("模型测试 · {reference}")
                },
                running: true,
                ok: true,
                cancelled: false,
                job_id: String::new(),
                log: String::new(),
            });
            if job.state == "running" {
                smoke.running = true;
            }
            if !job.message.is_empty() {
                smoke.log.push_str(&job.message);
                smoke.log.push('\n');
            }
            let done = job.state == "done" || job.phase == "done";
            let failed = job.state == "failed" || job.phase == "failed";
            if smoke.running && (done || failed) {
                smoke.running = false;
                if smoke.cancelled {
                    smoke.log.push_str("测试已取消\n");
                } else if done {
                    smoke.ok = true;
                    smoke.log.push_str("测试通过\n");
                } else {
                    smoke.ok = false;
                    smoke.log.push_str("测试失败\n");
                }
            }
            return;
        }
        let same_ref = !job.reference.is_empty() && self.job_ref == job.reference;
        if !job.reference.is_empty() {
            self.job_ref = job.reference.clone();
        }
        if !job.verb.is_empty() {
            // HTTP job polling (authoritative) and WebSocket updates arrive
            // together. Keep the local verb (加载 vs 下载/启动) and only use
            // the WS default when no local job has set one.
            if job.authoritative
                || self.job_verb.is_empty()
                || !same_ref
                || (!self.loading && job.state == "running")
            {
                self.job_verb = job.verb.clone();
            }
        }
        if !job.message.is_empty() {
            self.load_pct = parse_pct(&job.message);
            self.load_message = job.message.clone();
        }
        if !job.phase.is_empty() {
            self.load_phase = translate_phase(&job.phase).to_string();
        }
        match job.state.as_str() {
            "running" => {
                self.loading = true;
                self.load_status.clear();
                self.load_status_at = None;
            }
            "done" => {
                self.loading = false;
                self.load_pct = Some(100.0);
                self.load_message.clear();
                self.load_status = format!("{}完成", job.verb);
                self.load_status_at = Some(Instant::now());
            }
            "failed" => {
                self.loading = false;
                self.load_status = format!("{}失败：{}", job.verb, job.message);
                self.load_status_at = None;
            }
            _ => {}
        }
    }

    fn sync_model_selection(&mut self) {
        let cleanable: HashSet<String> = self
            .models
            .iter()
            .filter(|m| !m.loaded)
            .map(|m| m.name.clone())
            .collect();
        self.selected_models.retain(|r| cleanable.contains(r));
        for name in &cleanable {
            if !self.known_models.contains(name) {
                self.selected_models.insert(name.clone());
            }
        }
        self.known_models = self.models.iter().map(|m| m.name.clone()).collect();
    }

    fn autostart_state(&self) -> Option<bool> {
        self.system
            .as_ref()
            .and_then(|s| match s["autostart"].as_str() {
                Some("enabled") => Some(true),
                Some("disabled") => Some(false),
                _ => None,
            })
            .or(self.autostart_known)
    }

    fn overview(&mut self, ui: &mut egui::Ui) {
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                ui.label(egui::RichText::new("算力资源").small().strong().weak());
                ui.add_space(8.0);
                let width = ui.available_width();
                let half = ((width - 12.0) / 2.0).max(320.0);
                ui.horizontal_top(|ui| {
                    ui.vertical(|ui| {
                        ui.set_width(half);
                        self.gpu_card(ui);
                    });
                    ui.add_space(12.0);
                    ui.vertical(|ui| {
                        ui.set_width((width - half - 12.0).max(320.0));
                        self.cpu_card(ui);
                    });
                });
                ui.add_space(12.0);
                ui.horizontal_top(|ui| {
                    ui.vertical(|ui| {
                        ui.set_width(half);
                        self.service_panel(ui);
                    });
                    ui.add_space(12.0);
                    ui.vertical(|ui| {
                        ui.set_width((width - half - 12.0).max(320.0));
                        self.storage_panel(ui);
                    });
                });
            });
    }

    fn gpu_card(&self, ui: &mut egui::Ui) {
        panel(ui, "显卡", |ui| {
            let Some(sys) = &self.system else {
                ui.label("等待数据…");
                return;
            };
            let gpu = &sys["gpu"][0];
            if gpu.is_null() {
                ui.label(egui::RichText::new("GPU 不可用").strong().color(red(ui)));
                ui.label(sys["gpu_error"].as_str().unwrap_or("nvidia-smi 不可用"));
                return;
            }
            ui.label(
                egui::RichText::new(gpu["name"].as_str().unwrap_or("GPU"))
                    .strong()
                    .size(15.0),
            );
            let mut meta = Vec::new();
            if let Some(t) = gpu["temperature_c"].as_i64() {
                meta.push(format!("{t}°C"));
            }
            if let (Some(cg), Some(cm)) = (
                gpu["clock_graphics_mhz"].as_i64(),
                gpu["clock_memory_mhz"].as_i64(),
            ) {
                meta.push(format!("{cg}/{cm} MHz"));
            }
            if let Some(limit) = gpu["power_limit_w"].as_f64() {
                match gpu["power_draw_w"].as_f64() {
                    Some(draw) => meta.push(format!("{draw:.0}/{limit:.0} W")),
                    None => meta.push(format!("≤{limit:.0} W")),
                }
            }
            if let Some(fan) = gpu["fan_speed_pct"].as_i64() {
                meta.push(format!("风扇 {fan}%"));
            }
            egui::Grid::new("gpu_env")
                .num_columns(2)
                .spacing([14.0, 4.0])
                .show(ui, |ui| {
                    let driver = gpu["driver_version"].as_str().unwrap_or("—");
                    let cuda = sys["cuda_version"].as_str().unwrap_or("—");
                    kv(ui, "驱动 / CUDA", &format!("{driver} · CUDA {cuda}"));
                    let mem_total = gpu["memory_total_bytes"].as_f64().unwrap_or(0.0);
                    let mem_used = gpu["memory_used_bytes"].as_f64().unwrap_or(0.0);
                    let vram = if mem_total > 0.0 {
                        format!(
                            "{} / {} ({:.0}%)",
                            fmt_bytes(mem_used),
                            fmt_bytes(mem_total),
                            mem_used / mem_total * 100.0
                        )
                    } else {
                        "—".to_string()
                    };
                    kv(ui, "显存", &vram);
                    let sm = sys["sm"].as_str().unwrap_or("");
                    let cap = gpu["compute_cap"].as_str().unwrap_or("");
                    let sm_text = if sm.is_empty() {
                        "—".to_string()
                    } else if cap.is_empty() {
                        format!("sm{sm}")
                    } else {
                        format!("sm{sm} ({cap})")
                    };
                    kv(ui, "计算能力", &sm_text);
                    kv(ui, "torch", sys["torch_index"].as_str().unwrap_or("—"));
                    kv(ui, "状态", &meta.join(" · "));
                });
            ui.add_space(2.0);
            ui.horizontal(|ui| {
                legend(ui, egui::Color32::from_rgb(55, 148, 255), "利用率");
                legend(ui, egui::Color32::from_rgb(78, 201, 176), "显存");
            });
            plot(
                ui,
                "gpu_plot",
                168.0,
                &[
                    (
                        "利用率",
                        &self.gpu_util,
                        egui::Color32::from_rgb(55, 148, 255),
                    ),
                    ("显存", &self.gpu_mem, egui::Color32::from_rgb(78, 201, 176)),
                ],
            );
        });
    }

    fn cpu_card(&self, ui: &mut egui::Ui) {
        panel(ui, "处理器", |ui| {
            let Some(sys) = &self.system else {
                ui.label("等待数据…");
                return;
            };
            let cpu = &sys["cpu"];
            ui.label(
                egui::RichText::new(cpu["model"].as_str().unwrap_or("CPU"))
                    .strong()
                    .size(15.0),
            );
            egui::Grid::new("cpu_info")
                .num_columns(2)
                .spacing([14.0, 4.0])
                .show(ui, |ui| {
                    kv(
                        ui,
                        "核心/线程",
                        &format!(
                            "{}C / {}T",
                            cpu["cores"].as_i64().unwrap_or(0),
                            cpu["threads"].as_i64().unwrap_or(0)
                        ),
                    );
                    kv(
                        ui,
                        "当前频率",
                        &format!("{:.0} MHz", cpu["mhz"].as_f64().unwrap_or(0.0)),
                    );
                    kv(
                        ui,
                        "负载 1/5/15m",
                        &format!(
                            "{:.2} / {:.2} / {:.2}",
                            cpu["load1"].as_f64().unwrap_or(0.0),
                            cpu["load5"].as_f64().unwrap_or(0.0),
                            cpu["load15"].as_f64().unwrap_or(0.0)
                        ),
                    );
                    let mem_total = cpu["mem_total_bytes"].as_f64().unwrap_or(0.0);
                    let mem_used = cpu["mem_used_bytes"].as_f64().unwrap_or(0.0);
                    kv(
                        ui,
                        "内存",
                        &format!("{} / {}", fmt_bytes(mem_used), fmt_bytes(mem_total)),
                    );
                    let wsl = if sys["wsl"].as_bool().unwrap_or(false) {
                        " · WSL2"
                    } else {
                        ""
                    };
                    kv(
                        ui,
                        "系统",
                        &format!(
                            "{} / {}{}",
                            sys["os"].as_str().unwrap_or("—"),
                            sys["arch"].as_str().unwrap_or("—"),
                            wsl
                        ),
                    );
                });
            ui.add_space(2.0);
            ui.horizontal(|ui| {
                legend(ui, egui::Color32::from_rgb(215, 186, 125), "利用率");
            });
            plot(
                ui,
                "cpu_plot",
                168.0,
                &[("利用率", &self.cpu, egui::Color32::from_rgb(215, 186, 125))],
            );
        });
    }

    fn service_panel(&self, ui: &mut egui::Ui) {
        panel(ui, "服务状态", |ui| {
            let Some(sys) = &self.system else {
                ui.label("服务未运行");
                return;
            };
            let loaded = format!(
                "{} / {}",
                sys["loaded_count"].as_i64().unwrap_or(0),
                match sys["max_loaded"].as_i64().unwrap_or(0) {
                    0 => "不限".to_string(),
                    n => n.to_string(),
                }
            );
            egui::Grid::new("service_rows")
                .num_columns(6)
                .spacing([12.0, 6.0])
                .show(ui, |ui| {
                    pair(
                        ui,
                        "运行时长",
                        &fmt_uptime(sys["uptime_seconds"].as_f64().unwrap_or(0.0)),
                    );
                    pair(ui, "开机启动", autostart_text(self.autostart_state()));
                    let port = api_addr().rsplit(':').next().unwrap_or("8790");
                    pair(ui, "监听", port);
                    ui.end_row();
                    pair(
                        ui,
                        "认证",
                        if sys["auth"].as_bool().unwrap_or(false) {
                            "已开启"
                        } else {
                            "未开启"
                        },
                    );
                    pair(ui, "已启动", &loaded);
                    pair(ui, "版本", env!("CARGO_PKG_VERSION"));
                    ui.end_row();
                });
        });
    }

    fn storage_panel(&self, ui: &mut egui::Ui) {
        let title = format!("磁盘占用 · 总 {}", fmt_bytes(self.storage_total));
        panel(ui, &title, |ui| {
            if self.storage.is_empty() {
                ui.label("—");
                return;
            }
            egui::Grid::new("storage_rows")
                .num_columns(6)
                .spacing([12.0, 6.0])
                .show(ui, |ui| {
                    for (index, (name, size)) in self.storage.iter().enumerate() {
                        pair(ui, name, size);
                        if (index + 1) % 3 == 0 {
                            ui.end_row();
                        }
                    }
                });
        });
    }

    fn models_page(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if ui
                .selectable_label(self.model_tab == ModelTab::Local, "本地模型")
                .clicked()
            {
                self.model_tab = ModelTab::Local;
            }
            if ui
                .selectable_label(self.model_tab == ModelTab::Hub, "FlashHub")
                .clicked()
            {
                self.model_tab = ModelTab::Hub;
                if self.hub_tags.is_empty() && !self.hub_busy {
                    self.hub_busy = true;
                    spawn_catalog_tags(self.tx.clone(), ui.ctx().clone());
                }
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if self.hub_busy {
                    ui.add(egui::Spinner::new().size(14.0));
                }
            });
        });
        ui.add_space(6.0);
        let page_width = ui.available_width();
        self.load_progress(ui);
        ui.set_max_width(page_width);
        match self.model_tab {
            ModelTab::Local => self.local_models(ui),
            ModelTab::Hub => self.hub_models(ui),
        }
        self.show_model_detail(ui.ctx());
    }

    fn load_progress(&self, ui: &mut egui::Ui) {
        let stale = self
            .load_status_at
            .map(|at| at.elapsed() > Duration::from_secs(4))
            .unwrap_or(false);
        let expired = stale && !self.load_status.contains("失败");
        if !self.loading && (self.load_status.is_empty() || expired) {
            return;
        }
        if !self.loading && !expired {
            ui.ctx().request_repaint_after(Duration::from_millis(500));
        }
        ui.add_space(6.0);
        card_frame(ui).show(ui, |ui| {
            let width = ui.available_width();
            ui.set_max_width(width);
            ui.set_width(width);
            ui.horizontal_wrapped(|ui| {
                if self.loading {
                    ui.add(egui::Spinner::new().size(14.0));
                    if !self.job_verb.is_empty() {
                        ui.label(egui::RichText::new(&self.job_verb).strong());
                    }
                    if !self.job_ref.is_empty() {
                        ui.add(
                            egui::Label::new(
                                egui::RichText::new(&self.job_ref)
                                    .monospace()
                                    .weak()
                                    .small(),
                            )
                            .wrap(),
                        );
                    }
                } else {
                    let color = if self.load_status.contains("失败") {
                        red(ui)
                    } else {
                        green(ui)
                    };
                    ui.add(
                        egui::Label::new(egui::RichText::new(&self.load_status).color(color))
                            .wrap(),
                    );
                    if !self.job_ref.is_empty() {
                        ui.add(
                            egui::Label::new(
                                egui::RichText::new(&self.job_ref)
                                    .monospace()
                                    .weak()
                                    .small(),
                            )
                            .wrap(),
                        );
                    }
                }
            });
            if self.loading {
                ui.add_space(2.0);
                ui.horizontal_wrapped(|ui| {
                    ui.label(
                        egui::RichText::new(&self.load_phase)
                            .strong()
                            .color(accent(ui)),
                    );
                    if !self.load_message.is_empty() {
                        ui.add(
                            egui::Label::new(
                                egui::RichText::new(&self.load_message).weak().small(),
                            )
                            .wrap(),
                        );
                    }
                });
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    let bar = match self.load_pct {
                        Some(pct) => egui::ProgressBar::new((pct / 100.0).clamp(0.0, 1.0))
                            .desired_width(progress_width(ui))
                            .desired_height(8.0)
                            .corner_radius(egui::CornerRadius::same(3))
                            .fill(accent(ui)),
                        None => egui::ProgressBar::new(0.0)
                            .desired_width(progress_width(ui))
                            .desired_height(8.0)
                            .corner_radius(egui::CornerRadius::same(3))
                            .fill(accent(ui))
                            .animate(true),
                    };
                    ui.add(bar);
                    if let Some(pct) = self.load_pct {
                        ui.label(egui::RichText::new(format!("{pct:.0}%")).small().strong());
                    }
                });
            }
        });
    }

    fn local_models(&mut self, ui: &mut egui::Ui) {
        let total_bytes = unique_model_bytes(&self.models);
        let ready = self.models.iter().filter(|m| m.ready()).count();
        let loaded = self.models.iter().filter(|m| m.loaded).count();
        let selected_rows: Vec<ModelRow> = self
            .models
            .iter()
            .filter(|m| self.selected_models.contains(&m.name))
            .cloned()
            .collect();
        let selected_bytes = unique_model_bytes(&selected_rows);
        let selected_count = self.selected_models.len();
        ui.horizontal_wrapped(|ui| {
            stat(ui, "本地模型", &self.models.len().to_string());
            stat(ui, "已就绪", &ready.to_string());
            stat(ui, "已启动", &loaded.to_string());
            stat(ui, "模型占用(去重)", &fmt_bytes(total_bytes));
        });
        ui.add_space(4.0);
        let mut clean_request: Option<Vec<String>> = None;
        ui.horizontal(|ui| {
            ui.label(
                egui::RichText::new(format!(
                    "已选 {} 个 · {}",
                    selected_count,
                    fmt_bytes(selected_bytes)
                ))
                .weak()
                .small(),
            );
            if ui
                .add_enabled(
                    selected_count > 0,
                    egui::Button::new(egui::RichText::new("清理所选").color(red(ui)))
                        .min_size(egui::vec2(110.0, 28.0)),
                )
                .clicked()
            {
                clean_request = Some(self.selected_models.iter().cloned().collect());
            }
            if !self.models_note.is_empty() {
                ui.label(egui::RichText::new(&self.models_note).weak().small());
            }
        });
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            let width = (ui.available_width() - 110.0).max(200.0);
            ui.add_sized(
                [width, 28.0],
                egui::TextEdit::singleline(&mut self.load_ref)
                    .hint_text("flashcli-bundle/<name>:<version>")
                    .vertical_align(egui::Align::Center)
                    .margin(egui::Margin::symmetric(8, 4)),
            );
            let load_clicked = ui
                .add_enabled_ui(!self.loading, |ui| ui.button("加载"))
                .inner
                .clicked();
            if load_clicked {
                let ref_str = self.load_ref.trim().to_string();
                if !ref_str.is_empty() {
                    self.spawn_job_ui(ui.ctx(), ref_str, true, "加载");
                }
            }
        });
        ui.add_space(8.0);
        if self.models.is_empty() {
            ui.label("本地还没有缓存模型。切到「FlashHub」搜索并下载。");
            return;
        }

        let mut selected = self.selected_models.clone();
        let cleanable: Vec<String> = self
            .models
            .iter()
            .filter(|m| !m.loaded)
            .map(|m| m.name.clone())
            .collect();
        let all_selected = !cleanable.is_empty() && cleanable.iter().all(|r| selected.contains(r));
        let shared_weights = shared_weights_set(&self.models);
        let mut toggle_all: Option<bool> = None;
        let mut detail_request = None;
        let mut load_request = None;
        let mut pull_request = None;
        let mut unload_request = None;
        let mut logs_request = None;
        let mut use_request: Option<ModelRow> = None;
        let mut smoke_request: Option<ModelRow> = None;
        let list_height = ui.available_height().max(220.0);
        TableBuilder::new(ui)
            .striped(true)
            .cell_layout(egui::Layout::left_to_right(egui::Align::Center))
            .column(Column::exact(34.0))
            .column(Column::remainder().at_least(120.0))
            .column(Column::exact(74.0))
            .column(Column::exact(82.0))
            .column(Column::exact(104.0))
            .column(Column::exact(84.0))
            .column(Column::exact(64.0))
            .column(Column::exact(150.0))
            .max_scroll_height(list_height)
            .header(26.0, |mut header| {
                header.col(|ui| {
                    let mut all = all_selected;
                    let response =
                        ui.add_enabled(!cleanable.is_empty(), egui::Checkbox::new(&mut all, ""));
                    if response.changed() {
                        toggle_all = Some(all);
                    }
                });
                for title in ["模型", "Bundle", "运行时", "权重", "合计", "状态", "操作"]
                {
                    header.col(|ui| {
                        ui.strong(title);
                    });
                }
            })
            .body(|mut body| {
                for m in &self.models {
                    body.row(32.0, |mut row| {
                        row.col(|ui| {
                            let mut checked = selected.contains(&m.name);
                            let response =
                                ui.add_enabled(!m.loaded, egui::Checkbox::new(&mut checked, ""));
                            if response.changed() {
                                if checked {
                                    selected.insert(m.name.clone());
                                } else {
                                    selected.remove(&m.name);
                                }
                            }
                            if m.loaded {
                                response.on_disabled_hover_text("先停止才能清理");
                            }
                        });
                        row.col(|ui| {
                            let response = ui
                                .add(
                                    egui::Label::new(egui::RichText::new(&m.name).monospace())
                                        .truncate()
                                        .sense(egui::Sense::click()),
                                )
                                .on_hover_text(&m.name);
                            if response.clicked() {
                                detail_request = Some(m.clone());
                            }
                        });
                        row.col(|ui| {
                            size_cell(ui, m.bundle_ready, m.bundle_bytes);
                        });
                        row.col(|ui| {
                            runtime_cell(ui, m);
                        });
                        row.col(|ui| {
                            weights_cell(ui, m, shared_weights.contains(m.weights_key.as_str()));
                        });
                        row.col(|ui| {
                            ui.label(fmt_bytes(m.total_bytes()));
                        });
                        row.col(|ui| {
                            let color = if m.loaded || (m.ready() && m.serve) {
                                green(ui)
                            } else if m.ready() {
                                ui.visuals().weak_text_color()
                            } else {
                                red(ui)
                            };
                            ui.label(egui::RichText::new(m.status()).color(color));
                        });
                        row.col(|ui| {
                            if m.loaded {
                                let clicked = ui
                                    .add_enabled_ui(!self.loading, |ui| table_button(ui, "使用"))
                                    .inner
                                    .clicked();
                                if clicked {
                                    use_request = Some(m.clone());
                                }
                            } else if m.ready() {
                                if m.serve {
                                    let active = self.loading
                                        && self.job_ref == m.name
                                        && self.job_verb == "启动";
                                    let label = if active { "启动中…" } else { "启动" };
                                    let clicked = ui
                                        .add_enabled_ui(!self.loading, |ui| table_button(ui, label))
                                        .inner
                                        .clicked();
                                    if clicked {
                                        load_request = Some(m.name.clone());
                                    }
                                } else {
                                    ui.label(egui::RichText::new("—").weak())
                                        .on_hover_text("在「更多」中使用 Run 冒烟测试");
                                }
                            } else {
                                let active = self.loading
                                    && self.job_ref == m.name
                                    && self.job_verb == "加载";
                                let label = if active { "加载中…" } else { "加载" };
                                let clicked = ui
                                    .add_enabled_ui(!self.loading, |ui| table_button(ui, label))
                                    .inner
                                    .clicked();
                                if clicked {
                                    pull_request = Some(m.name.clone());
                                }
                            }
                            ui.menu_button(egui::RichText::new("更多").size(12.5), |ui| {
                                if ui.button("查看信息").clicked() {
                                    detail_request = Some(m.clone());
                                    ui.close_menu();
                                }
                                if ui.button("查看日志").clicked() {
                                    logs_request = Some(m.name.clone());
                                    ui.close_menu();
                                }
                                if m.ready() && !m.serve && ui.button("Run 冒烟测试").clicked()
                                {
                                    smoke_request = Some(m.clone());
                                    ui.close_menu();
                                }
                                if m.loaded && ui.button("停止").clicked() {
                                    unload_request = Some(m.name.clone());
                                    ui.close_menu();
                                }
                            });
                        });
                    });
                }
            });
        if let Some(all) = toggle_all {
            if all {
                for name in cleanable {
                    selected.insert(name);
                }
            } else {
                for name in cleanable {
                    selected.remove(&name);
                }
            }
        }
        self.selected_models = selected;
        if let Some(m) = detail_request {
            self.model_detail = Some(m);
        }
        if let Some(model) = logs_request {
            self.logs_ref = Some(model);
            self.logs_since = None;
            self.logs_note.clear();
            self.logs_at = None;
            self.logs_busy = true;
            self.tab = Tab::Logs;
            spawn_logs(
                self.tx.clone(),
                ui.ctx().clone(),
                None,
                self.logs_ref.clone(),
            );
        }
        if let Some(m) = use_request {
            self.use_model = Some(m);
        }
        if let Some(m) = smoke_request {
            self.dialog = Some(DialogState {
                title: "Run 冒烟测试".into(),
                message: format!(
                    "将对 {} 执行一次完整 flashcli run 推理。\n\n该操作会加载模型并占用大量 CPU/GPU，可能持续数分钟，期间电脑可能明显卡顿。\n\n确定运行？",
                    m.name
                ),
                action: Pending::Smoke(m.name),
            });
        }
        if let Some(refs) = clean_request {
            let bytes: f64 = self
                .models
                .iter()
                .filter(|m| refs.contains(&m.name))
                .map(|m| m.total_bytes())
                .sum();
            self.dialog = Some(DialogState {
                title: "清理模型缓存".into(),
                message: format!(
                    "将删除所选 {} 个模型的本地 Bundle、运行时、权重和缓存记录（约 {}）。\n与其他模型共享的权重会保留；清理后需要重新加载才能使用；已启动的模型不会被清理。\n确定清理？",
                    refs.len(),
                    fmt_bytes(bytes)
                ),
                action: Pending::Clean(refs),
            });
        }
        if let Some(name) = load_request {
            self.open_model_options(ui.ctx(), name, true);
        }
        if let Some(name) = pull_request {
            self.spawn_job_ui(ui.ctx(), name, true, "加载");
        }
        if let Some(name) = unload_request {
            self.dialog = Some(DialogState {
                title: "停止模型".into(),
                message: format!(
                    "停止后该模型的推理服务将结束，权重和缓存保留。\n确定停止 {name}？"
                ),
                action: Pending::Unload(name),
            });
        }
    }

    fn hub_models(&mut self, ui: &mut egui::Ui) {
        let mut run_search = false;
        ui.horizontal(|ui| {
            let resp = ui.add_sized(
                [240.0, 28.0],
                egui::TextEdit::singleline(&mut self.hub_query)
                    .hint_text("搜索 FlashHub 模型")
                    .vertical_align(egui::Align::Center)
                    .margin(egui::Margin::symmetric(8, 4)),
            );
            let enter = resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
            let tags = self.hub_tags.clone();
            let mut tag_label = "全部分类".to_string();
            for (id, name) in &tags {
                if *id == self.hub_tag {
                    tag_label = name.clone();
                }
            }
            egui::ComboBox::from_id_salt("hub_tag")
                .selected_text(tag_label)
                .width(120.0)
                .show_ui(ui, |ui| {
                    if ui
                        .selectable_value(&mut self.hub_tag, 0, "全部分类")
                        .clicked()
                    {
                        run_search = true;
                    }
                    for (id, name) in &tags {
                        if ui.selectable_value(&mut self.hub_tag, *id, name).clicked() {
                            run_search = true;
                        }
                    }
                });
            if ui.button("搜索").clicked() || enter {
                run_search = true;
            }
        });
        if run_search {
            self.load_hub(ui.ctx());
        }
        if !self.hub_error.is_empty() {
            ui.label(egui::RichText::new(&self.hub_error).color(red(ui)).small());
        }
        ui.add_space(4.0);
        if self.hub_searched {
            ui.label(
                egui::RichText::new(format!("共 {} 个仓库", self.hub_total))
                    .weak()
                    .small(),
            );
        }
        if self.hub_repos.is_empty() {
            if !self.hub_busy {
                if self.hub_searched {
                    ui.label("没有结果。换个关键词或分类再试。");
                } else {
                    ui.label("输入关键词或选择分类后点击「搜索」。");
                }
            }
            return;
        }

        let mut selected = None;
        // Fill the blank area below the filters; keep room for the version
        // panel when a repository is selected.
        let list_height = {
            let available = ui.available_height().max(220.0);
            if self.hub_detail.is_some() {
                (available * 0.45).clamp(200.0, 520.0)
            } else {
                available
            }
        };
        TableBuilder::new(ui)
            .id_salt("hub_repos")
            .striped(true)
            .cell_layout(egui::Layout::left_to_right(egui::Align::Center))
            .column(Column::remainder())
            .column(Column::exact(230.0))
            .column(Column::exact(100.0))
            .column(Column::exact(56.0))
            .column(Column::exact(64.0))
            .max_scroll_height(list_height)
            .header(26.0, |mut header| {
                for title in ["仓库", "模型", "分类", "版本", "下载"] {
                    header.col(|ui| {
                        ui.strong(title);
                    });
                }
            })
            .body(|mut body| {
                for r in &self.hub_repos {
                    body.row(30.0, |mut row| {
                        row.col(|ui| {
                            let label = format!("{}/{}", r.namespace, r.name);
                            if ui
                                .selectable_label(
                                    self.hub_selected == Some(r.id),
                                    egui::RichText::new(label).monospace(),
                                )
                                .clicked()
                            {
                                selected = Some(r.id);
                            }
                        });
                        row.col(|ui| {
                            ui.label(egui::RichText::new(&r.model_name).weak().small());
                        });
                        row.col(|ui| {
                            ui.label(egui::RichText::new(r.tags.join(" ")).small());
                        });
                        row.col(|ui| {
                            ui.label(r.versions.to_string());
                        });
                        row.col(|ui| {
                            ui.label(r.downloads.to_string());
                        });
                    });
                }
            });
        if let Some(id) = selected {
            if self.hub_selected == Some(id) {
                // Clicking the selected repository again collapses its
                // version panel and returns to the full list.
                self.hub_selected = None;
                self.hub_detail = None;
            } else {
                self.select_hub(id, ui.ctx());
            }
        }

        let Some(detail) = self.hub_detail.clone() else {
            return;
        };
        let Some(repo) = self
            .hub_repos
            .iter()
            .find(|r| r.id == detail.repo_id)
            .cloned()
        else {
            return;
        };
        ui.add_space(10.0);
        let mut load_ref = None;
        let mut close_detail = false;
        panel(ui, "版本", |ui| {
            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new(format!("{}/{}", repo.namespace, repo.name))
                        .monospace()
                        .strong(),
                );
                ui.label(egui::RichText::new(&repo.model_name).weak().small());
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("关闭").on_hover_text("收起版本列表").clicked() {
                        close_detail = true;
                    }
                });
            });
            ui.add_space(4.0);
            if detail.versions.is_empty() {
                ui.label("该仓库没有公开版本。");
                return;
            }
            let versions_height = (ui.available_height() - 8.0).max(120.0);
            TableBuilder::new(ui)
                .id_salt("hub_versions")
                .striped(true)
                .cell_layout(egui::Layout::left_to_right(egui::Align::Center))
                .column(Column::exact(110.0))
                .column(Column::exact(110.0))
                .column(Column::exact(70.0))
                .column(Column::exact(110.0))
                .column(Column::remainder())
                .max_scroll_height(versions_height)
                .header(24.0, |mut header| {
                    for title in ["版本", "Bundle 大小", "文件", "状态", "操作"] {
                        header.col(|ui| {
                            ui.strong(title);
                        });
                    }
                })
                .body(|mut body| {
                    for v in &detail.versions {
                        body.row(30.0, |mut row| {
                            row.col(|ui| {
                                ui.monospace(&v.version);
                            });
                            row.col(|ui| {
                                ui.label(fmt_bytes(v.size));
                            });
                            row.col(|ui| {
                                ui.label(v.files.to_string());
                            });
                            row.col(|ui| {
                                ui.label(egui::RichText::new(&v.status).weak().small());
                            });
                            row.col(|ui| {
                                let reference =
                                    format!("{}/{}:{}", repo.namespace, repo.name, v.version);
                                let active = self.loading
                                    && self.job_ref == reference
                                    && self.job_verb == "下载";
                                let label = if active { "下载中…" } else { "下载" };
                                let clicked = ui
                                    .add_enabled_ui(!self.loading, |ui| table_button(ui, label))
                                    .inner
                                    .clicked();
                                if clicked {
                                    load_ref = Some(reference);
                                }
                            });
                        });
                    }
                });
        });
        if close_detail {
            self.hub_selected = None;
            self.hub_detail = None;
        }
        if let Some(reference) = load_ref {
            self.spawn_job_ui(ui.ctx(), reference, true, "下载");
        }
    }

    fn load_hub(&mut self, ctx: &egui::Context) {
        self.hub_busy = true;
        self.hub_searched = true;
        self.hub_error.clear();
        self.hub_detail = None;
        self.hub_selected = None;
        let query = self.hub_query.trim().to_string();
        let tag = if self.hub_tag > 0 {
            Some(self.hub_tag)
        } else {
            None
        };
        spawn_catalog(self.tx.clone(), ctx.clone(), query, tag);
        if self.hub_tags.is_empty() {
            spawn_catalog_tags(self.tx.clone(), ctx.clone());
        }
    }

    fn select_hub(&mut self, id: i64, ctx: &egui::Context) {
        self.hub_selected = Some(id);
        self.hub_detail = None;
        self.hub_busy = true;
        spawn_hub_detail(self.tx.clone(), ctx.clone(), id);
    }

    fn show_model_detail(&mut self, ctx: &egui::Context) {
        let Some(model) = self.model_detail.clone() else {
            return;
        };
        let dark = ctx.style().visuals.dark_mode;
        let mut close = false;
        let mut load = false;
        let mut pull = false;
        let mut options = false;
        modal_backdrop(ctx, dark, &mut close);
        egui::Window::new("model_detail_dialog")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.set_width(560.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("模型详情").size(16.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add(
                                egui::Button::new(egui::RichText::new("×").size(18.0))
                                    .min_size(egui::vec2(28.0, 24.0)),
                            )
                            .clicked()
                        {
                            close = true;
                        }
                    });
                });
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(12.0);

                ui.label(
                    egui::RichText::new(&model.name)
                        .monospace()
                        .strong()
                        .size(14.0),
                );
                ui.add_space(6.0);
                let (status_color, status) = if model.loaded {
                    (green(ui), "已启动")
                } else if model.ready() && model.serve {
                    (green(ui), "就绪")
                } else if model.ready() {
                    (ui.visuals().weak_text_color(), "仅 run")
                } else if model.bundle_ready {
                    (red(ui), "缺权重")
                } else {
                    (red(ui), "缺 Bundle")
                };
                chip(ui, status, status_color);

                ui.add_space(14.0);
                ui.label(
                    egui::RichText::new("存储")
                        .size(12.0)
                        .strong()
                        .color(ui.visuals().weak_text_color()),
                );
                ui.add_space(6.0);
                let runtime_text = if model.runtime_id.is_empty() {
                    "—".to_string()
                } else if model.runtime_bytes > 0.0 {
                    fmt_bytes(model.runtime_bytes)
                } else {
                    "未安装".to_string()
                };
                egui::Grid::new("model_detail")
                    .num_columns(2)
                    .spacing([18.0, 7.0])
                    .show(ui, |ui| {
                        kv(
                            ui,
                            "Bundle",
                            &size_text(model.bundle_ready, model.bundle_bytes),
                        );
                        kv(
                            ui,
                            "权重",
                            &size_text(model.weights_ready, model.weights_bytes),
                        );
                        kv(ui, "运行时", &runtime_text);
                        kv(ui, "模型大小", &fmt_bytes(model.total_bytes()));
                        kv(
                            ui,
                            "服务",
                            if model.serve {
                                "支持 serve"
                            } else {
                                "仅支持 run"
                            },
                        );
                    });
                if !model.runtime_id.is_empty() {
                    ui.add_space(4.0);
                    ui.add(
                        egui::Label::new(
                            egui::RichText::new(format!("runtime: {}", model.runtime_id))
                                .monospace()
                                .weak()
                                .small(),
                        )
                        .wrap(),
                    );
                }

                if model.loaded {
                    ui.add_space(14.0);
                    ui.separator();
                    ui.add_space(12.0);
                    ui.label(
                        egui::RichText::new("运行信息")
                            .size(12.0)
                            .strong()
                            .color(ui.visuals().weak_text_color()),
                    );
                    ui.add_space(6.0);
                    egui::Grid::new("model_runtime")
                        .num_columns(2)
                        .spacing([18.0, 7.0])
                        .show(ui, |ui| {
                            kv(ui, "Endpoint", &model.endpoint);
                            kv(ui, "PID", &model.pid.to_string());
                            kv(ui, "启动时间", &model.loaded_at);
                        });
                }

                if !model.loaded {
                    ui.add_space(16.0);
                    ui.separator();
                    ui.add_space(10.0);
                    ui.horizontal(|ui| {
                        if model.ready() && model.serve {
                            let active = self.loading
                                && self.job_ref == model.name
                                && self.job_verb == "启动";
                            let label = if active { "启动中…" } else { "启动" };
                            let clicked = ui
                                .add_enabled_ui(!self.loading, |ui| primary_button(ui, label))
                                .inner
                                .clicked();
                            if clicked {
                                load = true;
                            }
                            if ui
                                .add_enabled(!self.loading, egui::Button::new("参数"))
                                .clicked()
                            {
                                options = true;
                            }
                        } else if model.ready() {
                            ui.label(
                                egui::RichText::new("该 bundle 仅支持 flashcli run")
                                    .weak()
                                    .small(),
                            );
                        } else {
                            let active = self.loading
                                && self.job_ref == model.name
                                && self.job_verb == "加载";
                            let label = if active { "加载中…" } else { "加载" };
                            let clicked = ui
                                .add_enabled_ui(!self.loading, |ui| button(ui, label))
                                .inner
                                .clicked();
                            if clicked {
                                pull = true;
                            }
                        }
                    });
                }
            });
        if close {
            self.model_detail = None;
        }
        if load {
            self.model_detail = None;
            self.open_model_options(ctx, model.name.clone(), true);
        }
        if options {
            self.model_detail = None;
            self.open_model_options(ctx, model.name.clone(), false);
        }
        if pull {
            self.model_detail = None;
            self.spawn_job_ui(ctx, model.name.clone(), true, "加载");
        }
    }

    fn show_options_dialog(&mut self, ctx: &egui::Context) {
        let Some(mut dlg) = self.options_dialog.take() else {
            return;
        };
        let dark = ctx.style().visuals.dark_mode;
        let mirrored = self.wsl.mirrored;
        let mut close = false;
        let mut save = false;
        let mut reset = false;
        modal_backdrop(ctx, dark, &mut close);
        egui::Window::new("model_options_dialog")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.set_width(640.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("启动参数").size(16.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add(
                                egui::Button::new(egui::RichText::new("×").size(18.0))
                                    .min_size(egui::vec2(28.0, 24.0)),
                            )
                            .clicked()
                        {
                            close = true;
                        }
                    });
                });
                ui.add_space(4.0);
                ui.label(
                    egui::RichText::new(&dlg.reference)
                        .monospace()
                        .weak()
                        .small(),
                );
                ui.add_space(8.0);
                if dlg.loading {
                    ui.horizontal(|ui| {
                        ui.spinner();
                        ui.label("正在读取 bundle 的 serve_options…");
                    });
                    return;
                }
                if !dlg.error.is_empty() {
                    ui.label(egui::RichText::new(&dlg.error).color(red(ui)));
                    ui.add_space(6.0);
                }
                egui::Grid::new("serve_host_grid")
                    .num_columns(2)
                    .spacing([12.0, 6.0])
                    .show(ui, |ui| {
                        ui.label("监听地址");
                        let host_hint = dlg.default_host.clone();
                        ui.add(
                            egui::TextEdit::singleline(&mut dlg.host)
                                .hint_text(host_hint)
                                .desired_width(220.0),
                        );
                        ui.end_row();
                        ui.label("端口");
                        ui.add(
                            egui::TextEdit::singleline(&mut dlg.port)
                                .hint_text("0 = 自动（任意空闲端口）")
                                .desired_width(220.0),
                        );
                        ui.end_row();
                    });
                ui.label(
                    egui::RichText::new("0.0.0.0 = 所有网卡；127.0.0.1 = 仅本机。")
                        .weak()
                        .small(),
                );
                if dlg.host.trim() == "0.0.0.0" {
                    if mirrored {
                        ui.label(
                            egui::RichText::new(
                                "已开启 WSL 镜像网络：局域网可通过 Windows 本机 IP 访问；防火墙端口由设置中的“防火墙端口”决定。公网还需路由器映射和 Public 规则。",
                            )
                            .color(green(ui))
                            .small(),
                        );
                    } else {
                        ui.label(
                            egui::RichText::new(
                                "当前 WSL 为 NAT 模式：0.0.0.0 仅 Windows 本机 localhost 可达。局域网 IP 访问请在“设置 → WSL 资源”开启局域网访问；公网还需额外放行 Public。",
                            )
                            .color(egui::Color32::from_rgb(215, 186, 125))
                            .small(),
                        );
                    }
                }
                if dlg.restart_required {
                    ui.label(
                        egui::RichText::new("模型正在运行：保存后需停止并重新启动才会生效。")
                            .color(egui::Color32::from_rgb(215, 186, 125))
                            .small(),
                    );
                }
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(6.0);
                egui::ScrollArea::vertical()
                    .max_height(330.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        if dlg.options.is_empty() {
                            ui.label("该 bundle 未声明 serve_options。");
                        }
                        for opt in &mut dlg.options {
                            ui.horizontal(|ui| {
                                ui.label(egui::RichText::new(&opt.name).strong());
                                ui.label(
                                    egui::RichText::new(format!("--{}", opt.flag))
                                        .monospace()
                                        .weak()
                                        .small(),
                                );
                                ui.label(
                                    egui::RichText::new(format!("({})", opt.kind))
                                        .weak()
                                        .small(),
                                );
                            });
                            if !opt.help.is_empty() {
                                ui.label(egui::RichText::new(&opt.help).weak().small());
                            }
                            let hint = if opt.default.is_empty() {
                                "留空 = bundle 默认值".to_string()
                            } else {
                                format!("留空 = 默认：{}", opt.default)
                            };
                            let width = ui.available_width();
                            ui.add(
                                egui::TextEdit::singleline(&mut opt.value)
                                    .hint_text(hint)
                                    .desired_width(width),
                            );
                            ui.add_space(6.0);
                        }
                    });
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    if dlg.start_after_save {
                        if ui
                            .add_enabled(!dlg.saving, egui::Button::new("使用默认值启动"))
                            .clicked()
                        {
                            reset = true;
                            save = true;
                        }
                    } else if ui
                        .add_enabled(!dlg.saving, egui::Button::new("恢复默认"))
                        .clicked()
                    {
                        reset = true;
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        let label = if dlg.start_after_save {
                            "保存并启动"
                        } else {
                            "保存"
                        };
                        if ui
                            .add_enabled_ui(!dlg.saving, |ui| primary_button(ui, label))
                            .inner
                            .clicked()
                        {
                            save = true;
                        }
                        if dlg.saving {
                            ui.spinner();
                            ui.label(if dlg.start_after_save {
                                "保存并启动…"
                            } else {
                                "保存中…"
                            });
                        }
                    });
                });
            });
        if close {
            self.options_dialog = None;
            return;
        }
        if reset {
            dlg.host = dlg.default_host.clone();
            dlg.port = "0".to_string();
            for opt in &mut dlg.options {
                opt.value.clear();
            }
        }
        if save {
            let port = match dlg.port.trim() {
                "" | "0" => 0u16,
                text => match text.parse::<u16>() {
                    Ok(p) => p,
                    Err(_) => {
                        dlg.error = "端口必须是 0-65535 的整数（0 = 自动）".to_string();
                        self.options_dialog = Some(dlg);
                        return;
                    }
                },
            };
            let mut values = HashMap::new();
            for opt in &dlg.options {
                let value = opt.value.trim();
                if !value.is_empty() {
                    values.insert(opt.name.clone(), value.to_string());
                }
            }
            dlg.saving = true;
            dlg.error.clear();
            spawn_save_model_options(
                self.tx.clone(),
                ctx.clone(),
                dlg.reference.clone(),
                dlg.host.trim().to_string(),
                port,
                values,
                dlg.start_after_save,
            );
        }
        self.options_dialog = Some(dlg);
    }

    fn open_model_options(&mut self, ctx: &egui::Context, reference: String, start_after_save: bool) {
        self.options_dialog = Some(OptionsDialog {
            reference: reference.clone(),
            host: String::new(),
            default_host: "0.0.0.0".to_string(),
            public_host: String::new(),
            port: "0".to_string(),
            options: Vec::new(),
            loading: true,
            saving: false,
            error: String::new(),
            restart_required: false,
            start_after_save,
        });
        spawn_model_options(self.tx.clone(), ctx.clone(), reference);
    }

    fn show_use_dialog(&mut self, ctx: &egui::Context) {
        let Some(model) = self.use_model.clone() else {
            return;
        };
        if self.dialog.is_some() {
            return;
        }
        let dark = ctx.style().visuals.dark_mode;
        let mut close = false;
        let mut copied = false;
        let mut copied_example = false;
        let mut smoke = false;
        modal_backdrop(ctx, dark, &mut close);
        egui::Window::new("use_model_dialog")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.set_width(620.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("使用模型").size(17.0).strong());
                    ui.with_layout(
                        egui::Layout::right_to_left(egui::Align::Center),
                        |ui| {
                            if ui.button("×").clicked() {
                                close = true;
                            }
                        },
                    );
                });
                ui.add_space(4.0);
                ui.add(
                    egui::Label::new(egui::RichText::new(&model.name).monospace().weak())
                        .wrap(),
                );
                ui.add_space(12.0);
                ui.label(
                    egui::RichText::new("目标 Serve 地址")
                        .size(12.0)
                        .strong()
                        .color(ui.visuals().weak_text_color()),
                );
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    ui.add(
                        egui::Label::new(
                            egui::RichText::new(&model.endpoint).monospace().size(14.0),
                        )
                        .wrap(),
                    );
                    if button(ui, "复制地址").clicked() {
                        ui.ctx().copy_text(model.endpoint.clone());
                        copied = true;
                    }
                });
                ui.add_space(12.0);
                let models_url = format!("{}/v1/models", model.endpoint.trim_end_matches('/'));
                let chat_url = format!(
                    "{}/v1/chat/completions",
                    model.endpoint.trim_end_matches('/')
                );
                let example = format!(
                    "curl {models_url}\n\ncurl {chat_url} -H 'Content-Type: application/json' \\\n  -d '{{\"model\":\"<model-id>\",\"messages\":[{{\"role\":\"user\",\"content\":\"Hello\"}}]}}'"
                );
                ui.horizontal(|ui| {
                    ui.label(
                        egui::RichText::new("OpenAI 兼容接口")
                            .size(12.0)
                            .strong()
                            .color(ui.visuals().weak_text_color()),
                    );
                    ui.with_layout(
                        egui::Layout::right_to_left(egui::Align::Center),
                        |ui| {
                            if button(ui, "复制示例").clicked() {
                                ui.ctx().copy_text(example.clone());
                                copied_example = true;
                            }
                        },
                    );
                });
                ui.add_space(4.0);
                ui.add(
                    egui::Label::new(
                        egui::RichText::new(&example).monospace().small(),
                    )
                    .selectable(true),
                );
                ui.add_space(4.0);
                ui.label(
                    egui::RichText::new("模型 ID 以 /v1/models 返回值为准")
                        .weak()
                        .small(),
                );
                ui.add_space(14.0);
                ui.separator();
                ui.add_space(10.0);
                ui.horizontal(|ui| {
                    if button(ui, "请求测试").clicked() {
                        smoke = true;
                    }
                    if button(ui, "打开 API 文档").clicked() {
                        let _ = webbrowser::open(&format!(
                            "{}/docs",
                            model.endpoint.trim_end_matches('/')
                        ));
                    }
                    if button(ui, "打开模型列表").clicked() {
                        let _ = webbrowser::open(&models_url);
                    }
                    if button(ui, "打开本地控制台").clicked() {
                        let _ = webbrowser::open(&format!("{}/", api_base().trim_end_matches('/')));
                    }
                });
            });
        if copied_example {
            self.op_note = Some(("已复制使用示例".into(), true, Instant::now()));
        } else if copied {
            self.op_note = Some(("已复制 Serve 地址".into(), true, Instant::now()));
        }
        if close {
            self.use_model = None;
        }
        if smoke {
            self.use_model = None;
            self.pending_smoke_cancel = false;
            self.smoke = Some(SmokeState {
                title: format!("请求测试 · {}", model.name),
                running: true,
                ok: true,
                cancelled: false,
                job_id: String::new(),
                log: "测试运行中…\n".into(),
            });
            spawn_smoke(self.tx.clone(), ctx.clone(), model.name.clone());
        }
    }

    fn logs_page(&mut self, ui: &mut egui::Ui) {
        let mut clear = false;
        let mut reset = false;
        let mut export = false;
        let model_log = self.logs_ref.is_some();
        ui.horizontal(|ui| {
            if let Some(model) = self.logs_ref.clone() {
                ui.label(egui::RichText::new("模型日志").strong());
                ui.add(
                    egui::Label::new(egui::RichText::new(&model).monospace().weak().small()).wrap(),
                );
                if ui.button("返回服务日志").clicked() {
                    self.logs_ref = None;
                    self.logs_since = None;
                    self.logs_note.clear();
                    self.logs_at = None;
                    self.logs_busy = true;
                    spawn_logs(self.tx.clone(), ui.ctx().clone(), None, None);
                }
            } else {
                ui.label(egui::RichText::new("服务日志").strong());
            }
            ui.label(
                egui::RichText::new(if !model_log && self.logs_since.is_some() {
                    "仅显示清空后的新日志"
                } else {
                    "最近 300 行"
                })
                .weak()
                .small(),
            );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("另存为…").clicked() {
                    export = true;
                }
                if !model_log {
                    if ui.button("清空").clicked() {
                        clear = true;
                    }
                    if self.logs_since.is_some() && ui.button("最新 300 行").clicked() {
                        reset = true;
                    }
                }
            });
        });
        if !self.logs_note.is_empty() {
            ui.add_space(4.0);
            ui.label(egui::RichText::new(&self.logs_note).weak().small());
        }
        if clear {
            self.logs.clear();
            self.logs_since = Some(now_epoch());
            self.logs_note = "已清空当前显示，仅显示之后的新日志。".into();
            self.logs_at = None;
        }
        if reset {
            self.logs_since = None;
            self.logs_note.clear();
            self.logs_at = None;
        }
        if export {
            if let Some(path) = rfd::FileDialog::new()
                .set_title("保存完整日志")
                .set_file_name(if self.logs_ref.is_some() {
                    "model.log"
                } else {
                    "flashserver.log"
                })
                .add_filter("日志", &["log", "txt"])
                .save_file()
            {
                spawn_export_logs(
                    self.tx.clone(),
                    ui.ctx().clone(),
                    path,
                    self.logs_ref.clone(),
                );
            }
        }
        ui.add_space(8.0);
        card_frame(ui)
            .inner_margin(egui::Margin::symmetric(12, 10))
            .show(ui, |ui| {
                ui.set_min_width(ui.available_width());
                ui.set_min_height(ui.available_height());
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .stick_to_bottom(true)
                    .show(ui, |ui| {
                        ui.add(
                            egui::Label::new(
                                egui::RichText::new(&self.logs).monospace().size(13.0),
                            )
                            .wrap(),
                        );
                    });
            });
    }

    fn settings_page(&mut self, ui: &mut egui::Ui) {
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                panel(ui, "服务", |ui| {
                    egui::Grid::new("service_rows")
                        .num_columns(2)
                        .spacing([18.0, 6.0])
                        .show(ui, |ui| {
                            kv(ui, "当前状态", if self.system.is_some() { "运行中" } else { "已停止" });
                            kv(
                                ui,
                                "开机启动",
                                autostart_text(self.autostart_state()),
                            );
                            kv(ui, "监听地址", api_addr());
                        });
                    ui.add_space(8.0);
                    let running = self.system.is_some();
                    let autostart = self.autostart_state().unwrap_or(false);
                    ui.horizontal(|ui| {
                        if running {
                            if danger_button(ui, "停止服务").clicked() {
                                self.dialog = Some(DialogState {
                                    title: "停止服务".into(),
                                    message: "停止后正在启动/运行的模型会中断，已启动模型将不可用。\n确定停止？".into(),
                                    action: Pending::StopService,
                                });
                            }
                        } else if primary_button(ui, "启动服务").clicked() {
                            spawn_action(self.tx.clone(), ui.ctx().clone(), Action::Start);
                        }
                        ui.add_space(8.0);
                        if autostart {
                            if danger_button(ui, "禁用开机启动").clicked() {
                                self.dialog = Some(DialogState {
                                    title: "禁用开机启动".into(),
                                    message: "只取消开机启动，当前运行的服务不受影响。\n确定继续？".into(),
                                    action: Pending::DisableAutostart,
                                });
                            }
                        } else if button(ui, "启用开机启动").clicked() {
                            spawn_action(self.tx.clone(), ui.ctx().clone(), Action::EnableAutostart);
                        }
                    });
                });

                ui.add_space(10.0);
                let wsl_now = self
                    .system
                    .as_ref()
                    .map(|sys| {
                        let cpu = &sys["cpu"];
                        format!(
                            "当前 WSL：{} 线程 / {} 内存",
                            cpu["threads"].as_i64().unwrap_or(0),
                            fmt_bytes(cpu["mem_total_bytes"].as_f64().unwrap_or(0.0))
                        )
                    })
                    .unwrap_or_else(|| "服务未运行，无法读取当前 WSL 资源。".to_string());
                let wsl_path = wslconfig_path()
                    .map(|p| p.display().to_string())
                    .unwrap_or_default();
                let service_running = self.system.is_some();
                let mut apply_wsl = false;
                panel(ui, "WSL 资源", |ui| {
                    ui.label(
                        egui::RichText::new(format!(
                            "全局配置 {}（影响所有 WSL2 发行版）",
                            wsl_path
                        ))
                        .weak()
                        .small(),
                    );
                    ui.add_space(4.0);
                    egui::Grid::new("wsl_resource_rows")
                        .num_columns(2)
                        .spacing([14.0, 6.0])
                        .show(ui, |ui| {
                            ui.label("内存上限");
                            ui.add(
                                egui::TextEdit::singleline(&mut self.wsl.memory)
                                    .hint_text("默认：物理内存 50%（如 16GB）")
                                    .desired_width(220.0),
                            );
                            ui.end_row();
                            ui.label("CPU 核心");
                            ui.add(
                                egui::TextEdit::singleline(&mut self.wsl.processors)
                                    .hint_text("默认：全部逻辑处理器")
                                    .desired_width(220.0),
                            );
                            ui.end_row();
                            ui.label("Swap");
                            ui.add(
                                egui::TextEdit::singleline(&mut self.wsl.swap)
                                    .hint_text("默认：内存的 25%（0 关闭）")
                                    .desired_width(220.0),
                            );
                            ui.end_row();
                            ui.label("防火墙端口");
                            ui.add(
                                egui::TextEdit::singleline(&mut self.wsl_ports)
                                    .hint_text("留空 = 所有 TCP 端口；如 18000-18999")
                                    .desired_width(220.0),
                            );
                            ui.end_row();
                        });
                    ui.add_space(4.0);
                    ui.checkbox(
                        &mut self.wsl.mirrored,
                        "局域网访问（WSL 镜像网络，host=0.0.0.0 可通过本机 IP 访问）",
                    );
                    ui.label(
                        egui::RichText::new(if !self.wsl.mirrored {
                            "默认 NAT：模型只在 Windows 本机 localhost 可达；局域网访问请勾选上面的选项（公网还需 Public 规则和路由器映射）。"
                        } else if self.wsl_ports.trim().is_empty() {
                            "未设置端口范围：应用时会放行所有 TCP 端口（Private/Domain），仅建议在受信网络使用。"
                        } else {
                            "应用时会放行输入的 TCP 端口范围（Private/Domain）。"
                        })
                        .weak()
                        .small(),
                    );
                    ui.add_space(6.0);
                    ui.horizontal(|ui| {
                        if ui.button("应用并重启 WSL").clicked() {
                            apply_wsl = true;
                        }
                        ui.label(egui::RichText::new(&wsl_now).weak().small());
                    });
                    ui.label(
                        egui::RichText::new(
                            "修改后需要重启 WSL 才生效；正在运行的模型会中断。留空表示使用 WSL 默认值。",
                        )
                        .weak()
                        .small(),
                    );
                });
                if apply_wsl {
                    if !valid_wsl_size(&self.wsl.memory)
                        || !valid_wsl_size(&self.wsl.swap)
                        || !valid_processors(&self.wsl.processors)
                        || !valid_firewall_ports(&self.wsl_ports)
                    {
                        self.op_note = Some((
                            "WSL 资源格式无效：内存/Swap 用 16GB / 8GB / 0，CPU 核心为 1-256，防火墙端口用 18000-18999 / 8000,8001".into(),
                            false,
                            Instant::now(),
                        ));
                    } else {
                        save_settings(&Settings {
                            dark: self.dark,
                            wsl_ports: self.wsl_ports.clone(),
                        });
                        if service_running {
                            self.wsl_pending = Some(self.wsl.clone());
                            self.wsl_pending_ports = self.wsl_ports.trim().to_string();
                            self.dialog = Some(DialogState {
                                title: "重启 WSL".into(),
                                message: "应用 WSL 资源/网络设置需要重启 WSL，正在运行的模型会中断。\n完成后 FlashServer 会自动启动。\n确定继续？".into(),
                                action: Pending::ApplyWsl,
                            });
                        } else {
                            self.op_busy = Some("正在应用 WSL 配置…".into());
                            spawn_apply_wsl(
                                self.tx.clone(),
                                ui.ctx().clone(),
                                self.wsl.clone(),
                                false,
                                self.wsl_ports.trim().to_string(),
                            );
                        }
                    }
                }

                ui.add_space(10.0);
                panel(ui, "下载源", |ui| {
                    let state = self.mirror_enabled;
                    let can_edit = self.system.is_some() && state.is_some() && !self.loading;
                    let mut checked = state.unwrap_or(false);
                    let changed = ui
                        .add_enabled_ui(can_edit, |ui| {
                            ui.checkbox(&mut checked, "使用国内镜像（pip / HuggingFace / GitHub）")
                        })
                        .inner
                        .changed();
                    if changed {
                        spawn_set_mirror(self.tx.clone(), ui.ctx().clone(), checked);
                    }
                    ui.label(
                        egui::RichText::new(
                            "pip 使用阿里云，HuggingFace 使用 hf-mirror，GitHub 使用 gh-proxy / Gitee；修改后新下载立即生效。",
                        )
                        .weak()
                        .small(),
                    );
                    if self.system.is_none() {
                        ui.label(
                            egui::RichText::new("服务未运行，无法读取或修改镜像设置。")
                                .weak()
                                .small(),
                        );
                    } else if self.loading {
                        ui.label(
                            egui::RichText::new("下载/启动进行中，完成后再修改镜像设置。")
                                .weak()
                                .small(),
                        );
                    } else if state.is_none() {
                        ui.label(egui::RichText::new("正在读取镜像设置…").weak().small());
                    }
                });

                ui.add_space(10.0);
                panel(ui, "存储", |ui| {
                    ui.horizontal(|ui| {
                        ui.label(
                            egui::RichText::new("共享缓存：下载缓存 / Python / uv 工具")
                                .weak()
                                .small(),
                        );
                        ui.with_layout(
                            egui::Layout::right_to_left(egui::Align::Center),
                            |ui| {
                                if ui
                                    .add(
                                        egui::Button::new(
                                            egui::RichText::new("清理缓存…").color(red(ui)),
                                        )
                                        .min_size(egui::vec2(120.0, 28.0)),
                                    )
                                    .clicked()
                                {
                                    self.cache_dialog = true;
                                    self.cache_selected.clear();
                                    self.cache_selected.insert("cache".to_string());
                                }
                            },
                        );
                    });
                    if !self.storage_note.is_empty() {
                        ui.add_space(4.0);
                        ui.label(egui::RichText::new(&self.storage_note).weak().small());
                    }
                });

                ui.add_space(10.0);
                panel(ui, "外观", |ui| {
                    ui.horizontal(|ui| {
                        ui.label("主题");
                        let dark = self.dark;
                        if ui.selectable_label(dark, "深色").clicked() && !dark {
                            self.set_theme(ui.ctx(), true);
                        }
                        if ui.selectable_label(!dark, "浅色").clicked() && dark {
                            self.set_theme(ui.ctx(), false);
                        }
                        ui.label(egui::RichText::new("（Ctrl+T 快速切换）").weak().small());
                    });
                });

                ui.add_space(10.0);
                panel(ui, "关于", |ui| {
                    ui.label(format!("FlashServer Desktop v{}", env!("CARGO_PKG_VERSION")));
                    ui.add_space(6.0);
                    ui.horizontal(|ui| {
                        if button(ui, "API 文档").clicked() {
                            let _ = webbrowser::open(&format!("{}/docs", api_base()));
                        }
                        ui.add_space(8.0);
                        if danger_button(ui, "退出客户端").clicked() {
                            self.dialog = Some(DialogState {
                                title: "退出客户端".into(),
                                message: "退出客户端不会停止 FlashServer 服务。\n确定退出？".into(),
                                action: Pending::Quit,
                            });
                        }
                    });
                });
            });
    }

    fn set_theme(&mut self, ctx: &egui::Context, dark: bool) {
        if self.dark != dark {
            self.dark = dark;
            apply_theme(ctx, dark);
            save_settings(&Settings {
                dark,
                wsl_ports: self.wsl_ports.clone(),
            });
        }
    }

    fn show_cache_dialog(&mut self, ctx: &egui::Context) {
        if !self.cache_dialog || self.dialog.is_some() || self.model_detail.is_some() {
            return;
        }
        let dark = ctx.style().visuals.dark_mode;
        let targets = [(
            "cache",
            "共享缓存",
            "下载缓存 / Python 基础解释器 / uv 工具；清理后下次加载会重新下载",
            "~/.flashcli/{cache,python,tools}",
        )];
        let mut selected = self.cache_selected.clone();
        let mut close = false;
        let mut confirm = false;
        modal_backdrop(ctx, dark, &mut close);
        egui::Window::new("cache_clean_dialog")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.set_width(540.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("清理缓存").size(16.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add(
                                egui::Button::new(egui::RichText::new("×").size(18.0))
                                    .min_size(egui::vec2(28.0, 24.0)),
                            )
                            .clicked()
                        {
                            close = true;
                        }
                    });
                });
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(12.0);
                ui.label("选择要删除的共享缓存：");
                ui.add_space(6.0);
                for &(key, label, description, path) in &targets {
                    let size = self.storage_sizes.get(key).copied().unwrap_or(0.0);
                    let mut checked = selected.contains(key);
                    ui.horizontal(|ui| {
                        let response = ui.add(egui::Checkbox::new(&mut checked, ""));
                        if response.changed() {
                            if checked {
                                selected.insert(key.to_string());
                            } else {
                                selected.remove(key);
                            }
                        }
                        ui.label(egui::RichText::new(label).strong())
                            .on_hover_text(format!("路径: {path}"));
                        ui.label(egui::RichText::new(description).weak().small());
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.label(fmt_bytes(size));
                        });
                    });
                }
                ui.add_space(10.0);
                ui.separator();
                ui.add_space(10.0);
                let total: f64 = targets
                    .iter()
                    .filter(|(key, _, _, _)| selected.contains(*key))
                    .map(|(key, _, _, _)| self.storage_sizes.get(*key).copied().unwrap_or(0.0))
                    .sum();
                ui.label(egui::RichText::new(format!("将释放约 {}", fmt_bytes(total))).strong());
                ui.label(
                    egui::RichText::new(
                        "模型 Bundle/权重/运行时不受影响；共享缓存与运行时可能通过硬链接共享文件，实际释放量可能小于显示值。清理后下次加载会重新下载缓存。",
                    )
                    .weak()
                    .small(),
                );
                ui.add_space(12.0);
                ui.separator();
                ui.add_space(10.0);
                ui.horizontal(|ui| {
                    ui.add_space((ui.available_width() - 200.0).max(0.0));
                    if button(ui, "取消").clicked() {
                        close = true;
                    }
                    ui.add_space(8.0);
                    let enabled = !selected.is_empty();
                    let response = ui.add_enabled(
                        enabled,
                        egui::Button::new(egui::RichText::new("清理").color(egui::Color32::WHITE))
                            .fill(egui::Color32::from_rgb(176, 54, 48))
                            .min_size(egui::vec2(96.0, 28.0)),
                    );
                    if response.clicked() {
                        confirm = true;
                    }
                });
            });
        self.cache_selected = selected;
        if close {
            self.cache_dialog = false;
        }
        if confirm && !self.cache_selected.is_empty() {
            let targets: Vec<String> = self.cache_selected.iter().cloned().collect();
            self.cache_dialog = false;
            self.storage_note.clear();
            spawn_storage_clean(self.tx.clone(), ctx.clone(), targets);
        }
    }

    fn show_busy_overlay(&self, ctx: &egui::Context) {
        let Some(label) = &self.op_busy else {
            return;
        };
        let dark = ctx.style().visuals.dark_mode;
        let mut ignored = false;
        modal_backdrop(ctx, dark, &mut ignored);
        egui::Window::new("busy_overlay")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.set_width(300.0);
                ui.horizontal(|ui| {
                    ui.add(egui::Spinner::new().size(18.0));
                    ui.label(egui::RichText::new(label).size(14.0));
                });
            });
    }

    fn show_toast(&self, ctx: &egui::Context) {
        let Some((message, ok, at)) = &self.op_note else {
            return;
        };
        if at.elapsed() > Duration::from_secs(4) {
            return;
        }
        let dark = ctx.style().visuals.dark_mode;
        let color = if *ok {
            if dark {
                egui::Color32::from_rgb(78, 201, 176)
            } else {
                egui::Color32::from_rgb(16, 124, 16)
            }
        } else if dark {
            egui::Color32::from_rgb(244, 135, 113)
        } else {
            egui::Color32::from_rgb(196, 43, 28)
        };
        let font = egui::FontId::proportional(13.0);
        let text_width =
            ctx.fonts(|fonts| fonts.layout_no_wrap(message.clone(), font, color).size().x);
        let max_width = (ctx.screen_rect().width() - 96.0).min(720.0).max(180.0);
        let width = (text_width + 4.0).clamp(180.0, max_width);
        egui::Area::new(egui::Id::new("op_toast"))
            .order(egui::Order::Foreground)
            .anchor(egui::Align2::CENTER_BOTTOM, [0.0, -24.0])
            .interactable(false)
            .show(ctx, |ui| {
                ui.set_max_width(width);
                egui::Frame::NONE
                    .fill(card_fill_dark(dark))
                    .stroke(card_stroke_dark(dark))
                    .corner_radius(6)
                    .inner_margin(egui::Margin::symmetric(14, 8))
                    .show(ui, |ui| {
                        ui.set_width(width);
                        ui.add(
                            egui::Label::new(egui::RichText::new(message).color(color).size(13.0))
                                .wrap(),
                        );
                    });
            });
    }

    fn show_smoke_dialog(&mut self, ctx: &egui::Context) {
        let Some(smoke) = self.smoke.as_mut() else {
            return;
        };
        let dark = ctx.style().visuals.dark_mode;
        let mut close = false;
        let mut copy = false;
        let mut cancel = false;
        egui::Window::new("smoke_dialog")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(true)
            .default_width(760.0)
            .show(ctx, |ui| {
                ui.set_min_width(640.0);
                ui.set_max_width(920.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new(&smoke.title).size(16.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add(
                                egui::Button::new(egui::RichText::new("×").size(18.0))
                                    .min_size(egui::vec2(28.0, 24.0)),
                            )
                            .clicked()
                        {
                            if smoke.running && !smoke.cancelled {
                                cancel = true;
                            }
                            close = true;
                        }
                    });
                });
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(8.0);
                if smoke.running {
                    ui.horizontal(|ui| {
                        ui.add(egui::Spinner::new().size(16.0));
                        ui.label(if smoke.cancelled {
                            "正在取消测试…"
                        } else {
                            "测试运行中…"
                        });
                    });
                } else if smoke.cancelled {
                    ui.label(egui::RichText::new("测试已取消").weak().strong());
                } else {
                    let color = if smoke.ok { green(ui) } else { red(ui) };
                    ui.label(
                        egui::RichText::new(if smoke.ok {
                            "测试通过"
                        } else {
                            "测试失败"
                        })
                        .color(color)
                        .strong(),
                    );
                }
                ui.add_space(6.0);
                egui::ScrollArea::vertical()
                    .max_height(420.0)
                    .auto_shrink([false, false])
                    .stick_to_bottom(true)
                    .show(ui, |ui| {
                        ui.add(
                            egui::Label::new(egui::RichText::new(&smoke.log).monospace().small())
                                .selectable(true)
                                .wrap(),
                        );
                    });
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    if smoke.running && !smoke.cancelled {
                        if button(ui, "取消测试").clicked() {
                            cancel = true;
                        }
                    } else if !smoke.running {
                        if button(ui, "复制日志").clicked() {
                            copy = true;
                        }
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        let label = if smoke.running && !smoke.cancelled {
                            "取消并关闭"
                        } else {
                            "关闭"
                        };
                        if button(ui, label).clicked() {
                            if smoke.running && !smoke.cancelled {
                                cancel = true;
                            }
                            close = true;
                        }
                    });
                });
            });
        if copy {
            ctx.copy_text(smoke.log.clone());
            self.op_note = Some(("测试日志已复制".into(), true, Instant::now()));
        }
        if cancel {
            smoke.cancelled = true;
            smoke.log.push_str("正在取消测试…\n");
            if smoke.job_id.is_empty() {
                self.pending_smoke_cancel = true;
            } else {
                spawn_cancel_job(ctx.clone(), smoke.job_id.clone());
            }
        }
        if close {
            self.smoke = None;
        }
    }

    fn show_dialog(&mut self, ctx: &egui::Context) {
        let Some(dialog) = self.dialog.as_ref() else {
            return;
        };
        let title = dialog.title.clone();
        let message = dialog.message.clone();
        let destructive = matches!(
            dialog.action,
            Pending::StopService
                | Pending::DisableAutostart
                | Pending::Unload(_)
                | Pending::Clean(_)
                | Pending::Smoke(_)
        );
        let dark = ctx.style().visuals.dark_mode;
        let mut close = false;
        let mut confirm = false;
        modal_backdrop(ctx, dark, &mut close);
        egui::Window::new("confirm_dialog")
            .title_bar(false)
            .order(egui::Order::Foreground)
            .frame(dialog_frame(dark))
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(false)
            .show(ctx, |ui| {
                ui.set_width(440.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new(&title).size(16.0).strong());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui
                            .add(
                                egui::Button::new(egui::RichText::new("×").size(18.0))
                                    .min_size(egui::vec2(28.0, 24.0)),
                            )
                            .clicked()
                        {
                            close = true;
                        }
                    });
                });
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(12.0);
                ui.label(&message);
                ui.add_space(16.0);
                ui.separator();
                ui.add_space(10.0);
                ui.horizontal(|ui| {
                    ui.add_space((ui.available_width() - 200.0).max(0.0));
                    if button(ui, "取消").clicked() {
                        close = true;
                    }
                    ui.add_space(8.0);
                    let response = if destructive {
                        destructive_button(ui, "确认")
                    } else {
                        primary_button(ui, "确认")
                    };
                    if response.clicked() {
                        confirm = true;
                    }
                });
            });
        if close {
            self.dialog = None;
        }
        if confirm {
            let dialog = self.dialog.take().unwrap();
            match dialog.action {
                Pending::StopService => {
                    spawn_action(self.tx.clone(), ctx.clone(), Action::Stop);
                }
                Pending::DisableAutostart => {
                    spawn_action(
                        self.tx.clone(),
                        ctx.clone(),
                        Action::DisableAutostart {
                            keep_stopped: self.system.is_none(),
                        },
                    );
                }
                Pending::Unload(name) => {
                    spawn_unload(self.tx.clone(), ctx.clone(), name);
                }
                Pending::Clean(refs) => {
                    spawn_clean(self.tx.clone(), ctx.clone(), refs);
                }
                Pending::Smoke(name) => {
                    self.start_smoke(ctx, name);
                }
                Pending::ApplyWsl => {
                    if let Some(cfg) = self.wsl_pending.take() {
                        self.op_busy = Some("正在重启 WSL…".into());
                        self.system = None;
                        let ports = self.wsl_pending_ports.clone();
                        spawn_apply_wsl(self.tx.clone(), ctx.clone(), cfg, true, ports);
                    }
                }
                Pending::Quit => {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.drain_events(ctx);
        if !self.closing && ctx.input(|i| i.viewport().close_requested()) {
            self.closing = true;
            if let Some(smoke) = &self.smoke {
                if smoke.running && !smoke.job_id.is_empty() {
                    let _ = post_json_timeout(
                        &format!("/v1/jobs/{}/cancel", smoke.job_id),
                        &serde_json::json!({}),
                        2,
                    );
                }
            }
        }
        ctx.request_repaint_after(Duration::from_millis(500));
        if ctx.input(|i| i.modifiers.command && i.key_pressed(egui::Key::T)) {
            let dark = !self.dark;
            self.set_theme(ctx, dark);
        }
        if self.tab == Tab::Logs && !self.logs_busy {
            let due = self
                .logs_at
                .map(|t| t.elapsed() >= Duration::from_secs(1))
                .unwrap_or(true);
            if due {
                self.logs_busy = true;
                spawn_logs(
                    self.tx.clone(),
                    ctx.clone(),
                    self.logs_since,
                    self.logs_ref.clone(),
                );
            }
        }
        let dark = ctx.style().visuals.dark_mode;

        egui::SidePanel::left("nav")
            .resizable(false)
            .exact_width(200.0)
            .frame(
                egui::Frame::NONE
                    .fill(side_fill(dark))
                    .inner_margin(egui::Margin::symmetric(10, 8)),
            )
            .show(ctx, |ui| {
                ui.add_space(8.0);
                for tab in [Tab::Overview, Tab::Models, Tab::Logs, Tab::Settings] {
                    if nav_item(ui, self.tab == tab, tab.label()).clicked() {
                        self.tab = tab;
                        if tab == Tab::Logs {
                            self.logs_busy = true;
                            spawn_logs(
                                self.tx.clone(),
                                ctx.clone(),
                                self.logs_since,
                                self.logs_ref.clone(),
                            );
                        }
                    }
                    ui.add_space(2.0);
                }
                ui.with_layout(egui::Layout::bottom_up(egui::Align::LEFT), |ui| {
                    ui.label(
                        egui::RichText::new(format!("v{}", env!("CARGO_PKG_VERSION")))
                            .weak()
                            .small(),
                    );
                    if let Some(sys) = &self.system {
                        ui.label(
                            egui::RichText::new(format!(
                                "运行时长 {}",
                                fmt_uptime(sys["uptime_seconds"].as_f64().unwrap_or(0.0))
                            ))
                            .weak()
                            .small(),
                        );
                    }
                    let (color, text) = if self.system.is_some() {
                        (green(ui), "运行中")
                    } else {
                        (red(ui), "已停止")
                    };
                    ui.horizontal(|ui| {
                        ui.colored_label(color, "●");
                        ui.label(text);
                    });
                });
            });

        egui::TopBottomPanel::bottom("status")
            .frame(
                egui::Frame::NONE
                    .fill(status_fill(dark))
                    .inner_margin(egui::Margin::symmetric(14, 5)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let Some(sys) = &self.system else {
                        ui.label(
                            egui::RichText::new("服务未运行 · 无遥测数据")
                                .weak()
                                .small(),
                        );
                        return;
                    };
                    let gpu = &sys["gpu"][0];
                    let util = gpu["utilization_gpu_pct"].as_f64().unwrap_or(0.0) as f32;
                    let total = gpu["memory_total_bytes"].as_f64().unwrap_or(0.0);
                    let used = gpu["memory_used_bytes"].as_f64().unwrap_or(0.0);
                    let vram = if total > 0.0 {
                        (used / total * 100.0) as f32
                    } else {
                        0.0
                    };
                    let cpu = &sys["cpu"];
                    let cpu_pct = cpu["usage_pct"].as_f64().unwrap_or(0.0) as f32;
                    let mem_total = cpu["mem_total_bytes"].as_f64().unwrap_or(0.0);
                    let mem_used = cpu["mem_used_bytes"].as_f64().unwrap_or(0.0);
                    let mem_pct = if mem_total > 0.0 {
                        (mem_used / mem_total * 100.0) as f32
                    } else {
                        0.0
                    };
                    flat_metric(ui, "GPU", util, egui::Color32::from_rgb(55, 148, 255));
                    ui.add_space(16.0);
                    flat_metric(ui, "显存", vram, egui::Color32::from_rgb(78, 201, 176));
                    ui.add_space(16.0);
                    flat_metric(ui, "CPU", cpu_pct, egui::Color32::from_rgb(215, 186, 125));
                    ui.add_space(16.0);
                    flat_metric(ui, "内存", mem_pct, egui::Color32::from_rgb(197, 134, 192));
                });
            });

        let frame = egui::Frame::central_panel(&ctx.style()).inner_margin(egui::Margin::same(12));
        egui::CentralPanel::default().frame(frame).show(ctx, |ui| {
            ui.add_space(4.0);
            match self.tab {
                Tab::Overview => self.overview(ui),
                Tab::Models => self.models_page(ui),
                Tab::Logs => self.logs_page(ui),
                Tab::Settings => self.settings_page(ui),
            }
        });

        self.show_use_dialog(ctx);
        self.show_cache_dialog(ctx);
        self.show_smoke_dialog(ctx);
        self.show_options_dialog(ctx);
        self.show_dialog(ctx);
        self.show_busy_overlay(ctx);
        self.show_toast(ctx);
        if self.op_busy.is_some() {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
    }
}

// ---------- widgets ----------

fn card_fill_dark(dark: bool) -> egui::Color32 {
    if dark {
        egui::Color32::from_rgb(33, 33, 36)
    } else {
        egui::Color32::WHITE
    }
}

fn card_stroke_dark(dark: bool) -> egui::Stroke {
    if dark {
        egui::Stroke::new(1.0_f32, egui::Color32::from_rgb(52, 52, 58))
    } else {
        egui::Stroke::new(1.0_f32, egui::Color32::from_rgb(222, 225, 230))
    }
}

fn card_fill(ui: &egui::Ui) -> egui::Color32 {
    card_fill_dark(ui.visuals().dark_mode)
}

fn card_stroke(ui: &egui::Ui) -> egui::Stroke {
    card_stroke_dark(ui.visuals().dark_mode)
}

fn side_fill(dark: bool) -> egui::Color32 {
    if dark {
        egui::Color32::from_rgb(19, 19, 21)
    } else {
        egui::Color32::from_rgb(236, 238, 241)
    }
}

fn status_fill(dark: bool) -> egui::Color32 {
    if dark {
        egui::Color32::from_rgb(21, 21, 23)
    } else {
        egui::Color32::from_rgb(239, 241, 244)
    }
}

fn card_frame(ui: &egui::Ui) -> egui::Frame {
    egui::Frame::NONE
        .fill(card_fill(ui))
        .stroke(card_stroke(ui))
        .corner_radius(6)
        .inner_margin(egui::Margin::symmetric(14, 12))
}

fn dialog_frame(dark: bool) -> egui::Frame {
    egui::Frame::NONE
        .fill(card_fill_dark(dark))
        .stroke(card_stroke_dark(dark))
        .corner_radius(8)
        .inner_margin(egui::Margin::symmetric(18, 16))
        .shadow(egui::epaint::Shadow {
            offset: [0, 10],
            blur: 28,
            spread: 0,
            color: egui::Color32::from_black_alpha(if dark { 130 } else { 45 }),
        })
}

fn modal_backdrop(ctx: &egui::Context, dark: bool, close: &mut bool) {
    let screen = ctx.screen_rect();
    egui::Area::new(egui::Id::new("modal_backdrop"))
        .order(egui::Order::Middle)
        .fixed_pos(screen.min)
        .interactable(true)
        .show(ctx, |ui| {
            let (rect, response) = ui.allocate_exact_size(screen.size(), egui::Sense::click());
            ui.painter().rect_filled(
                rect,
                0.0,
                egui::Color32::from_black_alpha(if dark { 110 } else { 60 }),
            );
            if response.clicked() {
                *close = true;
            }
        });
}

fn panel(ui: &mut egui::Ui, title: &str, add: impl FnOnce(&mut egui::Ui)) {
    card_frame(ui).show(ui, |ui| {
        let width = ui.available_width();
        if width.is_finite() {
            ui.set_width(width);
        }
        ui.label(egui::RichText::new(title).small().strong().weak());
        ui.add_space(6.0);
        add(ui);
    });
}

fn pair(ui: &mut egui::Ui, label: &str, value: &str) {
    ui.label(egui::RichText::new(label).weak().small());
    ui.label(egui::RichText::new(value).size(13.0));
}

fn legend(ui: &mut egui::Ui, color: egui::Color32, text: &str) {
    ui.colored_label(color, "●");
    ui.label(egui::RichText::new(text).weak().small());
    ui.add_space(10.0);
}

fn stat(ui: &mut egui::Ui, label: &str, value: &str) {
    ui.label(egui::RichText::new(label).weak().small());
    ui.label(egui::RichText::new(value).small());
    ui.add_space(14.0);
}

fn size_text(ready: bool, bytes: f64) -> String {
    if ready {
        fmt_bytes(bytes)
    } else {
        "缺失".to_string()
    }
}

fn size_cell(ui: &mut egui::Ui, ready: bool, bytes: f64) {
    if ready {
        ui.label(fmt_bytes(bytes));
    } else {
        ui.label(egui::RichText::new("缺失").color(red(ui)).small());
    }
}

fn runtime_cell(ui: &mut egui::Ui, model: &ModelRow) {
    if model.runtime_id.is_empty() {
        ui.label(egui::RichText::new("—").weak().small())
            .on_hover_text("该模型没有独立运行时目录");
    } else if model.runtime_bytes > 0.0 {
        ui.label(fmt_bytes(model.runtime_bytes))
            .on_hover_text(format!("运行时: {}\n按 bundle/版本独立", model.runtime_id));
    } else {
        ui.label(egui::RichText::new("未安装").weak().small())
            .on_hover_text(format!("运行时: {}\n加载时会创建", model.runtime_id));
    }
}

fn weights_cell(ui: &mut egui::Ui, model: &ModelRow, shared: bool) {
    if !model.weights_ready {
        ui.label(egui::RichText::new("缺失").color(red(ui)).small());
        return;
    }
    ui.label(fmt_bytes(model.weights_bytes));
    if shared {
        ui.label(egui::RichText::new("共享").small().weak())
            .on_hover_text("多个模型共用同一 source/repo@revision 权重目录");
    }
}

fn kv(ui: &mut egui::Ui, key: &str, value: &str) {
    ui.label(egui::RichText::new(key).weak());
    ui.label(value);
    ui.end_row();
}

fn nav_item(ui: &mut egui::Ui, selected: bool, text: &str) -> egui::Response {
    let width = ui.available_width();
    let (rect, response) = ui.allocate_exact_size(egui::vec2(width, 30.0), egui::Sense::click());
    if ui.is_rect_visible(rect) {
        let visuals = ui.visuals().clone();
        let bg = if selected {
            visuals.selection.bg_fill
        } else if response.is_pointer_button_down_on() {
            visuals.widgets.active.bg_fill
        } else if response.hovered() {
            visuals.widgets.hovered.bg_fill
        } else {
            egui::Color32::TRANSPARENT
        };
        if bg != egui::Color32::TRANSPARENT {
            ui.painter().rect_filled(rect, 3.0, bg);
        }
        let color = if selected {
            egui::Color32::WHITE
        } else {
            visuals.text_color()
        };
        ui.painter().text(
            rect.left_center() + egui::vec2(12.0, 0.0),
            egui::Align2::LEFT_CENTER,
            text,
            egui::FontId::proportional(13.0),
            color,
        );
    }
    response.widget_info(|| {
        egui::WidgetInfo::selected(egui::WidgetType::SelectableLabel, true, selected, text)
    });
    response
}

fn flat_metric(ui: &mut egui::Ui, label: &str, pct: f32, color: egui::Color32) {
    ui.label(egui::RichText::new(label).weak().small());
    let (rect, _) = ui.allocate_exact_size(egui::vec2(90.0, 6.0), egui::Sense::hover());
    let track = if ui.visuals().dark_mode {
        egui::Color32::from_rgb(58, 58, 62)
    } else {
        egui::Color32::from_rgb(222, 224, 228)
    };
    let painter = ui.painter();
    painter.rect_filled(rect, 3.0, track);
    let pct = pct.clamp(0.0, 100.0);
    if pct > 0.0 {
        let fill = egui::Rect::from_min_size(
            rect.min,
            egui::vec2(rect.width() * pct / 100.0, rect.height()),
        );
        painter.rect_filled(fill, 3.0, color);
    }
    ui.label(
        egui::RichText::new(format!("{pct:>3.0}%"))
            .small()
            .monospace(),
    );
}

fn progress_width(ui: &egui::Ui) -> f32 {
    let w = ui.available_width().min(360.0);
    if w.is_finite() && w > 1.0 {
        w
    } else {
        200.0
    }
}

fn plot(
    ui: &mut egui::Ui,
    id: &str,
    height: f32,
    series: &[(&str, &Vec<[f64; 2]>, egui::Color32)],
) {
    use egui_plot::{Line, Plot, PlotPoints};
    Plot::new(id)
        .height(height)
        .include_y(0.0)
        .include_y(100.0)
        .allow_drag(false)
        .allow_zoom(false)
        .allow_scroll(false)
        .label_formatter(|name, point| format!("{name}: {:.0}%", point.y))
        .y_axis_formatter(|mark, _| format!("{:.0}%", mark.value))
        .show(ui, |plot_ui| {
            for (name, points, color) in series {
                let pts: PlotPoints = points.iter().copied().collect();
                plot_ui.line(Line::new(pts).name(*name).color(*color));
            }
        });
}

fn button(ui: &mut egui::Ui, text: &str) -> egui::Response {
    ui.add_sized([96.0, 28.0], egui::Button::new(text))
}

fn primary_button(ui: &mut egui::Ui, text: &str) -> egui::Response {
    ui.add_sized(
        [96.0, 28.0],
        egui::Button::new(egui::RichText::new(text).color(egui::Color32::WHITE)).fill(accent(ui)),
    )
}

fn danger_button(ui: &mut egui::Ui, text: &str) -> egui::Response {
    ui.add_sized(
        [96.0, 28.0],
        egui::Button::new(egui::RichText::new(text).color(red(ui))),
    )
}

fn destructive_button(ui: &mut egui::Ui, text: &str) -> egui::Response {
    ui.add_sized(
        [96.0, 28.0],
        egui::Button::new(egui::RichText::new(text).color(egui::Color32::WHITE))
            .fill(egui::Color32::from_rgb(176, 54, 48)),
    )
}

fn chip(ui: &mut egui::Ui, text: &str, color: egui::Color32) {
    egui::Frame::NONE
        .fill(color.gamma_multiply(0.18))
        .corner_radius(6)
        .inner_margin(egui::Margin::symmetric(9, 3))
        .show(ui, |ui| {
            ui.label(egui::RichText::new(text).color(color).small().strong());
        });
}

fn table_button(ui: &mut egui::Ui, text: &str) -> egui::Response {
    ui.add_sized(
        [64.0, 25.0],
        egui::Button::new(egui::RichText::new(text).size(12.5)),
    )
}

fn accent(ui: &egui::Ui) -> egui::Color32 {
    if ui.visuals().dark_mode {
        egui::Color32::from_rgb(55, 148, 255)
    } else {
        egui::Color32::from_rgb(26, 115, 232)
    }
}

fn green(ui: &egui::Ui) -> egui::Color32 {
    if ui.visuals().dark_mode {
        egui::Color32::from_rgb(78, 201, 176)
    } else {
        egui::Color32::from_rgb(16, 124, 16)
    }
}

fn red(ui: &egui::Ui) -> egui::Color32 {
    if ui.visuals().dark_mode {
        egui::Color32::from_rgb(244, 135, 113)
    } else {
        egui::Color32::from_rgb(196, 43, 28)
    }
}

// ---------- data ----------

fn parse_models(v: &Value, system: Option<&Value>) -> Vec<ModelRow> {
    let mut loaded: HashMap<String, (String, i64, String)> = HashMap::new();
    if let Some(items) = system.and_then(|s| s["loaded"].as_array()) {
        for m in items {
            if let Some(name) = m["ref"].as_str() {
                loaded.insert(
                    name.to_string(),
                    (
                        m["endpoint"].as_str().unwrap_or("").to_string(),
                        m["pid"].as_i64().unwrap_or(0),
                        m["loaded_at"].as_str().unwrap_or("").to_string(),
                    ),
                );
            }
        }
    }
    v["models"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .map(|m| {
                    let name = m["ref"].as_str().unwrap_or("").to_string();
                    let info = loaded.get(&name).cloned();
                    ModelRow {
                        name,
                        bundle_ready: m["bundle_cached"].as_bool().unwrap_or(false),
                        weights_ready: m["weights_cached"].as_bool().unwrap_or(false),
                        serve: m["serve"].as_bool().unwrap_or(false),
                        bundle_bytes: m["bundle_bytes"].as_f64().unwrap_or(0.0),
                        runtime_id: m["runtime_id"].as_str().unwrap_or("").to_string(),
                        runtime_bytes: m["runtime_bytes"].as_f64().unwrap_or(0.0),
                        weights_bytes: m["weights_bytes"].as_f64().unwrap_or(0.0),
                        weights_key: m["weights_key"].as_str().unwrap_or("").to_string(),
                        loaded: info.is_some(),
                        endpoint: info.as_ref().map(|i| i.0.clone()).unwrap_or_default(),
                        pid: info.as_ref().map(|i| i.1).unwrap_or(0),
                        loaded_at: info.as_ref().map(|i| i.2.clone()).unwrap_or_default(),
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn parse_catalog(v: &Value) -> (Vec<HubRepo>, i64) {
    let total = v["total"].as_i64().unwrap_or(0);
    let repos = v["repos"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .map(|r| HubRepo {
                    id: r["id"].as_i64().unwrap_or(0),
                    namespace: r["namespace"].as_str().unwrap_or("").to_string(),
                    name: r["name"].as_str().unwrap_or("").to_string(),
                    model_name: r["model_name"].as_str().unwrap_or("").to_string(),
                    tags: r["tags"]
                        .as_array()
                        .map(|tags| {
                            tags.iter()
                                .filter_map(|t| t["name"].as_str().map(str::to_string))
                                .collect()
                        })
                        .unwrap_or_default(),
                    versions: r["version_count"].as_i64().unwrap_or(0),
                    downloads: r["downloads"].as_i64().unwrap_or(0),
                })
                .collect()
        })
        .unwrap_or_default();
    (repos, total)
}

fn parse_hub_detail(v: &Value) -> HubDetail {
    HubDetail {
        repo_id: v["repo"]["id"].as_i64().unwrap_or(0),
        versions: v["versions"]
            .as_array()
            .map(|items| {
                items
                    .iter()
                    .map(|x| {
                        let status = match x["release_status"].as_str().unwrap_or("") {
                            "released" => "正式",
                            "pre-release" => "预发布",
                            other => other,
                        };
                        HubVersion {
                            version: x["version"].as_str().unwrap_or("").to_string(),
                            size: x["size"].as_f64().unwrap_or(0.0),
                            files: x["file_count"].as_i64().unwrap_or(0),
                            status: status.to_string(),
                        }
                    })
                    .collect()
            })
            .unwrap_or_default(),
    }
}

fn parse_storage(v: &Value) -> (Vec<(String, String)>, f64, HashMap<String, f64>) {
    let mut total = 0.0;
    let mut sizes = HashMap::new();
    let rows = v["areas"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .map(|a| {
                    let bytes = a["bytes"].as_f64().unwrap_or(0.0);
                    total += bytes;
                    let raw = a["name"].as_str().unwrap_or("");
                    sizes.insert(raw.to_string(), bytes);
                    (storage_label(raw).to_string(), fmt_bytes(bytes))
                })
                .collect()
        })
        .unwrap_or_default();
    (rows, total, sizes)
}

fn storage_label(name: &str) -> &str {
    match name {
        "bundles" => "Bundle",
        "models" => "权重",
        "runtimes" => "模型运行时",
        "cache" => "共享缓存",
        "tools" => "工具",
        "python" => "Python",
        other => other,
    }
}

fn push_point(points: &mut Vec<[f64; 2]>, x: f64, y: f32) {
    points.push([x, y as f64]);
    if points.len() > 600 {
        points.remove(0);
    }
}

// ---------- threads ----------

fn start_ws(tx: Sender<Event>, ctx: egui::Context) {
    std::thread::spawn(move || {
        let mut reconnect_fails = 0;
        loop {
            let ws_url = if let Some(rest) = api_base().strip_prefix("http://") {
                format!("ws://{rest}/v1/ws")
            } else if let Some(rest) = api_base().strip_prefix("https://") {
                format!("wss://{rest}/v1/ws")
            } else {
                format!("{}/v1/ws", api_base())
            };
            match ewebsock::connect(ws_url, ewebsock::Options::default()) {
                Ok((_sender, receiver)) => {
                    reconnect_fails = 0;
                    loop {
                        let mut closed = false;
                        while let Some(event) = receiver.try_recv() {
                            match event {
                                ewebsock::WsEvent::Message(ewebsock::WsMessage::Text(text)) => {
                                    if let Ok(v) = serde_json::from_str::<Value>(&text) {
                                        match v["type"].as_str().unwrap_or("") {
                                            "system" => {
                                                let _ = tx.send(Event::System(v["data"].clone()));
                                            }
                                            "models" => {
                                                let _ = tx.send(Event::Models(v["data"].clone()));
                                            }
                                            "storage" => {
                                                let _ = tx.send(Event::Storage(v["data"].clone()));
                                            }
                                            "mirror" => {
                                                let _ = tx.send(Event::Mirror(v["data"].clone()));
                                            }
                                            "job" => {
                                                let data = &v["data"];
                                                let kind =
                                                    data["type"].as_str().unwrap_or("").to_string();
                                                let verb = match kind.as_str() {
                                                    "pull" => "下载",
                                                    "smoke" => "测试",
                                                    _ => "启动",
                                                };
                                                let _ = tx.send(Event::Job(JobEvent {
                                                    phase: data["event"]["phase"]
                                                        .as_str()
                                                        .unwrap_or("")
                                                        .to_string(),
                                                    message: data["event"]["message"]
                                                        .as_str()
                                                        .unwrap_or("")
                                                        .to_string(),
                                                    state: data["state"]
                                                        .as_str()
                                                        .unwrap_or("")
                                                        .to_string(),
                                                    verb: verb.to_string(),
                                                    reference: data["ref"]
                                                        .as_str()
                                                        .unwrap_or("")
                                                        .to_string(),
                                                    kind,
                                                    authoritative: false,
                                                }));
                                            }
                                            _ => {}
                                        }
                                        ctx.request_repaint();
                                    }
                                }
                                ewebsock::WsEvent::Closed | ewebsock::WsEvent::Error(_) => {
                                    closed = true;
                                    break;
                                }
                                _ => {}
                            }
                        }
                        if closed {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                }
                Err(_) => {
                    reconnect_fails += 1;
                    if reconnect_fails >= 3 {
                        let _ = tx.send(Event::ServiceDown);
                    }
                    let _ = tx.send(Event::Status(String::new()));
                    std::thread::sleep(Duration::from_secs(2));
                }
            }
        }
    });
}

#[derive(Clone, Copy)]
enum Action {
    Start,
    Stop,
    EnableAutostart,
    DisableAutostart { keep_stopped: bool },
}

impl Action {
    fn label(self) -> &'static str {
        match self {
            Action::Start => "正在启动服务…",
            Action::Stop => "正在停止服务…",
            Action::EnableAutostart => "正在启用开机启动…",
            Action::DisableAutostart { .. } => "正在禁用开机启动…",
        }
    }
}

fn spawn_action(tx: Sender<Event>, ctx: egui::Context, action: Action) {
    std::thread::spawn(move || {
        let _ = tx.send(Event::OpBusy(action.label().into()));
        ctx.request_repaint();
        let autostart = match action {
            Action::EnableAutostart => Some(true),
            Action::DisableAutostart { .. } => Some(false),
            _ => None,
        };
        let result = match action {
            Action::Start => match start_service() {
                Ok(message) => {
                    let mut ready = false;
                    for _ in 0..16 {
                        if let Some(v) = get_json("/v1/system") {
                            let _ = tx.send(Event::System(v));
                            ready = true;
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(500));
                    }
                    if ready {
                        Ok(message)
                    } else {
                        Err("服务启动命令已执行，但健康检查超时".into())
                    }
                }
                Err(err) => Err(err),
            },
            Action::Stop => match stop_service() {
                Ok(message) => {
                    let _ = tx.send(Event::ServiceDown);
                    Ok(message)
                }
                Err(err) => Err(err),
            },
            Action::EnableAutostart => set_autostart(true),
            Action::DisableAutostart { keep_stopped } => match set_autostart(false) {
                Ok(message) => {
                    if keep_stopped {
                        if let Err(err) = stop_service() {
                            Err(format!("{message}；停止服务失败：{err}"))
                        } else {
                            let _ = tx.send(Event::ServiceDown);
                            Ok(message)
                        }
                    } else {
                        Ok(message)
                    }
                }
                Err(err) => Err(err),
            },
        };
        if result.is_ok() {
            if let Some(state) = autostart {
                let _ = tx.send(Event::Autostart(state));
            }
            if matches!(
                action,
                Action::EnableAutostart | Action::DisableAutostart { .. }
            ) {
                if let Some(v) = get_json("/v1/system") {
                    let _ = tx.send(Event::System(v));
                }
            }
        }
        let ok = result.is_ok();
        let _ = tx.send(Event::OpDone(result));
        ctx.request_repaint();
        if ok && !matches!(action, Action::Stop) {
            if let Some(v) = get_json("/v1/models") {
                let _ = tx.send(Event::Models(v));
            }
            if let Some(v) = get_json("/v1/storage") {
                let _ = tx.send(Event::Storage(v));
            }
            ctx.request_repaint();
        }
    });
}

fn spawn_job(
    tx: Sender<Event>,
    ctx: egui::Context,
    ref_str: String,
    pull: bool,
    verb: &'static str,
) {
    std::thread::spawn(move || {
        let endpoint = if pull { "/v1/pull" } else { "/v1/models/load" };
        let event_ref = ref_str.clone();
        let kind = if pull { "pull" } else { "load" };
        let _ = tx.send(Event::Job(JobEvent {
            phase: "prepare".into(),
            message: format!("提交{verb}任务"),
            state: "running".into(),
            verb: verb.to_string(),
            reference: event_ref.clone(),
            kind: kind.to_string(),
            authoritative: true,
        }));
        let body = serde_json::json!({ "ref": ref_str, "async": true });
        match post_json(endpoint, &body) {
            Ok(v) => {
                let job = v["job_id"].as_str().unwrap_or("");
                if job.is_empty() {
                    let _ = tx.send(Event::Status(format!("已{verb}")));
                }
            }
            Err(e) => {
                let _ = tx.send(Event::Job(JobEvent {
                    phase: "failed".into(),
                    message: e,
                    state: "failed".into(),
                    verb: verb.to_string(),
                    reference: event_ref,
                    kind: kind.to_string(),
                    authoritative: true,
                }));
            }
        }
        ctx.request_repaint();
    });
}

fn spawn_catalog(tx: Sender<Event>, ctx: egui::Context, query: String, tag: Option<i64>) {
    std::thread::spawn(move || {
        let mut params = vec![
            ("page_size", "100".to_string()),
            ("sort", "updated".to_string()),
        ];
        if !query.is_empty() {
            params.push(("q", query));
        }
        if let Some(tag) = tag {
            params.push(("tag", tag.to_string()));
        }
        match get_json_query("/v1/catalog", &params) {
            Some(v) if v["repos"].is_array() || v["repos"].is_null() => {
                let (repos, total) = parse_catalog(&v);
                let _ = tx.send(Event::Catalog { repos, total });
            }
            Some(v) => {
                let _ = tx.send(Event::HubError(
                    v["error"]
                        .as_str()
                        .unwrap_or("FlashHub 请求失败")
                        .to_string(),
                ));
            }
            None => {
                let _ = tx.send(Event::HubError(
                    "无法连接 FlashHub，请检查网络或代理设置".to_string(),
                ));
            }
        }
        ctx.request_repaint();
    });
}

fn spawn_catalog_tags(tx: Sender<Event>, ctx: egui::Context) {
    std::thread::spawn(move || {
        let tags = get_json_timeout("/v1/catalog/tags", 20)
            .map(|v| {
                v["tags"]
                    .as_array()
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(|t| {
                                Some((t["id"].as_i64()?, t["name"].as_str()?.to_string()))
                            })
                            .collect()
                    })
                    .unwrap_or_default()
            })
            .unwrap_or_default();
        let _ = tx.send(Event::CatalogTags(tags));
        ctx.request_repaint();
    });
}

fn spawn_hub_detail(tx: Sender<Event>, ctx: egui::Context, id: i64) {
    std::thread::spawn(move || {
        match get_json_timeout(&format!("/v1/catalog/{id}"), 20) {
            Some(v) if v["repo"].is_object() => {
                let _ = tx.send(Event::HubDetail(parse_hub_detail(&v)));
            }
            Some(v) => {
                let _ = tx.send(Event::HubError(
                    v["error"].as_str().unwrap_or("读取仓库失败").to_string(),
                ));
            }
            None => {
                let _ = tx.send(Event::HubError("读取仓库失败，请稍后重试".to_string()));
            }
        }
        ctx.request_repaint();
    });
}

fn spawn_clean(tx: Sender<Event>, ctx: egui::Context, refs: Vec<String>) {
    std::thread::spawn(move || {
        let body = serde_json::json!({ "refs": refs });
        let note = match post_json("/v1/models/clean", &body) {
            Ok(v) => {
                let freed = v["freed_bytes"].as_f64().unwrap_or(0.0);
                let results = v["results"].as_array();
                let removed = results
                    .map(|items| {
                        items
                            .iter()
                            .filter(|r| r["removed"].as_bool().unwrap_or(false))
                            .count()
                    })
                    .unwrap_or(0);
                let skipped = results
                    .map(|items| {
                        items
                            .iter()
                            .filter(|r| !r["skipped"].as_str().unwrap_or("").is_empty())
                            .count()
                    })
                    .unwrap_or(0);
                let mut note = format!("已清理 {removed} 个模型，释放 {}", fmt_bytes(freed));
                if skipped > 0 {
                    note.push_str(&format!("；跳过 {skipped} 个（已加载/占用中）"));
                }
                note
            }
            Err(e) => format!("清理失败：{e}"),
        };
        let _ = tx.send(Event::CleanNote(note));
        if let Some(v) = get_json("/v1/models") {
            let _ = tx.send(Event::Models(v));
        }
        ctx.request_repaint();
    });
}

fn spawn_storage_clean(tx: Sender<Event>, ctx: egui::Context, targets: Vec<String>) {
    std::thread::spawn(move || {
        let body = serde_json::json!({ "targets": targets });
        let note = match post_json("/v1/storage/clean", &body) {
            Ok(v) => {
                let freed = v["freed_bytes"].as_f64().unwrap_or(0.0);
                format!("共享缓存已清理，释放 {}", fmt_bytes(freed))
            }
            Err(e) => format!("清理缓存失败：{e}"),
        };
        let _ = tx.send(Event::StorageNote(note));
        if let Some(v) = get_json("/v1/storage") {
            let _ = tx.send(Event::Storage(v));
        }
        ctx.request_repaint();
    });
}

fn spawn_set_mirror(tx: Sender<Event>, ctx: egui::Context, enabled: bool) {
    std::thread::spawn(move || {
        let body = serde_json::json!({ "enabled": enabled });
        let mut last_error = String::new();
        for attempt in 0..6 {
            match post_json_timeout("/v1/mirror", &body, 15) {
                Ok(v) => {
                    let _ = tx.send(Event::Mirror(v));
                    let _ = tx.send(Event::OpDone(Ok(if enabled {
                        "已启用国内镜像".into()
                    } else {
                        "已禁用国内镜像".into()
                    })));
                    ctx.request_repaint();
                    return;
                }
                Err(e) => {
                    last_error = e;
                    if attempt < 5 {
                        std::thread::sleep(Duration::from_secs(2));
                    }
                }
            }
        }
        let _ = tx.send(Event::OpDone(Err(format!(
            "镜像设置失败（已重试 6 次）：{last_error}"
        ))));
        ctx.request_repaint();
    });
}

fn spawn_unload(tx: Sender<Event>, ctx: egui::Context, ref_str: String) {
    std::thread::spawn(move || {
        let body = serde_json::json!({ "ref": ref_str });
        let status = match post_json("/v1/models/unload", &body) {
            Ok(_) => "已停止".to_string(),
            Err(e) => format!("停止失败：{e}"),
        };
        let _ = tx.send(Event::Status(status));
        ctx.request_repaint();
    });
}

fn spawn_logs(
    tx: Sender<Event>,
    ctx: egui::Context,
    since: Option<u64>,
    model_ref: Option<String>,
) {
    std::thread::spawn(move || {
        let mut params = vec![("lines", "300".to_string())];
        if let Some(ref model) = model_ref {
            params.push(("kind", "model".to_string()));
            params.push(("ref", model.clone()));
        } else {
            params.push(("kind", "server".to_string()));
            if let Some(since) = since {
                params.push(("since", since.to_string()));
            }
        }
        let text = get_json_query("/v1/logs", &params).map(|v| {
            v["lines"]
                .as_array()
                .map(|lines| {
                    lines
                        .iter()
                        .filter_map(|l| l.as_str())
                        .collect::<Vec<_>>()
                        .join("\n")
                })
                .unwrap_or_default()
        });
        let _ = tx.send(Event::Logs(text));
        ctx.request_repaint();
    });
}

fn spawn_export_logs(
    tx: Sender<Event>,
    ctx: egui::Context,
    path: PathBuf,
    model_ref: Option<String>,
) {
    std::thread::spawn(move || {
        let result = (|| -> Result<(), String> {
            let agent = ureq::AgentBuilder::new()
                .timeout(Duration::from_secs(120))
                .build();
            let mut request = agent.get(&format!("{}/v1/logs/download", api_base()));
            request = match &model_ref {
                Some(model) => request.query("kind", "model").query("ref", model),
                None => request.query("kind", "server"),
            };
            let resp = request.call().map_err(|e| e.to_string())?;
            let mut reader = resp.into_reader();
            let mut file = std::fs::File::create(&path).map_err(|e| e.to_string())?;
            std::io::copy(&mut reader, &mut file).map_err(|e| e.to_string())?;
            Ok(())
        })();
        let note = match result {
            Ok(()) => format!("已保存到 {}", path.display()),
            Err(err) => format!("保存失败：{err}"),
        };
        let _ = tx.send(Event::LogsNote(note));
        ctx.request_repaint();
    });
}

fn now_epoch() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

// ---------- HTTP / service ----------

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(3))
        .build()
}

fn get_json(path: &str) -> Option<Value> {
    agent()
        .get(&format!("{}{}", api_base(), path))
        .call()
        .ok()?
        .into_json()
        .ok()
}

fn get_json_query(path: &str, params: &[(&str, String)]) -> Option<Value> {
    let mut request = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(20))
        .build()
        .get(&format!("{}{}", api_base(), path));
    for (key, value) in params {
        request = request.query(key, value);
    }
    request.call().ok()?.into_json().ok()
}

fn get_json_timeout(path: &str, secs: u64) -> Option<Value> {
    ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(secs))
        .build()
        .get(&format!("{}{}", api_base(), path))
        .call()
        .ok()?
        .into_json()
        .ok()
}

fn post_json(path: &str, body: &Value) -> Result<Value, String> {
    post_json_timeout(path, body, 60)
}

fn put_json_timeout(path: &str, body: &Value, secs: u64) -> Result<Value, String> {
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(secs))
        .build();
    match agent
        .put(&format!("{}{}", api_base(), path))
        .send_json(body)
    {
        Ok(resp) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(_, resp)) => Err(resp.into_string().unwrap_or_default()),
        Err(e) => Err(e.to_string()),
    }
}

fn post_json_timeout(path: &str, body: &Value, secs: u64) -> Result<Value, String> {
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(secs))
        .build();
    match agent
        .post(&format!("{}{}", api_base(), path))
        .send_json(body)
    {
        Ok(resp) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(_, resp)) => Err(resp.into_string().unwrap_or_default()),
        Err(e) => Err(e.to_string()),
    }
}

fn spawn_model_options(tx: Sender<Event>, ctx: egui::Context, reference: String) {
    std::thread::spawn(move || {
        let result = get_json_query("/v1/models/options", &[("ref", reference.clone())])
            .ok_or_else(|| "读取启动参数失败：服务不可用".to_string());
        let _ = tx.send(Event::ModelOptions { reference, result });
        ctx.request_repaint();
    });
}

fn spawn_save_model_options(
    tx: Sender<Event>,
    ctx: egui::Context,
    reference: String,
    host: String,
    port: u16,
    options: HashMap<String, String>,
    start: bool,
) {
    std::thread::spawn(move || {
        let body = serde_json::json!({
            "ref": reference.clone(),
            "host": host,
            "port": port,
            "options": options,
        });
        let result = put_json_timeout("/v1/models/options", &body, 20);
        let _ = tx.send(Event::ModelOptionsSaved { reference, result, start });
        ctx.request_repaint();
    });
}

fn spawn_cancel_job(ctx: egui::Context, job_id: String) {
    std::thread::spawn(move || {
        let _ = post_json_timeout(
            &format!("/v1/jobs/{job_id}/cancel"),
            &serde_json::json!({}),
            10,
        );
        ctx.request_repaint();
    });
}

fn spawn_smoke(tx: Sender<Event>, ctx: egui::Context, ref_str: String) {
    std::thread::spawn(move || {
        let body = serde_json::json!({ "ref": ref_str });
        match post_json_timeout("/v1/models/smoke", &body, 20) {
            Ok(v) if v["job_id"].is_string() => {
                let _ = tx.send(Event::SmokeJob(
                    v["job_id"].as_str().unwrap_or("").to_string(),
                ));
            }
            Ok(v) => {
                let _ = tx.send(Event::Smoke(Err(v["error"]
                    .as_str()
                    .unwrap_or("测试任务启动失败")
                    .to_string())));
            }
            Err(e) => {
                let _ = tx.send(Event::Smoke(Err(e)));
            }
        }
        ctx.request_repaint();
    });
}

#[cfg(windows)]
fn run_wsl(args: &[&str]) -> Result<(), String> {
    let mut cmd = std::process::Command::new("wsl.exe");
    cmd.args(["-d", "Ubuntu", "-u", "root", "--"]).args(args);
    hide(&mut cmd);
    let out = cmd.output().map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

#[cfg(windows)]
fn spawn_keepalive() {
    let mut cmd = std::process::Command::new("wsl.exe");
    cmd.args(["-d", "Ubuntu", "-u", "root", "--", "sleep", "infinity"]);
    hide(&mut cmd);
    let _ = cmd.spawn();
}

#[cfg(windows)]
fn hide(cmd: &mut std::process::Command) {
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(0x08000000);
}

#[cfg(not(windows))]
fn run_wsl(args: &[&str]) -> Result<(), String> {
    let (program, rest) = args
        .split_first()
        .ok_or_else(|| "empty command".to_string())?;
    let out = std::process::Command::new(program)
        .args(rest)
        .output()
        .map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

#[cfg(not(windows))]
fn spawn_keepalive() {}

fn start_service() -> Result<String, String> {
    run_wsl(&["systemctl", "start", "flashserver"])?;
    spawn_keepalive();
    Ok("服务已启动".into())
}

fn stop_service() -> Result<String, String> {
    run_wsl(&["systemctl", "stop", "flashserver"])?;
    let _ = run_wsl(&["pkill", "-f", "sleep infinity"]);
    Ok("服务已停止".into())
}

fn set_autostart(enabled: bool) -> Result<String, String> {
    #[cfg(windows)]
    {
        let setup = setup_bin().ok_or_else(|| "找不到 flashserver-setup.exe".to_string())?;
        let arg = if enabled {
            "--enable-autostart"
        } else {
            "--disable-autostart"
        };
        let script = format!(
            "try {{ $p = Start-Process -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop -FilePath '{}' -ArgumentList '{}'; exit $p.ExitCode }} catch {{ exit 1 }}",
            setup.replace('\'', "''"),
            arg
        );
        let mut cmd = std::process::Command::new("powershell.exe");
        cmd.args(["-NoProfile", "-WindowStyle", "Hidden", "-Command", &script]);
        hide(&mut cmd);
        let out = cmd.output().map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok(if enabled {
                "已启用开机启动"
            } else {
                "已禁用开机启动"
            }
            .into())
        } else {
            let detail = String::from_utf8_lossy(&out.stderr).trim().to_string();
            if detail.is_empty() {
                Err("管理员授权被取消或执行失败".into())
            } else {
                Err(detail)
            }
        }
    }
    #[cfg(not(windows))]
    {
        let action = if enabled { "enable" } else { "disable" };
        let out = std::process::Command::new("systemctl")
            .args([action, "flashserver"])
            .output()
            .map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok("已更新开机启动".into())
        } else {
            Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
        }
    }
}

fn setup_bin() -> Option<String> {
    if let Ok(v) = std::env::var("FLASHSERVER_SETUP_BIN") {
        if !v.is_empty() {
            return Some(v);
        }
    }
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    for p in [
        dir.join("payload").join("flashserver-setup.exe"),
        dir.join("..").join("payload").join("flashserver-setup.exe"),
        dir.join("flashserver-setup.exe"),
    ] {
        if p.exists() {
            return Some(p.to_string_lossy().to_string());
        }
    }
    None
}

// ---------- WSL config / startup options ----------

fn json_text(v: &Value) -> String {
    if v.is_null() {
        String::new()
    } else if let Some(s) = v.as_str() {
        s.to_string()
    } else {
        v.to_string()
    }
}

fn wslconfig_path() -> Option<PathBuf> {
    if let Some(home) = std::env::var_os("USERPROFILE") {
        return Some(PathBuf::from(home).join(".wslconfig"));
    }
    std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".wslconfig"))
}

fn load_wslconfig() -> WslConfig {
    wslconfig_path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .map(|text| parse_wslconfig(&text))
        .unwrap_or_default()
}

fn parse_wslconfig(text: &str) -> WslConfig {
    let mut cfg = WslConfig::default();
    let mut in_wsl2 = false;
    for line in text.lines() {
        let t = line.trim();
        if t.starts_with('[') {
            in_wsl2 = t.eq_ignore_ascii_case("[wsl2]");
            continue;
        }
        if !in_wsl2 {
            continue;
        }
        let Some((key, value)) = t.split_once('=') else {
            continue;
        };
        let value = value.trim().trim_matches('"').to_string();
        match key.trim().to_ascii_lowercase().as_str() {
            "memory" => cfg.memory = value,
            "processors" => cfg.processors = value,
            "swap" => cfg.swap = value,
            "networkingmode" => cfg.mirrored = value.eq_ignore_ascii_case("mirrored"),
            _ => {}
        }
    }
    cfg
}

fn valid_wsl_size(value: &str) -> bool {
    let value = value.trim();
    if value.is_empty() {
        return true;
    }
    let digits = value
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect::<String>();
    if digits.is_empty() {
        return false;
    }
    let unit = value[digits.len()..].trim().to_ascii_uppercase();
    matches!(unit.as_str(), "" | "B" | "KB" | "MB" | "GB" | "TB")
}

fn valid_processors(value: &str) -> bool {
    let value = value.trim();
    if value.is_empty() {
        return true;
    }
    value
        .parse::<u32>()
        .map(|n| n > 0 && n <= 256)
        .unwrap_or(false)
}

fn valid_firewall_ports(value: &str) -> bool {
    let value = value.trim();
    if value.is_empty() {
        return true;
    }
    for part in value.split(',') {
        let part = part.trim();
        if part.is_empty() {
            return false;
        }
        if let Some((a, b)) = part.split_once('-') {
            let (Ok(a), Ok(b)) = (a.trim().parse::<u16>(), b.trim().parse::<u16>()) else {
                return false;
            };
            if a == 0 || b == 0 || a > b {
                return false;
            }
        } else if part.parse::<u16>().map(|p| p == 0).unwrap_or(true) {
            return false;
        }
    }
    true
}

fn update_wslconfig(text: &str, cfg: &WslConfig) -> String {
    let sep = if text.contains("\r\n") { "\r\n" } else { "\n" };
    let mut managed = Vec::new();
    if !cfg.memory.trim().is_empty() {
        managed.push(format!("memory={}", cfg.memory.trim()));
    }
    if !cfg.processors.trim().is_empty() {
        managed.push(format!("processors={}", cfg.processors.trim()));
    }
    if !cfg.swap.trim().is_empty() {
        managed.push(format!("swap={}", cfg.swap.trim()));
    }
    if cfg.mirrored {
        managed.push("networkingMode=mirrored".to_string());
    }
    let keys = ["memory", "processors", "swap", "networkingmode"];
    let mut out: Vec<String> = Vec::new();
    let mut in_wsl2 = false;
    let mut seen = false;
    for line in text.lines() {
        let t = line.trim();
        if t.starts_with('[') {
            in_wsl2 = t.eq_ignore_ascii_case("[wsl2]");
            out.push(line.to_string());
            if in_wsl2 {
                out.extend(managed.iter().cloned());
                seen = true;
            }
            continue;
        }
        if in_wsl2 {
            let key = t
                .split_once('=')
                .map(|(k, _)| k)
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if keys.contains(&key.as_str()) {
                continue;
            }
        }
        out.push(line.to_string());
    }
    if !seen && !managed.is_empty() {
        if !out.is_empty() && !out.last().map(|l| l.trim().is_empty()).unwrap_or(false) {
            out.push(String::new());
        }
        out.push("[wsl2]".to_string());
        out.extend(managed);
    }
    let mut result = out.join(sep);
    result.push_str(sep);
    result
}

fn save_wslconfig(cfg: &WslConfig) -> Result<(), String> {
    let path = wslconfig_path().ok_or_else(|| "找不到 USERPROFILE，无法写入 .wslconfig".to_string())?;
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    let updated = update_wslconfig(&text, cfg);
    std::fs::write(&path, updated).map_err(|e| format!("写入 {} 失败：{e}", path.display()))
}

fn run_elevated_ps1(script: &str) -> Result<(), String> {
    let path = std::env::temp_dir().join("flashserver-wsl-firewall.ps1");
    std::fs::write(&path, script).map_err(|e| e.to_string())?;
    let quoted = path.to_string_lossy().replace('\'', "''");
    let cmd = format!(
        "Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','{quoted}'"
    );
    let status = std::process::Command::new("powershell.exe")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &cmd])
        .status()
        .map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err("需要管理员权限（UAC）才能更新 Windows 防火墙规则".to_string())
    }
}

fn apply_wsl(cfg: &WslConfig, restart_service: bool, ports: &str) -> Result<String, String> {
    save_wslconfig(cfg)?;
    let _ = std::process::Command::new("wsl.exe")
        .arg("--shutdown")
        .status();
    std::thread::sleep(Duration::from_secs(3));
    if restart_service {
        let output = std::process::Command::new("wsl.exe")
            .args(["-d", "Ubuntu", "-u", "root", "systemctl", "start", "flashserver"])
            .output()
            .map_err(|e| format!("启动 FlashServer 失败：{e}"))?;
        if !output.status.success() {
            let _ = std::process::Command::new("wsl.exe")
                .args(["-d", "Ubuntu", "-u", "root", "true"])
                .status();
        }
    }
    let mut warning = String::new();
    if cfg.mirrored {
        let local_ports = if ports.trim().is_empty() {
            "Any".to_string()
        } else {
            ports.trim().replace(' ', "")
        };
        let script = format!(
            "$ErrorActionPreference='Stop'\n\
Remove-NetFirewallRule -DisplayName 'FlashServer models' -ErrorAction SilentlyContinue\n\
New-NetFirewallRule -DisplayName 'FlashServer models' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {local_ports} -Profile Private,Domain | Out-Null\n"
        );
        if let Err(err) = run_elevated_ps1(&script) {
            warning = format!("；局域网防火墙规则未更新：{err}");
        }
    }
    if restart_service {
        Ok(format!("WSL 已重启，FlashServer 服务已启动{warning}"))
    } else {
        Ok(format!("WSL 配置已应用{warning}"))
    }
}

fn spawn_apply_wsl(
    tx: Sender<Event>,
    ctx: egui::Context,
    cfg: WslConfig,
    restart_service: bool,
    ports: String,
) {
    std::thread::spawn(move || {
        let result = apply_wsl(&cfg, restart_service, &ports);
        let _ = tx.send(Event::WslApplied(result));
        ctx.request_repaint();
    });
}

// ---------- settings / fonts / theme ----------

fn settings_path() -> Option<PathBuf> {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("FlashServer").join("settings.json"))
}

fn load_settings() -> Settings {
    settings_path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(s.trim_start_matches('\u{feff}')).ok())
        .unwrap_or(Settings { dark: true, wsl_ports: String::new() })
}

fn save_settings(s: &Settings) {
    if let Some(path) = settings_path() {
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        if let Ok(text) = serde_json::to_string_pretty(s) {
            let _ = std::fs::write(path, text);
        }
    }
}

fn apply_theme(ctx: &egui::Context, dark: bool) {
    // Pin the preference so egui never falls back to the OS theme; the custom
    // visuals below must be written to the theme that is actually active.
    let theme = if dark {
        egui::Theme::Dark
    } else {
        egui::Theme::Light
    };
    ctx.set_theme(if dark {
        egui::ThemePreference::Dark
    } else {
        egui::ThemePreference::Light
    });
    let mut visuals = if dark {
        egui::Visuals::dark()
    } else {
        egui::Visuals::light()
    };
    if dark {
        visuals.panel_fill = egui::Color32::from_rgb(26, 26, 28);
        visuals.window_fill = egui::Color32::from_rgb(34, 34, 37);
        visuals.extreme_bg_color = egui::Color32::from_rgb(44, 44, 48);
        visuals.faint_bg_color = egui::Color32::from_rgb(34, 34, 37);
        visuals.selection.bg_fill = egui::Color32::from_rgb(14, 99, 156);
    } else {
        visuals.panel_fill = egui::Color32::from_rgb(244, 245, 247);
        visuals.window_fill = egui::Color32::WHITE;
        visuals.extreme_bg_color = egui::Color32::WHITE;
        visuals.faint_bg_color = egui::Color32::from_rgb(248, 249, 250);
        visuals.selection.bg_fill = egui::Color32::from_rgb(0, 120, 212);
    }
    visuals.selection.stroke = egui::Stroke::new(1.0_f32, egui::Color32::WHITE);

    let border = if dark {
        egui::Color32::from_rgb(66, 66, 72)
    } else {
        egui::Color32::from_rgb(206, 211, 218)
    };
    let inactive_bg = if dark {
        egui::Color32::from_rgb(44, 44, 48)
    } else {
        egui::Color32::from_rgb(252, 252, 253)
    };
    let hover_bg = if dark {
        egui::Color32::from_rgb(56, 56, 61)
    } else {
        egui::Color32::from_rgb(242, 245, 249)
    };
    let active_bg = if dark {
        egui::Color32::from_rgb(64, 64, 70)
    } else {
        egui::Color32::from_rgb(233, 238, 244)
    };
    let hover_border = if dark {
        egui::Color32::from_rgb(82, 156, 214)
    } else {
        egui::Color32::from_rgb(120, 165, 210)
    };
    visuals.widgets.inactive.bg_fill = inactive_bg;
    visuals.widgets.inactive.weak_bg_fill = inactive_bg;
    visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1.0_f32, border);
    visuals.widgets.inactive.corner_radius = egui::CornerRadius::same(4);
    visuals.widgets.hovered.bg_fill = hover_bg;
    visuals.widgets.hovered.weak_bg_fill = hover_bg;
    visuals.widgets.hovered.bg_stroke = egui::Stroke::new(1.0_f32, hover_border);
    visuals.widgets.hovered.corner_radius = egui::CornerRadius::same(4);
    visuals.widgets.active.bg_fill = active_bg;
    visuals.widgets.active.weak_bg_fill = active_bg;
    visuals.widgets.active.bg_stroke = egui::Stroke::new(1.0_f32, hover_border);
    visuals.widgets.active.corner_radius = egui::CornerRadius::same(4);
    visuals.widgets.open = visuals.widgets.hovered;
    visuals.window_stroke = egui::Stroke::new(1.0_f32, border);
    visuals.menu_corner_radius = egui::CornerRadius::same(6);

    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = egui::vec2(8.0, 6.0);
    style.spacing.button_padding = egui::vec2(10.0, 4.0);
    style.spacing.interact_size.y = 26.0;
    style
        .text_styles
        .insert(egui::TextStyle::Body, egui::FontId::proportional(13.0));
    style
        .text_styles
        .insert(egui::TextStyle::Button, egui::FontId::proportional(13.0));
    style
        .text_styles
        .insert(egui::TextStyle::Heading, egui::FontId::proportional(16.0));
    style
        .text_styles
        .insert(egui::TextStyle::Small, egui::FontId::proportional(12.0));
    style
        .text_styles
        .insert(egui::TextStyle::Monospace, egui::FontId::monospace(13.0));
    ctx.set_style_of(theme, style);
    ctx.set_visuals_of(theme, visuals);
}

fn install_fonts(ctx: &egui::Context) {
    let candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ];
    let mut fonts = egui::FontDefinitions::default();
    for path in candidates {
        if let Ok(bytes) = std::fs::read(path) {
            fonts
                .font_data
                .insert("cjk".to_owned(), egui::FontData::from_owned(bytes).into());
            for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
                fonts
                    .families
                    .entry(family)
                    .or_default()
                    .push("cjk".to_owned());
            }
            break;
        }
    }
    ctx.set_fonts(fonts);
}

// ---------- format ----------

fn fmt_bytes(n: f64) -> String {
    let units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let mut value = n;
    let mut idx = 0;
    while value >= 1024.0 && idx < units.len() - 1 {
        value /= 1024.0;
        idx += 1;
    }
    if idx == 0 || value >= 100.0 {
        format!("{value:.0} {}", units[idx])
    } else {
        format!("{value:.1} {}", units[idx])
    }
}

fn fmt_uptime(sec: f64) -> String {
    let sec = sec.max(0.0) as u64;
    let d = sec / 86400;
    let h = (sec % 86400) / 3600;
    let m = (sec % 3600) / 60;
    if d > 0 {
        format!("{d}d {h}h")
    } else if h > 0 {
        format!("{h}h {m}m")
    } else {
        format!("{m}m {}s", sec % 60)
    }
}

fn autostart_text(state: Option<bool>) -> &'static str {
    match state {
        Some(true) => "已启用",
        Some(false) => "已禁用",
        None => "未知",
    }
}

fn translate_phase(phase: &str) -> &str {
    match phase {
        "prepare" => "准备 Bundle",
        "resolve" => "解析引用",
        "pull" => "拉取 Bundle",
        "bundle" => "下载 Bundle",
        "weights" | "download" => "下载权重",
        "venv" | "deps" | "dependencies" => "安装依赖",
        "progress" => "启动服务",
        "done" => "完成",
        "failed" => "失败",
        other => other,
    }
}

fn parse_pct(message: &str) -> Option<f32> {
    let mut found = None;
    for token in message.split_whitespace() {
        let Some(idx) = token.find('%') else {
            continue;
        };
        let num: String = token[..idx]
            .chars()
            .filter(|c| c.is_ascii_digit() || *c == '.')
            .collect();
        if let Ok(value) = num.parse::<f32>() {
            found = Some(value.clamp(0.0, 100.0));
        }
    }
    found
}

fn main() -> eframe::Result<()> {
    let icon = image::load_from_memory(include_bytes!("../ui/icon.png"))
        .ok()
        .map(|img| {
            let rgba = img.to_rgba8();
            egui::IconData {
                rgba: rgba.as_raw().clone(),
                width: rgba.width(),
                height: rgba.height(),
            }
        });
    let mut viewport = egui::ViewportBuilder::default()
        .with_inner_size([1180.0, 760.0])
        .with_min_inner_size([900.0, 600.0])
        .with_position([40.0, 40.0]);
    if let Some(icon) = icon {
        viewport = viewport.with_icon(std::sync::Arc::new(icon));
    }
    let options = eframe::NativeOptions {
        viewport,
        ..Default::default()
    };
    eframe::run_native(
        "FlashServer",
        options,
        Box::new(|cc| Ok(Box::new(App::new(cc)))),
    )
}
