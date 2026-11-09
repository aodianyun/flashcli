#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

slint::include_modules!();

use std::process::Command;
use std::time::Duration;

use serde_json::Value;
use slint::{Image, ModelRc, Rgba8Pixel, SharedPixelBuffer, VecModel, Weak};

const BASE: &str = "http://127.0.0.1:8790";

#[derive(Clone, Default)]
struct Charts {
    gpu_util: Vec<f32>,
    gpu_mem: Vec<f32>,
    cpu: Vec<f32>,
}

#[derive(Default)]
struct History {
    gpu_util: Vec<f32>,
    gpu_mem: Vec<f32>,
    cpu: Vec<f32>,
}

impl History {
    fn push(&mut self, gpu_util: f32, gpu_mem: f32, cpu: f32) {
        for (buf, value) in [
            (&mut self.gpu_util, gpu_util),
            (&mut self.gpu_mem, gpu_mem),
            (&mut self.cpu, cpu),
        ] {
            buf.push(value.clamp(0.0, 100.0));
            if buf.len() > 120 {
                buf.remove(0);
            }
        }
    }
    fn snapshot(&self) -> Charts {
        Charts {
            gpu_util: self.gpu_util.clone(),
            gpu_mem: self.gpu_mem.clone(),
            cpu: self.cpu.clone(),
        }
    }
}

fn main() {
    // Software rendering is reliable on WSL/VM/RDP setups where OpenGL may be
    // unavailable; allow an explicit override via SLINT_BACKEND.
    if std::env::var_os("SLINT_BACKEND").is_none() {
        std::env::set_var("SLINT_BACKEND", "winit-software");
    }

    let ui = AppWindow::new().expect("failed to create window");
    ui.set_version("1.0.6.2026.11.06".into());

    wire_callbacks(&ui);
    start_ws(ui.as_weak());
    start_poll(ui.as_weak());
    refresh_async(ui.as_weak());

    ui.run().expect("ui failed");
}

fn wire_callbacks(ui: &AppWindow) {
    let weak = ui.as_weak();
    ui.on_refresh(move || refresh_async(weak.clone()));

    let weak = ui.as_weak();
    ui.on_start_service(move || {
        let weak = weak.clone();
        std::thread::spawn(move || {
            let result = start_service();
            set_status(&weak, result);
            std::thread::sleep(Duration::from_millis(800));
            refresh_async(weak.clone());
        });
    });

    let weak = ui.as_weak();
    ui.on_stop_service(move || {
        let weak = weak.clone();
        std::thread::spawn(move || {
            let result = stop_service();
            set_status(&weak, result);
            std::thread::sleep(Duration::from_millis(500));
            refresh_async(weak.clone());
        });
    });

    let weak = ui.as_weak();
    ui.on_enable_autostart(move || {
        let weak = weak.clone();
        std::thread::spawn(move || {
            let result = set_autostart(true);
            set_status(&weak, result);
            std::thread::sleep(Duration::from_secs(1));
            refresh_async(weak.clone());
        });
    });

    let weak = ui.as_weak();
    ui.on_disable_autostart(move || {
        let weak = weak.clone();
        std::thread::spawn(move || {
            let result = set_autostart(false);
            set_status(&weak, result);
            std::thread::sleep(Duration::from_secs(1));
            refresh_async(weak.clone());
        });
    });

    let weak = ui.as_weak();
    ui.on_do_load(move |ref_str| {
        let weak = weak.clone();
        let ref_str = ref_str.to_string();
        std::thread::spawn(move || load_model(weak, ref_str));
    });

    let weak = ui.as_weak();
    ui.on_do_unload(move |ref_str| {
        let weak = weak.clone();
        let ref_str = ref_str.to_string();
        std::thread::spawn(move || {
            let body = serde_json::json!({ "ref": ref_str });
            let result = post_json("/v1/models/unload", &body);
            set_status(&weak, result.map(|_| "已卸载".to_string()));
            refresh_async(weak.clone());
        });
    });

    let weak = ui.as_weak();
    ui.on_open_console(move || {
        let _ = webbrowser::open(BASE);
        let _ = weak;
    });

    ui.on_quit_app(|| std::process::exit(0));

    let weak = ui.as_weak();
    ui.on_load_logs(move || {
        let weak = weak.clone();
        std::thread::spawn(move || {
            if let Some(v) = get_json("/v1/logs?kind=server&lines=300") {
                let text = v["lines"]
                    .as_array()
                    .map(|lines| {
                        lines
                            .iter()
                            .filter_map(|l| l.as_str())
                            .collect::<Vec<_>>()
                            .join("\n")
                    })
                    .unwrap_or_default();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(ui) = weak.upgrade() {
                        ui.set_logs(text.into());
                    }
                });
            }
        });
    });

    let weak = ui.as_weak();
    ui.on_copy_text(move |text| {
        if let Ok(mut clipboard) = arboard::Clipboard::new() {
            let _ = clipboard.set_text(text.to_string());
        }
        let _ = weak;
    });
}

