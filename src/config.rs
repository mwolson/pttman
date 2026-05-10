use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use regex::Regex;

use crate::cli::Overrides;
use crate::daemon::Action;
use crate::pactl::{self, PactlRunner};
use crate::socket;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    pub all_sources: bool,
    pub source: Option<String>,
    pub start_muted: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            all_sources: false,
            source: None,
            start_muted: true,
        }
    }
}

impl Config {
    pub fn build(overrides: &Overrides, conf_path: Option<&Path>) -> Result<Self> {
        let mut config = Self::default();
        if let Some(path) = conf_path {
            if path.exists() {
                config.apply_file(path)?;
            }
        }
        config.apply_overrides(overrides);
        Ok(config)
    }

    pub fn apply_file(&mut self, path: &Path) -> Result<()> {
        let text = std::fs::read_to_string(path)
            .with_context(|| format!("reading config file {}", path.display()))?;
        for (flag, value) in parse_conf(&text, path)? {
            self.apply_flag(&flag, &value, path)?;
        }
        if self.all_sources && self.source.is_some() {
            bail!(
                "--all-sources and --source are mutually exclusive in {}",
                path.display()
            );
        }
        Ok(())
    }

    pub fn apply_overrides(&mut self, overrides: &Overrides) {
        if overrides.all_sources {
            self.all_sources = true;
            self.source = None;
        }
        if let Some(source) = &overrides.source {
            self.all_sources = false;
            self.source = Some(source.clone());
        }
        if let Some(start_muted) = overrides.start_muted {
            self.start_muted = start_muted;
        }
    }

    pub fn resolve_sources(&self, pactl: &dyn PactlRunner) -> Result<Vec<String>> {
        if let Some(source) = &self.source {
            return Ok(vec![source.clone()]);
        }
        pactl::get_all_source_names(pactl)
    }

    fn apply_flag(&mut self, flag: &str, value: &str, path: &Path) -> Result<()> {
        match flag {
            "--all-sources" => {
                self.all_sources = parse_bool_strict(value).ok_or_else(|| {
                    anyhow!(
                        "--all-sources must be 'true' or 'false' in {}",
                        path.display()
                    )
                })?;
            }
            "--source" => {
                self.source = Some(value.to_string());
            }
            "--start-muted" => {
                self.start_muted = parse_bool_strict(value).ok_or_else(|| {
                    anyhow!(
                        "--start-muted must be 'true' or 'false' in {}",
                        path.display()
                    )
                })?;
            }
            _ => bail!("unsupported flag '{}' in {}", flag, path.display()),
        }
        Ok(())
    }
}

pub fn print_default_source() -> Result<()> {
    let Some(path) = default_conf_path() else {
        bail!("cannot determine config path");
    };
    if !path.exists() {
        bail!(
            "no config file found at {}; without a default, pttman operates on all sources",
            path.display()
        );
    }
    let text = std::fs::read_to_string(&path)?;
    for (flag, value) in parse_conf(&text, &path)? {
        if flag == "--source" {
            println!("{}", value);
            return Ok(());
        }
    }
    bail!(
        "no --source entry found in {}; without a default, pttman operates on all sources",
        path.display()
    );
}

pub fn set_default_source(source: &str) -> Result<()> {
    let path = default_conf_path().context("cannot determine config path")?;
    let flag_prefix = "--source=";
    let mut lines = Vec::new();
    let mut replaced = false;
    if path.exists() {
        for line in std::fs::read_to_string(&path)?.lines() {
            if line.trim_start().starts_with(flag_prefix) {
                lines.push(format!("{}{}", flag_prefix, source));
                replaced = true;
            } else {
                lines.push(line.to_string());
            }
        }
    }
    if !replaced {
        lines.push(format!("{}{}", flag_prefix, source));
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, format!("{}\n", lines.join("\n")))?;
    println!("Wrote {}{} to {}", flag_prefix, source, path.display());
    let _ = socket::send_action(Action::Reload);
    Ok(())
}

pub fn default_conf_path() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("pttman.conf"))
}

pub fn parse_conf(text: &str, path: &Path) -> Result<Vec<(String, String)>> {
    let line_re = Regex::new(r"^(--[a-z][a-z0-9-]*)=(.+)$").expect("conf regex");
    let mut entries = Vec::new();
    for (line_num, raw_line) in text.lines().enumerate() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let captures = line_re.captures(line).ok_or_else(|| {
            anyhow!(
                "malformed line {} in {}: {}",
                line_num + 1,
                path.display(),
                line
            )
        })?;
        entries.push((captures[1].to_string(), captures[2].to_string()));
    }
    Ok(entries)
}

fn parse_bool_strict(value: &str) -> Option<bool> {
    match value {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    }
}
