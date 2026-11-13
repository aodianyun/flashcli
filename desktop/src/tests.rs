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