fn set_status(weak: &Weak<AppWindow>, result: Result<String, String>) {
    let message = match result {
        Ok(m) => m,
        Err(e) => format!("失败：{e}"),
    };
    let weak = weak.clone();
    let _ = slint::invoke_from_event_loop(move || {
        if let Some(ui) = weak.upgrade() {
            ui.set_load_status(message.into());
        }
    });
}

// ---------- WebSocket ----------

fn start_ws(weak: Weak<AppWindow>) {
    std::thread::spawn(move || {
        let mut history = History::default();
        loop {
            match ewebsock::connect("ws://127.0.0.1:8790/v1/ws", ewebsock::Options::default()) {
                Ok((_sender, receiver)) => loop {
                    let mut closed = false;
                    while let Some(event) = receiver.try_recv() {
                        match event {
                            ewebsock::WsEvent::Message(ewebsock::WsMessage::Text(text)) => {
                                handle_ws(&weak, &mut history, &text);
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
                },
                Err(_) => {
                    set_offline(&weak);
                    std::thread::sleep(Duration::from_secs(2));
                }
            }
        }
    });
}

fn handle_ws(weak: &Weak<AppWindow>, history: &mut History, text: &str) {
    let Ok(value) = serde_json::from_str::<Value>(text) else {
        return;
    };
    match value["type"].as_str().unwrap_or("") {
        "system" => {
            let data = &value["data"];
            let gpu_util = data["gpu"][0]["utilization_gpu_pct"].as_f64().unwrap_or(0.0) as f32;
            let mem_total = data["gpu"][0]["memory_total_bytes"].as_f64().unwrap_or(0.0);
            let mem_used = data["gpu"][0]["memory_used_bytes"].as_f64().unwrap_or(0.0);
            let gpu_mem = if mem_total > 0.0 { (mem_used / mem_total * 100.0) as f32 } else { 0.0 };
            let cpu = data["cpu"]["usage_pct"].as_f64().unwrap_or(0.0) as f32;
            history.push(gpu_util, gpu_mem, cpu);
            let charts = history.snapshot();
            let data = data.clone();
            let weak = weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak.upgrade() {
                    apply_system(&ui, &data, Some(charts));
                }
            });
        }
        "job" => {
            let data = &value["data"];
            let event = &data["event"];
            let msg = format!(
                "{} {} {}",
                data["type"].as_str().unwrap_or("job"),
                event["phase"].as_str().unwrap_or(""),
                event["message"].as_str().unwrap_or("")
            );
            let state = data["state"].as_str().unwrap_or("").to_string();
            let weak = weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak.upgrade() {
                    ui.set_load_status(msg.trim().to_string().into());
                    if state == "done" || state == "failed" {
                        // the poll loop also refreshes; keep the message visible
                    }
                }
            });
        }
        _ => {}
    }
}

fn set_offline(weak: &Weak<AppWindow>) {
    let weak = weak.clone();
    let _ = slint::invoke_from_event_loop(move || {
        if let Some(ui) = weak.upgrade() {
            ui.set_running(false);
            ui.set_status_text("已停止".into());
        }
    });
}

// ---------- HTTP polling ----------

