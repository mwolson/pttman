use anyhow::{bail, Result};
use clap::{ArgAction, Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(
    name = "pttman",
    version,
    about = "Push-to-talk microphone control with a daemon-backed command queue"
)]
pub struct Cli {
    /// Operate on all audio sources
    #[arg(long = "all-sources", action = ArgAction::SetTrue)]
    pub all_sources: bool,

    /// Audio source name to control
    #[arg(long, value_name = "SOURCE", conflicts_with = "all_sources")]
    pub source: Option<String>,

    /// Mute managed sources when the daemon starts
    #[arg(long = "start-muted", action = ArgAction::SetTrue, conflicts_with = "no_start_muted")]
    pub start_muted: bool,

    /// Leave mic state untouched when the daemon starts
    #[arg(long = "no-start-muted", action = ArgAction::SetTrue)]
    pub no_start_muted: bool,

    #[command(subcommand)]
    pub command: Option<Command>,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Print the default source from the config file
    GetDefaultSource,
    /// Install and enable the service (systemd or OpenRC)
    InstallService,
    /// List available audio sources
    ListSources,
    /// Mute the microphone and record it as the preference
    Mute,
    /// Temporarily unmute for push-to-talk without changing preference
    Press,
    /// Temporarily mute for push-to-talk without changing preference
    Release,
    /// Ask the daemon to reapply its desired mute state
    Resync,
    /// Set the default source and signal the daemon
    SetDefaultSource {
        /// Audio source name
        source: String,
    },
    /// Print the current microphone state
    Status,
    /// Toggle the microphone mute state and record the new state
    Toggle,
    /// Disable and remove the service (systemd or OpenRC)
    UninstallService,
    /// Unmute the microphone and record it as the preference
    Unmute,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Overrides {
    pub all_sources: bool,
    pub source: Option<String>,
    pub start_muted: Option<bool>,
}

pub fn overrides(cli: &Cli) -> Result<Overrides> {
    if cli.start_muted && cli.no_start_muted {
        bail!("--start-muted and --no-start-muted are mutually exclusive");
    }
    Ok(Overrides {
        all_sources: cli.all_sources,
        source: cli.source.clone(),
        start_muted: if cli.start_muted {
            Some(true)
        } else if cli.no_start_muted {
            Some(false)
        } else {
            None
        },
    })
}
