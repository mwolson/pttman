use std::os::unix::net::UnixDatagram;
use std::path::{Path, PathBuf};

use anyhow::Result;

use crate::daemon::Action;

pub fn send_action(action: Action) -> Result<()> {
    let client = UnixDatagram::unbound()?;
    client.send_to(action.as_str().as_bytes(), socket_path())?;
    Ok(())
}

pub fn socket_path() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(format!("/run/user/{}", effective_uid().unwrap_or(0))))
        .join("pttman.sock")
}

pub fn cleanup_socket(path: &Path) {
    let _ = std::fs::remove_file(path);
}

pub fn daemon_is_alive(path: &Path) -> bool {
    if !path.exists() {
        return false;
    }
    match UnixDatagram::unbound() {
        Ok(probe) => probe.connect(path).is_ok(),
        Err(_) => false,
    }
}

fn effective_uid() -> Option<u32> {
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
