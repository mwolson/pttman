use anyhow::Result;
use clap::Parser;
use pttman::{cli, config, daemon, deps, logging, pactl, service, signals, socket};
use tracing::error;

fn main() {
    logging::init();
    let parsed = cli::Cli::parse();
    match dispatch(parsed) {
        Ok(()) => {}
        Err(err) => {
            error!("{:#}", err);
            std::process::exit(1);
        }
    }
}

fn dispatch(parsed: cli::Cli) -> Result<()> {
    let overrides = cli::overrides(&parsed)?;
    let config = config::Config::build(&overrides, config::default_conf_path().as_deref())?;
    let pactl = pactl::RealPactl;

    match &parsed.command {
        Some(cli::Command::GetDefaultSource) => config::print_default_source(),
        Some(cli::Command::InstallService) => service::install(),
        Some(cli::Command::ListSources) => run_list_sources(&pactl, &config),
        Some(cli::Command::Mute) => run_client_or_direct(&pactl, &config, daemon::Action::Mute),
        Some(cli::Command::Press) => run_client_or_direct(&pactl, &config, daemon::Action::Press),
        Some(cli::Command::Release) => {
            run_client_or_direct(&pactl, &config, daemon::Action::Release)
        }
        Some(cli::Command::Resync) => socket::send_action(daemon::Action::Resync),
        Some(cli::Command::SetDefaultSource { source }) => config::set_default_source(source),
        Some(cli::Command::Status) => run_status(&pactl, &config),
        Some(cli::Command::Toggle) => run_client_or_direct(&pactl, &config, daemon::Action::Toggle),
        Some(cli::Command::UninstallService) => service::uninstall(),
        Some(cli::Command::Unmute) => run_client_or_direct(&pactl, &config, daemon::Action::Unmute),
        None => run_daemon(&pactl, config, overrides),
    }
}

fn run_daemon(
    pactl: &dyn pactl::PactlRunner,
    config: config::Config,
    overrides: cli::Overrides,
) -> Result<()> {
    deps::check_required()?;
    let sigs = signals::install()?;
    daemon::run(pactl, config, overrides, sigs)
}

fn run_client_or_direct(
    pactl: &dyn pactl::PactlRunner,
    config: &config::Config,
    action: daemon::Action,
) -> Result<()> {
    deps::check_required()?;
    match socket::send_action(action) {
        Ok(()) => Ok(()),
        Err(err) => {
            tracing::warn!(
                "daemon unavailable, running '{}' directly ({})",
                action,
                err
            );
            let sources = config.resolve_sources(pactl)?;
            daemon::run_direct_action(pactl, action, &sources)
        }
    }
}

fn run_list_sources(pactl: &dyn pactl::PactlRunner, config: &config::Config) -> Result<()> {
    deps::check_required()?;
    pactl::print_sources(pactl, config)
}

fn run_status(pactl: &dyn pactl::PactlRunner, config: &config::Config) -> Result<()> {
    deps::check_required()?;
    let sources = config.resolve_sources(pactl)?;
    pactl::print_status(pactl, &sources)
}