fn start_poll(weak: Weak<AppWindow>) {
    std::thread::spawn(move || loop {
        if let Some(system) = get_json("/v1/system") {
            let weak2 = weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak2.upgrade() {
                    apply_system(&ui, &system, None);
                }
            });
        }
        if let Some(models) = get_json("/v1/models") {
            if let Some(loaded) = get_json("/v1/models/loaded") {
                let weak2 = weak.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(ui) = weak2.upgrade() {
                        apply_models(&ui, &models, &loaded);
                    }
                });
            }
        }
        if let Some(storage) = get_json("/v1/storage") {
            let weak2 = weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak2.upgrade() {
                    apply_storage(&ui, &storage);
                }
            });
        }
        std::thread::sleep(Duration::from_secs(5));
    });
}

fn refresh_async(weak: Weak<AppWindow>) {
    std::thread::spawn(move || {
        if let Some(system) = get_json("/v1/system") {
            let weak2 = weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak2.upgrade() {
                    apply_system(&ui, &system, None);
                }
            });
        } else {
            set_offline(&weak);
        }
        if let Some(models) = get_json("/v1/models") {
            if let Some(loaded) = get_json("/v1/models/loaded") {
                let weak2 = weak.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(ui) = weak2.upgrade() {
                        apply_models(&ui, &models, &loaded);
                    }
                });
            }
        }
        if let Some(storage) = get_json("/v1/storage") {
            let weak2 = weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak2.upgrade() {
                    apply_storage(&ui, &storage);
                }
            });
        }
    });
}

