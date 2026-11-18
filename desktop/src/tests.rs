//! Unit tests for the pure desktop helpers (no egui, no Windows APIs).

use super::*;

#[test]
fn firewall_ports_accept_ports_and_ranges() {
    assert!(valid_firewall_ports(""));
    assert!(valid_firewall_ports("   "));
    assert!(valid_firewall_ports("8790"));
    assert!(valid_firewall_ports("18000-18999"));
    assert!(valid_firewall_ports("8790, 18000-18999, 20000"));
    assert!(valid_firewall_ports(" 18000 - 18999 "));
    assert!(valid_firewall_ports("1-65535"));
}

#[test]
fn firewall_ports_reject_invalid_input() {
    for value in [
        "0",
        "8790,",
        ",8790",
        "8790,,8800",
        "abc",
        "18000-",
        "-18999",
        "18999-18000",
        "0-100",
        "70000",
        "1.5",
    ] {
        assert!(!valid_firewall_ports(value), "accepted {value:?}");
    }
}

#[test]
fn app_platform_support_checks_os_and_arch() {
    let supported = serde_json::json!({
        "supported": {"os": [app_os_key()], "arch": [app_arch_key()]}
    });
    assert!(app_platform_supported(&supported));

    let other_os = if app_os_key() == "linux" { "windows" } else { "linux" };
    let wrong_os = serde_json::json!({
        "supported": {"os": [other_os], "arch": [app_arch_key()]}
    });
    assert!(!app_platform_supported(&wrong_os));
    assert!(!app_platform_supported(&serde_json::json!({})));
}

#[test]
fn install_command_prefers_the_arch_specific_entry() {
    let mut commands = serde_json::Map::new();
    commands.insert(
        app_os_key().to_string(),
        Value::String("echo generic".into()),
    );
    commands.insert(
        format!("{}/{}", app_os_key(), app_arch_key()),
        Value::String("echo arch".into()),
    );
    let manifest = serde_json::json!({"install": {"commands": commands}});
    assert_eq!(install_command(&manifest).as_deref(), Some("echo arch"));
    assert_eq!(install_command(&serde_json::json!({})), None);
}

#[test]
fn app_cover_url_ignores_blank_values() {
    let app = serde_json::json!({"cover_url": " https://cdn.test/a.png "});
    assert_eq!(app_cover_url(&app).as_deref(), Some("https://cdn.test/a.png"));
    assert_eq!(app_cover_url(&serde_json::json!({"cover_url": "  "})), None);
    assert_eq!(app_cover_url(&serde_json::json!({})), None);
}

#[test]
fn app_install_commands_lists_every_platform() {
    let manifest = serde_json::json!({"install": {"commands": {
        "windows": "irm x | iex",
        "linux": "curl -fsSL x | bash",
        "darwin/x86_64": "https://example.com/dmg"
    }}});
    let commands = app_install_commands(&manifest);
    let keys: Vec<&str> = commands.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, vec!["darwin/x86_64", "linux", "windows"]);
    assert_eq!(commands[0].1, "https://example.com/dmg");
    assert!(app_install_commands(&serde_json::json!({})).is_empty());
}

#[test]
fn app_platform_command_key_prefers_the_arch_key() {
    let manifest = serde_json::json!({"install": {"commands": {
        (app_os_key()): "generic",
        (format!("{}/{}", app_os_key(), app_arch_key())): "exact"
    }}});
    assert_eq!(
        app_platform_command_key(&manifest).as_deref(),
        Some(format!("{}/{}", app_os_key(), app_arch_key()).as_str())
    );
    let generic = serde_json::json!({"install": {"commands": {(app_os_key()): "generic"}}});
    assert_eq!(app_platform_command_key(&generic).as_deref(), Some(app_os_key()));
    assert_eq!(app_platform_command_key(&serde_json::json!({})), None);
}

#[test]
fn csv_list_joins_strings_only() {
    let value = serde_json::json!(["linux", "darwin", 3]);
    assert_eq!(csv_list(&value), "linux, darwin");
    assert_eq!(csv_list(&serde_json::json!(null)), "");
}

#[test]
fn app_domains_are_unique_and_skip_blanks() {
    let list = vec![
        serde_json::json!({"domain": "通用Agent"}),
        serde_json::json!({"domain": "专用Agent"}),
        serde_json::json!({"domain": " 通用Agent "}),
        serde_json::json!({"domain": ""}),
        serde_json::json!({}),
    ];
    assert_eq!(app_domains(&list), vec!["通用Agent", "专用Agent"]);
    assert!(app_domains(&[]).is_empty());
}

#[test]
fn detail_local_merge_replaces_the_state() {
    let mut detail = serde_json::json!({"local": {"state": "ready", "models": []}});
    merge_detail_local(&mut detail, Some(serde_json::json!({"state": "stopped"})));
    assert_eq!(detail["local"]["state"], "stopped");
    // Uninstalled: the local block is emptied.
    merge_detail_local(&mut detail, None);
    assert_eq!(detail["local"], serde_json::json!({}));
}

