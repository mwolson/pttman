use std::process::Command;

use anyhow::{anyhow, bail, Result};

use crate::deps;

pub mod openrc_system;
pub mod openrc_user;
pub mod systemd;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InitSystem {
    Systemd,
    OpenRcUser,
    OpenRcSystem,
}

pub fn detect() -> Result<InitSystem> {
    if deps::which("systemctl").is_some() {
        return Ok(InitSystem::Systemd);
    }
    if deps::which("rc-service").is_some() {
        if openrc_supports_user() {
            return Ok(InitSystem::OpenRcUser);
        }
        return Ok(InitSystem::OpenRcSystem);
    }
    bail!("no supported init system found (systemctl or rc-service)");
}

pub fn install() -> Result<()> {
    match detect()? {
        InitSystem::Systemd => systemd::install(),
        InitSystem::OpenRcUser => openrc_user::install(),
        InitSystem::OpenRcSystem => openrc_system::install(),
    }
}

pub fn uninstall() -> Result<()> {
    match detect()? {
        InitSystem::Systemd => systemd::uninstall(),
        InitSystem::OpenRcUser => openrc_user::uninstall(),
        InitSystem::OpenRcSystem => openrc_system::uninstall(),
    }
}

pub fn effective_uid() -> Option<u32> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    for line in status.lines() {
        if let Some(rest) = line.strip_prefix("Uid:") {
            let mut parts = rest.split_whitespace();
            let _real = parts.next()?;
            return parts.next()?.parse().ok();
        }
    }
    None
}

pub fn is_root() -> bool {
    effective_uid() == Some(0)
}

pub fn render_template(template: &str, placeholder: &str) -> Result<String> {
    let exe_str = service_executable()?;
    Ok(template.replace(placeholder, &exe_str))
}

fn service_executable() -> Result<String> {
    if let Some(exe) = std::env::var_os("SERVICE_EXECUTABLE") {
        return exe
            .into_string()
            .map_err(|_| anyhow!("SERVICE_EXECUTABLE is not valid UTF-8"));
    }
    let exe = std::env::current_exe()?;
    exe.to_str()
        .map(str::to_owned)
        .ok_or_else(|| anyhow!("current exe path is not valid UTF-8"))
}

fn openrc_supports_user() -> bool {
    let Ok(output) = Command::new("openrc").arg("--version").output() else {
        return false;
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    parse_openrc_version(&stdout)
        .map(|(maj, min)| (maj, min) >= (0, 60))
        .unwrap_or(false)
}

pub fn parse_openrc_version(s: &str) -> Option<(u32, u32)> {
    for token in s.split_whitespace() {
        let digits: String = token
            .chars()
            .take_while(|c| c.is_ascii_digit() || *c == '.')
            .collect();
        if digits.is_empty() {
            continue;
        }
        let mut parts = digits.split('.');
        let maj: u32 = parts.next()?.parse().ok()?;
        let min = parts.next().and_then(|p| p.parse().ok()).unwrap_or(0);
        return Some((maj, min));
    }
    None
}