fn apply_system(ui: &AppWindow, v: &Value, charts: Option<Charts>) {
    ui.set_running(true);
    ui.set_status_text("运行中".into());
    ui.set_version(v["version"].as_str().unwrap_or("").into());
    ui.set_uptime_text(fmt_uptime(v["uptime_seconds"].as_f64().unwrap_or(0.0)).into());
    ui.set_service_info(
        format!(
            "已加载 {}/{}",
            v["loaded_count"].as_i64().unwrap_or(0),
            match v["max_loaded"].as_i64().unwrap_or(0) {
                0 => "不限".to_string(),
                n => n.to_string(),
            }
        )
        .into(),
    );
    ui.set_autostart(translate_autostart(v["autostart"].as_str().unwrap_or("unknown")).into());

    let gpu = &v["gpu"][0];
    if !gpu.is_null() {
        let total = gpu["memory_total_bytes"].as_f64().unwrap_or(0.0);
        let used = gpu["memory_used_bytes"].as_f64().unwrap_or(0.0);
        ui.set_gpu_name(gpu["name"].as_str().unwrap_or("").into());
        ui.set_gpu_util(gpu["utilization_gpu_pct"].as_f64().unwrap_or(0.0) as f32);
        ui.set_gpu_mem(if total > 0.0 { (used / total * 100.0) as f32 } else { 0.0 });
        ui.set_gpu_mem_text(format!("{} / {}", fmt_bytes(used), fmt_bytes(total)).into());
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
        if let Some(cuda) = v["cuda_version"].as_str() {
            let sm = v["sm"].as_str().unwrap_or("");
            meta.push(format!("CUDA {cuda}"));
            if !sm.is_empty() {
                meta.push(format!("SM {sm}"));
            }
        }
        if let Some(torch) = v["torch_index"].as_str() {
            meta.push(format!("torch {torch}"));
        }
        ui.set_gpu_meta(meta.join(" · ").into());
        ui.set_gpu_driver(gpu["driver_version"].as_str().unwrap_or("—").into());
        ui.set_gpu_cuda(v["cuda_version"].as_str().unwrap_or("—").into());
        let sm = v["sm"].as_str().unwrap_or("");
        let cap = gpu["compute_cap"].as_str().unwrap_or("");
        ui.set_gpu_sm(if sm.is_empty() {
            "—".into()
        } else if cap.is_empty() {
            format!("sm{sm}").into()
        } else {
            format!("sm{sm} ({cap})").into()
        });
        ui.set_gpu_torch(v["torch_index"].as_str().unwrap_or("—").into());
    } else {
        ui.set_gpu_name("GPU 不可用".into());
        ui.set_gpu_meta(v["gpu_error"].as_str().unwrap_or("nvidia-smi 不可用").into());
        ui.set_gpu_driver("—".into());
        ui.set_gpu_cuda("—".into());
        ui.set_gpu_sm("—".into());
        ui.set_gpu_torch("—".into());
    }

    let cpu = &v["cpu"];
    if !cpu.is_null() {
        ui.set_cpu_name(cpu["model"].as_str().unwrap_or("").into());
        let cores = cpu["cores"].as_i64().unwrap_or(0);
        let threads = cpu["threads"].as_i64().unwrap_or(0);
        let mhz = cpu["mhz"].as_f64().unwrap_or(0.0);
        let l1 = cpu["load1"].as_f64().unwrap_or(0.0);
        let l5 = cpu["load5"].as_f64().unwrap_or(0.0);
        let l15 = cpu["load15"].as_f64().unwrap_or(0.0);
        ui.set_cpu_meta(
            format!("{cores}C/{threads}T · {mhz:.0} MHz · load {l1:.2}/{l5:.2}/{l15:.2}").into(),
        );
        ui.set_cpu_util(cpu["usage_pct"].as_f64().unwrap_or(0.0) as f32);
        let per_core = cpu["per_core_pct"].as_array().cloned().unwrap_or_default();
        let items: Vec<CoreItem> = per_core
            .iter()
            .enumerate()
            .map(|(i, v)| CoreItem {
                label: format!("C{i}").into(),
                value: v.as_f64().unwrap_or(0.0) as f32,
            })
            .collect();
        let mid = (items.len() + 1) / 2;
        let (left, right) = items.split_at(mid);
        ui.set_cores_left(ModelRc::new(VecModel::from(left.to_vec())));
        ui.set_cores_right(ModelRc::new(VecModel::from(right.to_vec())));
        let mem_total = cpu["mem_total_bytes"].as_f64().unwrap_or(0.0);
        let mem_used = cpu["mem_used_bytes"].as_f64().unwrap_or(0.0);
        ui.set_mem_text(format!("{} / {}", fmt_bytes(mem_used), fmt_bytes(mem_total)).into());
        ui.set_mem_pct(if mem_total > 0.0 { (mem_used / mem_total * 100.0) as f32 } else { 0.0 });
        let swap_total = cpu["swap_total_bytes"].as_f64().unwrap_or(0.0);
        let swap_used = cpu["swap_used_bytes"].as_f64().unwrap_or(0.0);
        ui.set_swap_text(if swap_total > 0.0 {
            format!("{} / {}", fmt_bytes(swap_used), fmt_bytes(swap_total))
        } else {
            "—".to_string()
        }.into());
        ui.set_swap_pct(if swap_total > 0.0 { (swap_used / swap_total * 100.0) as f32 } else { 0.0 });
    }

    let mut loaded = Vec::new();
    for item in v["loaded"].as_array().cloned().unwrap_or_default() {
        let pid = item["pid"].as_i64().unwrap_or(0);
        let loaded_at = item["loaded_at"].as_str().unwrap_or("");
        loaded.push(LoadedItem {
            name: item["ref"].as_str().unwrap_or("").into(),
            endpoint: item["endpoint"].as_str().unwrap_or("").into(),
            meta: format!("PID {pid} · {loaded_at}").into(),
        });
    }
    ui.set_loaded(ModelRc::new(VecModel::from(loaded)));

    if let Some(c) = charts {
        ui.set_gpu_chart(render_chart(
            &[(&c.gpu_util, (26, 115, 232)), (&c.gpu_mem, (52, 168, 83))],
            640,
            76,
        ));
        ui.set_cpu_chart(render_chart(&[(&c.cpu, (251, 188, 4))], 640, 48));
    }
}