#[test]
fn list_state_merge_updates_the_installed_flag() {
    let mut app = serde_json::json!({"installed": false, "state": ""});
    merge_list_state(&mut app, true, "ready");
    assert_eq!(app["installed"], true);
    assert_eq!(app["state"], "ready");
    merge_list_state(&mut app, false, "");
    assert_eq!(app["installed"], false);
}

#[test]
fn app_job_phase_tracks_the_install_steps() {
    assert_eq!(app_job_phase("$ npm install -g x", "安装应用"), "安装应用");
    assert_eq!(
        app_job_phase("Preparing model xym/gemma4_e2b_it:1.0.1 ...", "安装应用"),
        "准备模型"
    );
    assert_eq!(app_job_phase("  pull  45%  1.2 GB", "准备模型"), "准备模型");
    assert_eq!(
        app_job_phase("Starting xym/gemma4_e2b_it", "准备模型"),
        "启动模型"
    );
    assert_eq!(app_job_phase("Installed xym/demo 1.0.0", "启动模型"), "完成");
    assert_eq!(
        app_job_phase("下载中 45%（1/2 字节）", "安装应用"),
        "安装应用"
    );
    assert_eq!(app_job_phase("noise", "启动模型"), "启动模型");
}

#[test]
fn lifecycle_jobs_start_with_their_own_phase() {
    assert_eq!(default_app_job_phase("启动"), "启动模型");
    assert_eq!(default_app_job_phase("停止"), "停止模型");
    assert_eq!(default_app_job_phase("安装"), "安装应用");
    assert_eq!(
        app_job_phase("stopping xym/gemma4_e2b_it:1.0.1 ...", "启动模型"),
        "停止模型"
    );
}

#[test]
fn app_job_status_names_the_model_for_start_and_stop() {
    let mut job = AppJobState {
        verb: "启动".to_string(),
        phase: "启动模型".to_string(),
        percent: None,
        running: true,
        log: "starting xym/gemma4_e2b_it:1.0.1 ...\n".to_string(),
    };
    assert_eq!(
        app_job_status_text(&job, "Grok CLI", ""),
        "正在启动模型 xym/gemma4_e2b_it:1.0.1"
    );
    job.verb = "停止".to_string();
    job.log = "stopping xym/gemma4_e2b_it:1.0.1 ...\n".to_string();
    assert_eq!(
        app_job_status_text(&job, "Grok CLI", ""),
        "正在停止模型 xym/gemma4_e2b_it:1.0.1"
    );
    job.verb = "启动".to_string();
    job.log.clear();
    assert_eq!(app_job_status_text(&job, "Grok CLI", ""), "正在启动模型…");
    job.verb = "安装".to_string();
    job.phase = "安装应用".to_string();
    assert_eq!(
        app_job_status_text(&job, "Grok CLI", ""),
        "正在安装 Grok CLI · 安装应用"
    );
}

#[test]
fn installer_kinds_follow_the_extension() {
    assert!(matches!(
        installer_kind("https://x/a.exe?token=1"),
        InstallerKind::Exe
    ));
    assert!(matches!(installer_kind("https://x/a.MSI"), InstallerKind::Msi));
    assert!(matches!(
        installer_kind("https://x/a.dmg#frag"),
        InstallerKind::Dmg
    ));
    assert!(matches!(installer_kind("https://x/a.pkg"), InstallerKind::Pkg));
    assert!(matches!(
        installer_kind("https://example.com/demo"),
        InstallerKind::Page
    ));
    assert!(installer_is_runnable(InstallerKind::Exe));
    assert!(installer_is_runnable(InstallerKind::Msi));
    assert!(!installer_is_runnable(InstallerKind::Page));
}

#[test]
fn installer_file_names_are_sanitized() {
    assert_eq!(
        installer_file_name("https://x/WorkBuddy-5.exe?token=1", InstallerKind::Exe),
        "WorkBuddy-5.exe"
    );
    assert_eq!(
        installer_file_name("https://x/", InstallerKind::Exe),
        "installer.exe"
    );
    assert_eq!(
        installer_file_name("https://x/setup.msi", InstallerKind::Msi),
        "setup.msi"
    );
}

#[test]
fn app_install_body_makes_the_script_decision_explicit() {
    let ran = app_install_body("1.0.0", true, true);
    assert_eq!(ran["version"], "1.0.0");
    assert_eq!(ran["install_command"], "client");
    assert_eq!(ran["client_os"], app_os_key());
    assert_eq!(ran["client_arch"], app_arch_key());
    assert_eq!(ran["force"], true);
    let skip = app_install_body("1.0.0", false, false);
    assert_eq!(skip["install_command"], "skip");
    assert_eq!(skip["client_os"], app_os_key());
    assert_eq!(skip["force"], false);
}

