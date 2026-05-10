use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::Command;

use anyhow::{bail, Context, Result};
use tracing::info;

use crate::service;
use crate::service_files;

pub fn install() -> Result<()> {
    if service::is_root() {
        bail!("OpenRC user install must not be run as root");
    }
    let init_dir = user_init_dir()?;
    fs::create_dir_all(&init_dir).with_context(|| format!("creating {}", init_dir.display()))?;
    let init_path = init_dir.join("pttman");
    let script = service::render_template(service_files::OPENRC_USER, "$HOME/.local/bin/pttman")?;
    fs::write(&init_path, script).with_context(|| format!("writing {}", init_path.display()))?;
    let mut perms = fs::metadata(&init_path)?.permissions();
    perms.set_mode(0o755);
    fs::set_permissions(&init_path, perms)?;
    info!("Wrote {}", init_path.display());
    run(&["rc-update", "--user", "add", "pttman", "default"])?;
    info!("Enabled pttman (user). Start with: rc-service --user pttman start");
    Ok(())
}

pub fn uninstall() -> Result<()> {
    if service::is_root() {
        bail!("OpenRC user uninstall must not be run as root");
    }
    let _ = run(&["rc-service", "--user", "pttman", "stop"]);
    let _ = run(&["rc-update", "--user", "del", "pttman", "default"]);
    let init_path = user_init_dir()?.join("pttman");
    if init_path.exists() {
        fs::remove_file(&init_path).with_context(|| format!("removing {}", init_path.display()))?;
        info!("Removed {}", init_path.display());
    }
    Ok(())
}

fn user_init_dir() -> Result<PathBuf> {
    if let Some(dir) = std::env::var_os("XDG_CONFIG_HOME") {
        return Ok(PathBuf::from(dir).join("rc").join("init.d"));
    }
    let home = std::env::var_os("HOME").context("HOME env var not set")?;
    Ok(PathBuf::from(home)
        .join(".config")
        .join("rc")
        .join("init.d"))
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