fn apply_models(ui: &AppWindow, models: &Value, loaded: &Value) {
    let loaded_refs: Vec<String> = loaded["models"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter_map(|m| m["ref"].as_str().map(|s| s.to_string()))
        .collect();
    let items: Vec<ModelItem> = models["models"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|m| {
            let name = m["ref"].as_str().unwrap_or("").to_string();
            let ready = m["bundle_cached"].as_bool().unwrap_or(false)
                && m["weights_cached"].as_bool().unwrap_or(false);
            let bytes = m["bundle_bytes"].as_f64().unwrap_or(0.0)
                + m["weights_bytes"].as_f64().unwrap_or(0.0);
            ModelItem {
                name: name.clone().into(),
                status: if ready { "就绪".into() } else { "缺失".into() },
                size: fmt_bytes(bytes).into(),
                loaded: loaded_refs.contains(&name),
                ready,
            }
        })
        .collect();
    ui.set_models(ModelRc::new(VecModel::from(items)));
}

fn apply_storage(ui: &AppWindow, storage: &Value) {
    let items: Vec<StorageItem> = storage["areas"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|a| StorageItem {
            name: a["name"].as_str().unwrap_or("").into(),
            size: fmt_bytes(a["bytes"].as_f64().unwrap_or(0.0)).into(),
        })
        .collect();
    ui.set_storage(ModelRc::new(VecModel::from(items)));
}

// ---------- actions ----------

fn load_model(weak: Weak<AppWindow>, ref_str: String) {
    let body = serde_json::json!({ "ref": ref_str, "async": true });
    let result = post_json("/v1/models/load", &body);
    match result {
        Ok(v) => {
            let job = v["job_id"].as_str().unwrap_or("").to_string();
            if job.is_empty() {
                set_status(&weak, Ok("已加载".into()));
                refresh_async(weak);
                return;
            }
            for _ in 0..2400 {
                std::thread::sleep(Duration::from_millis(700));
                let Some(j) = get_json(&format!("/v1/jobs/{job}")) else {
                    continue;
                };
                let state = j["state"].as_str().unwrap_or("");
                let phase = j["events"]
                    .as_array()
                    .and_then(|e| e.last())
                    .and_then(|e| e["phase"].as_str())
                    .unwrap_or("");
                let message = j["events"]
                    .as_array()
                    .and_then(|e| e.last())
                    .and_then(|e| e["message"].as_str())
                    .unwrap_or("");
                set_status(&weak, Ok(format!("{phase} {message}").trim().to_string()));
                if state == "done" {
                    set_status(&weak, Ok("加载完成".into()));
                    refresh_async(weak.clone());
                    return;
                }
                if state == "failed" {
                    set_status(&weak, Err(j["error"].as_str().unwrap_or("load failed").to_string()));
                    return;
                }
            }
            set_status(&weak, Err("加载超时".into()));
        }
        Err(e) => set_status(&weak, Err(e)),
    }
}

fn start_service() -> Result<String, String> {
    run_wsl(&["systemctl", "start", "flashserver"])?;
    spawn_keepalive();
    Ok("服务已启动".into())
}

fn stop_service() -> Result<String, String> {
    let _ = run_wsl(&["systemctl", "stop", "flashserver"]);
    let _ = run_wsl(&["pkill", "-f", "sleep infinity"]);
    Ok("服务已停止".into())
}

#[cfg(windows)]
fn run_wsl(args: &[&str]) -> Result<(), String> {
    let mut cmd = Command::new("wsl.exe");
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
    let mut cmd = Command::new("wsl.exe");
    cmd.args(["-d", "Ubuntu", "-u", "root", "--", "sleep", "infinity"]);
    hide(&mut cmd);
    let _ = cmd.spawn();
}

#[cfg(windows)]
fn hide(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(0x08000000);
}

#[cfg(not(windows))]
fn run_wsl(args: &[&str]) -> Result<(), String> {
    let (program, rest) = args.split_first().ok_or_else(|| "empty command".to_string())?;
    let out = Command::new(program)
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

fn set_autostart(enabled: bool) -> Result<String, String> {
    #[cfg(windows)]
    {
        let setup = setup_bin().ok_or_else(|| "找不到 flashserver-setup.exe".to_string())?;
        let arg = if enabled { "--start-service" } else { "--stop-service" };
        let script = format!(
            "Start-Process -Verb RunAs -WindowStyle Hidden -Wait -FilePath '{}' -ArgumentList '{}'",
            setup.replace('\'', "''"),
            arg
        );
        let out = Command::new("powershell.exe")
            .args(["-NoProfile", "-Command", &script])
            .output()
            .map_err(|e| e.to_string())?;
        if out.status.success() { Ok(if enabled { "已启用开机启动" } else { "已禁用开机启动" }.into()) }
        else { Err("管理员授权被取消或执行失败".into()) }
    }
    #[cfg(not(windows))]
    {
        let action = if enabled { "enable" } else { "disable" };
        let out = Command::new("systemctl").args([action, "flashserver"]).output().map_err(|e| e.to_string())?;
        if out.status.success() { Ok("已更新开机启动".into()) } else { Err(String::from_utf8_lossy(&out.stderr).trim().to_string()) }
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

// ---------- helpers ----------

fn get_json(path: &str) -> Option<Value> {
    let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(3)).build();
    agent
        .get(&format!("{BASE}{path}"))
        .call()
        .ok()?
        .into_json::<Value>()
        .ok()
}

fn post_json(path: &str, body: &Value) -> Result<Value, String> {
    let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(60)).build();
    match agent.post(&format!("{BASE}{path}")).send_json(body) {
        Ok(resp) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(_, resp)) => {
            let text = resp.into_string().unwrap_or_default();
            Err(text)
        }
        Err(e) => Err(e.to_string()),
    }
}

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

fn translate_autostart(value: &str) -> &'static str {
    match value {
        "enabled" => "已启用",
        "disabled" => "已禁用",
        _ => "未知",
    }
}

