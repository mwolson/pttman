use std::path::PathBuf;

use anyhow::{bail, Result};

pub fn check_required() -> Result<()> {
    if which("pactl").is_none() {
        eprintln!("Error: 'pactl' is required but not found in PATH.");
        bail!("missing required commands");
    }
    Ok(())
}

pub fn which(cmd: &str) -> Option<PathBuf> {
    let path_env = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_env) {
        let candidate = dir.join(cmd);
        if is_executable(&candidate) {
            return Some(candidate);
        }
    }
    None
}

fn is_executable(path: &std::path::Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(metadata) = std::fs::metadata(path) {
            return metadata.is_file() && metadata.permissions().mode() & 0o111 != 0;
        }
    }
    #[cfg(not(unix))]
    {
        return path.is_file();
    }
    #[cfg(unix)]
    false
}