#[test]
fn local_command_uses_the_platform_shell() {
    let (program, args) = local_command("echo hi");
    if cfg!(windows) {
        assert_eq!(program, "powershell");
        assert!(args.iter().any(|a| a == "-Command"));
    } else {
        assert_eq!(program, "sh");
        assert_eq!(args[0], "-c");
    }
    assert_eq!(args.last().map(String::as_str), Some("echo hi"));
}

#[test]
fn app_install_command_is_classified() {
    assert!(is_url_command("https://example.com/demo"));
    assert!(is_url_command("  HTTP://example.com/demo "));
    assert!(!is_url_command("irm https://example.com/demo | iex"));
    assert!(!is_url_command("bash install.sh"));
    assert!(!is_url_command(""));
}

#[test]
fn default_app_bundles_selects_default_entries() {
    let manifest: Value = serde_json::from_str(
        r#"{"model":{"bundles":[
            {"bundle":"a/one:1","default":true},
            {"bundle":"a/two:1","default":false},
            {"bundle":"a/three:1"}
        ]}}"#,
    )
    .unwrap();
    assert_eq!(default_app_bundles(&manifest), vec!["a/one:1".to_string()]);
    assert!(default_app_bundles(&Value::Null).is_empty());
}

#[test]
fn app_reference_matches_the_daemon_format() {
    assert_eq!(app_reference("xym", "demo", "1.0.0"), "xym/demo:1.0.0");
    assert_eq!(app_reference("xym", "demo", ""), "xym/demo");
}

#[test]
fn app_job_log_dedupes_and_caps() {
    let mut log = String::new();
    append_app_log(&mut log, "preparing a/one");
    append_app_log(&mut log, "preparing a/one");
    append_app_log(&mut log, "   ");
    assert_eq!(log, "preparing a/one\n");

    for i in 0..400 {
        append_app_log(&mut log, &format!("line {i}"));
    }
    assert_eq!(log.lines().count(), 300);
    assert_eq!(log.lines().last().unwrap(), "line 399");
}

#[test]
fn app_log_tail_returns_the_last_lines() {
    assert_eq!(app_log_tail("a\nb\nc\n\n", 2), vec!["b", "c"]);
    assert_eq!(app_log_tail("only", 5), vec!["only"]);
    assert!(app_log_tail("", 5).is_empty());
}

#[test]
fn settings_tolerate_missing_optional_fields() {
    let s: Settings = serde_json::from_str(r#"{"dark":true}"#).unwrap();
    assert!(s.dark);
    assert!(s.wsl_ports.is_empty());
    assert!(!s.stop_wsl);
}

#[test]
fn settings_roundtrip() {
    let s = Settings {
        dark: false,
        wsl_ports: "18000-18999".into(),
        stop_wsl: true,
    };
    let text = serde_json::to_string(&s).unwrap();
    let back: Settings = serde_json::from_str(&text).unwrap();
    assert!(!back.dark);
    assert_eq!(back.wsl_ports, "18000-18999");
    assert!(back.stop_wsl);
}

#[test]
fn wslconfig_replaces_managed_keys_only() {
    let text = "[wsl2]\nmemory=4GB\nnetworkingMode=nat\nswap=2GB\n\n[experimental]\nsparseVhd=true\n";
    let cfg = WslConfig {
        memory: "8GB".into(),
        processors: "8".into(),
        swap: String::new(),
        mirrored: true,
    };
    let out = update_wslconfig(text, &cfg);
    assert_eq!(
        out,
        "[wsl2]\nmemory=8GB\nprocessors=8\nnetworkingMode=mirrored\n\n[experimental]\nsparseVhd=true\n"
    );
}

#[test]
fn wslconfig_appends_section_when_missing() {
    let cfg = WslConfig {
        memory: "8GB".into(),
        ..Default::default()
    };
    assert_eq!(update_wslconfig("", &cfg), "[wsl2]\nmemory=8GB\n");

    let out = update_wslconfig("[experimental]\nsparseVhd=true\n", &cfg);
    assert_eq!(out, "[experimental]\nsparseVhd=true\n\n[wsl2]\nmemory=8GB\n");
}

#[test]
fn wslconfig_preserves_crlf() {
    let cfg = WslConfig {
        memory: "8GB".into(),
        ..Default::default()
    };
    let out = update_wslconfig("[wsl2]\r\nmemory=4GB\r\n", &cfg);
    assert_eq!(out, "[wsl2]\r\nmemory=8GB\r\n");
}

#[test]
fn wslconfig_empty_values_do_not_add_keys() {
    let cfg = WslConfig {
        memory: "  ".into(),
        processors: String::new(),
        swap: String::new(),
        mirrored: false,
    };
    assert_eq!(update_wslconfig("[wsl2]\nmemory=4GB\n", &cfg), "[wsl2]\n");
}
