use std::collections::HashSet;
use std::process::Command;

use anyhow::{anyhow, Context, Result};

use crate::config::Config;

pub trait PactlRunner {
    fn run(&self, args: &[&str]) -> Result<String>;
    fn run_ok(&self, args: &[&str]) -> String;
}

pub struct RealPactl;

impl PactlRunner for RealPactl {
    fn run(&self, args: &[&str]) -> Result<String> {
        let output = Command::new("pactl")
            .args(args)
            .env("LC_ALL", "C")
            .output()
            .with_context(|| format!("running pactl {}", args.join(" ")))?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(anyhow!(
                "pactl {} failed: {}",
                args.join(" "),
                stderr.trim()
            ));
        }
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    }

    fn run_ok(&self, args: &[&str]) -> String {
        match Command::new("pactl").args(args).env("LC_ALL", "C").output() {
            Ok(out) if out.status.success() => String::from_utf8_lossy(&out.stdout).into_owned(),
            _ => String::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MuteState {
    Muted,
    Unmuted,
    Unknown,
}

impl MuteState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Muted => "muted",
            Self::Unmuted => "unmuted",
            Self::Unknown => "unknown",
        }
    }

    pub fn muted_bool(self) -> Option<bool> {
        match self {
            Self::Muted => Some(true),
            Self::Unmuted => Some(false),
            Self::Unknown => None,
        }
    }
}

pub fn get_all_source_names(runner: &dyn PactlRunner) -> Result<Vec<String>> {
    let out = runner.run(&["list", "sources", "short"])?;
    Ok(parse_source_names(&out))
}

pub fn parse_source_names(out: &str) -> Vec<String> {
    out.lines()
        .filter_map(|line| {
            let name = line.split('\t').nth(1)?;
            (!name.contains(".monitor")).then(|| name.to_string())
        })
        .collect()
}

pub fn get_default_source_name(runner: &dyn PactlRunner) -> String {
    let out = runner.run_ok(&["get-default-source"]);
    let trimmed = out.trim();
    if trimmed.is_empty() {
        "@DEFAULT_SOURCE@".into()
    } else {
        trimmed.into()
    }
}

pub fn get_source_descriptions(runner: &dyn PactlRunner) -> Vec<(String, String)> {
    parse_source_descriptions(&runner.run_ok(&["list", "sources"]))
}

pub fn parse_source_descriptions(out: &str) -> Vec<(String, String)> {
    let mut descriptions = Vec::new();
    let mut current_name: Option<String> = None;
    for line in out.lines() {
        let trimmed = line.trim();
        if let Some(name) = trimmed.strip_prefix("Name: ") {
            current_name = Some(name.to_string());
        } else if let Some(desc) = trimmed.strip_prefix("Description: ") {
            if let Some(name) = current_name.take() {
                descriptions.push((name, desc.trim().to_string()));
            }
        }
    }
    descriptions
}

pub fn get_mute_state(runner: &dyn PactlRunner, source: &str) -> MuteState {
    let out = runner.run_ok(&["get-source-mute", source]);
    if out.contains("yes") {
        MuteState::Muted
    } else if out.contains("no") {
        MuteState::Unmuted
    } else {
        MuteState::Unknown
    }
}

pub fn set_mute(runner: &dyn PactlRunner, sources: &[String], mute: bool) -> Result<()> {
    let value = if mute { "1" } else { "0" };
    for source in sources {
        runner.run(&["set-source-mute", source, value])?;
    }
    Ok(())
}

pub fn toggle_mute(runner: &dyn PactlRunner, sources: &[String]) -> Result<()> {
    for source in sources {
        runner.run(&["set-source-mute", source, "toggle"])?;
    }
    Ok(())
}

pub fn print_sources(runner: &dyn PactlRunner, config: &Config) -> Result<()> {
    let sources = get_all_source_names(runner)?;
    if sources.is_empty() {
        anyhow::bail!("no audio sources found");
    }
    let selected = config
        .source
        .clone()
        .unwrap_or_else(|| get_default_source_name(runner));
    let descriptions = get_source_descriptions(runner);
    for name in sources {
        let desc = descriptions
            .iter()
            .find_map(|(source, desc)| (source == &name).then_some(desc.as_str()));
        match desc {
            Some(desc) if name == selected => {
                println!(
                    "{}  ({})  {}  *",
                    name,
                    desc,
                    get_mute_state(runner, &name).as_str()
                );
            }
            Some(desc) => {
                println!(
                    "{}  ({})  {}",
                    name,
                    desc,
                    get_mute_state(runner, &name).as_str()
                );
            }
            None if name == selected => {
                println!("{}  {}  *", name, get_mute_state(runner, &name).as_str());
            }
            None => {
                println!("{}  {}", name, get_mute_state(runner, &name).as_str());
            }
        }
    }
    Ok(())
}

pub fn print_status(runner: &dyn PactlRunner, sources: &[String]) -> Result<()> {
    let all_sources = get_all_source_names(runner)?;
    let default_name = get_default_source_name(runner);
    let managed: HashSet<String> = sources
        .iter()
        .map(|s| {
            if s == "@DEFAULT_SOURCE@" {
                default_name.clone()
            } else {
                s.clone()
            }
        })
        .collect();

    for source in all_sources {
        let marker = if managed.contains(&source) { " *" } else { "" };
        println!(
            "source {}: {}{}",
            source,
            get_mute_state(runner, &source).as_str(),
            marker
        );
    }
    Ok(())
}
