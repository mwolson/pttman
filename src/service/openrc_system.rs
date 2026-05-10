use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;

use anyhow::{bail, Context, Result};
use tracing::info;

use crate::service;
use crate::service_files;

const INIT_PATH: &str = "/etc/init.d/pttman";

pub fn install() -> Result<()> {
    if !service::is_root() {
        bail!("OpenRC system install must be run as root");
    }
    let script = service::render_template(service_files::OPENRC_SYSTEM, "/usr/local/bin/pttman")?;
    fs::write(INIT_PATH, script).with_context(|| format!("writing {}", INIT_PATH))?;
    let mut perms = fs::metadata(INIT_PATH)?.permissions();
    perms.set_mode(0o755);
    fs::set_permissions(INIT_PATH, perms)?;
    info!("Wrote {}", INIT_PATH);
    run(&["rc-update", "add", "pttman", "default"])?;
    info!("Enabled pttman (system). Start with: rc-service pttman start");
    Ok(())
}

pub fn uninstall() -> Result<()> {
    if !service::is_root() {
        bail!("OpenRC system uninstall must be run as root");
    }
    let _ = run(&["rc-service", "pttman", "stop"]);
    let _ = run(&["rc-update", "del", "pttman", "default"]);
    if Path::new(INIT_PATH).exists() {
        fs::remove_file(INIT_PATH).with_context(|| format!("removing {}", INIT_PATH))?;
        info!("Removed {}", INIT_PATH);
    }
    Ok(())
}

fn run(args: &[&str]) -> Result<()> {
    let status = Command::new(args[0])
        .args(&args[1..])
        .status()
        .with_context(|| format!("running {}", args.join(" ")))?;
    if !status.success() {
        bail!("{} failed with {}", args.join(" "), status);
    }
    Ok(())
}