fn render_chart(lines: &[(&[f32], (u8, u8, u8))], w: u32, h: u32) -> Image {
    let mut buffer = SharedPixelBuffer::<Rgba8Pixel>::new(w, h);
    {
        let pixels = buffer.make_mut_slice();
        for p in pixels.iter_mut() {
            *p = Rgba8Pixel { r: 255, g: 255, b: 255, a: 255 };
        }
        for frac in [0.25f32, 0.5, 0.75] {
            let y = (h as f32 * frac) as u32;
            for x in 0..w {
                pixels[(y * w + x) as usize] = Rgba8Pixel { r: 232, g: 234, b: 237, a: 255 };
            }
        }
        for (data, color) in lines {
            if data.len() < 2 {
                continue;
            }
            for i in 1..data.len() {
                let x0 = ((i - 1) as f32 / (data.len() - 1) as f32 * (w - 1) as f32) as i32;
                let x1 = (i as f32 / (data.len() - 1) as f32 * (w - 1) as f32) as i32;
                let y0 = ((h - 6) as f32 - data[i - 1].clamp(0.0, 100.0) / 100.0 * (h - 12) as f32) as i32;
                let y1 = ((h - 6) as f32 - data[i].clamp(0.0, 100.0) / 100.0 * (h - 12) as f32) as i32;
                draw_line(pixels, w, h, x0, y0, x1, y1, *color);
            }
        }
    }
    Image::from_rgba8(buffer)
}

fn draw_line(pixels: &mut [Rgba8Pixel], w: u32, h: u32, x0: i32, y0: i32, x1: i32, y1: i32, color: (u8, u8, u8)) {
    let dx = (x1 - x0).abs();
    let dy = (y1 - y0).abs();
    let steps = dx.max(dy).max(1);
    for i in 0..=steps {
        let t = i as f32 / steps as f32;
        let x = x0 as f32 + (x1 - x0) as f32 * t;
        let y = y0 as f32 + (y1 - y0) as f32 * t;
        paint(pixels, w, h, x as i32, y as i32, color);
        paint(pixels, w, h, x as i32 + 1, y as i32, color);
    }
}

fn paint(pixels: &mut [Rgba8Pixel], w: u32, h: u32, x: i32, y: i32, color: (u8, u8, u8)) {
    if x < 0 || y < 0 || x >= w as i32 || y >= h as i32 {
        return;
    }
    pixels[(y as u32 * w + x as u32) as usize] = Rgba8Pixel { r: color.0, g: color.1, b: color.2, a: 255 };
}
