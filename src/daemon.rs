use std::collections::HashMap;
use std::os::unix::net::UnixDatagram;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use tracing::{info, warn};

use crate::cli::Overrides;
use crate::config;
use crate::pactl::{self, PactlRunner};
use crate::signals;
use crate::socket;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    Mute,
    Press,
    Release,
    Reload,
    Resync,
    Toggle,
    Unmute,
}

impl Action {
    pub fn parse(raw: &[u8]) -> Result<Self> {
        match std::str::from_utf8(raw)?.trim() {
            "mute" => Ok(Self::Mute),
            "press" => Ok(Self::Press),
            "release" => Ok(Self::Release),
            "reload" => Ok(Self::Reload),
            "resync" => Ok(Self::Resync),
            "toggle" => Ok(Self::Toggle),
            "unmute" => Ok(Self::Unmute),
            command => bail!("unsupported action: {}", command),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Mute => "mute",
            Self::Press => "press",
            Self::Release => "release",
            Self::Reload => "reload",
            Self::Resync => "resync",
            Self::Toggle => "toggle",
            Self::Unmute => "unmute",
        }
    }
}

impl std::fmt::Display for Action {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone)]
pub struct State {
    pub auto_discover: bool,
    pub cli_all_sources: bool,
    pub cli_source: Option<String>,
    pub default_mute: bool,
    pub last_applied_mute: HashMap<String, bool>,
    pub per_source_desired: HashMap<String, bool>,
    pub sources: Vec<String>,
}

impl State {
    pub fn new(
        config: &config::Config,
        overrides: &Overrides,
        pactl: &dyn PactlRunner,
    ) -> Result<Self> {
        let sources = config.resolve_sources(pactl)?;
        Ok(Self {
            auto_discover: config.source.is_none(),
            cli_all_sources: overrides.all_sources,
            cli_source: overrides.source.clone(),
            default_mute: config.start_muted,
            last_applied_mute: HashMap::new(),
            per_source_desired: HashMap::new(),
            sources,
        })
    }

    pub fn effective_desired(&self, source: &str) -> bool {
        self.per_source_desired
            .get(source)
            .copied()
            .unwrap_or(self.default_mute)
    }

    pub fn refresh_sources(&mut self, pactl: &dyn PactlRunner) -> Result<()> {
        if !self.auto_discover {
            return Ok(());
        }
        let new_sources = pactl::get_all_source_names(pactl)?;
        if self.sources != new_sources {
            info!("Sources changed: {:?} -> {:?}", self.sources, new_sources);
            self.sources = new_sources;
        }
        Ok(())
    }

    pub fn reload_config(&mut self, pactl: &dyn PactlRunner) -> Result<()> {
        info!("Reloading config...");
        if self.cli_source.is_some() || self.cli_all_sources {
            info!("CLI flags take precedence, keeping current settings.");
            return Ok(());
        }
        let config = config::Config::build(
            &Overrides::default(),
            config::default_conf_path().as_deref(),
        )?;
        if let Some(source) = config.source {
            let new_sources = vec![source];
            self.auto_discover = false;
            if self.sources != new_sources {
                info!("Updated sources: {:?} -> {:?}", self.sources, new_sources);
                self.sources = new_sources;
            }
        } else {
            self.auto_discover = true;
            self.refresh_sources(pactl)?;
        }
        Ok(())
    }

    pub fn apply_mute(
        &mut self,
        pactl: &dyn PactlRunner,
        sources: &[String],
        mute: bool,
    ) -> Result<()> {
        if sources.is_empty() {
            return Ok(());
        }
        for source in sources {
            self.last_applied_mute.insert(source.clone(), mute);
        }
        pactl::set_mute(pactl, sources, mute)
    }

    pub fn run_action(&mut self, pactl: &dyn PactlRunner, action: Action) -> Result<()> {
        let sources = self.sources.clone();
        match action {
            Action::Mute => {
                self.apply_mute(pactl, &sources, true)?;
                for source in sources {
                    self.per_source_desired.insert(source, true);
                }
            }
            Action::Unmute => {
                self.apply_mute(pactl, &sources, false)?;
                for source in sources {
                    self.per_source_desired.insert(source, false);
                }
            }
            Action::Press => self.apply_mute(pactl, &sources, false)?,
            Action::Release => self.apply_mute(pactl, &sources, true)?,
            Action::Resync => self.reapply_desired_state(pactl)?,
            Action::Toggle => {
                let new_mute = sources.iter().any(|source| !self.effective_desired(source));
                self.apply_mute(pactl, &sources, new_mute)?;
                for source in sources {
                    self.per_source_desired.insert(source, new_mute);
                }
            }
            Action::Reload => self.reload_config(pactl)?,
        }
        Ok(())
    }

    pub fn reapply_desired_state(&mut self, pactl: &dyn PactlRunner) -> Result<()> {
        let sources = self.sources.clone();
        let mut muted = 0;
        let mut unmuted = 0;
        for source in sources {
            let desired = self.effective_desired(&source);
            if let Err(err) = self.apply_mute(pactl, &[source], desired) {
                warn!("Failed to reapply mute state: {:#}", err);
                continue;
            }
            if desired {
                muted += 1;
            } else {
                unmuted += 1;
            }
        }
        if muted != 0 || unmuted != 0 {
            info!(
                "Reapplied desired state: {} muted, {} unmuted",
                muted, unmuted
            );
        }
        Ok(())
    }

    pub fn revert_external_change(&mut self, pactl: &dyn PactlRunner) {
        let sources = self.sources.clone();
        for source in sources {
            let Some(actual) = pactl::get_mute_state(pactl, &source).muted_bool() else {
                continue;
            };
            let Some(last) = self.last_applied_mute.get(&source).copied() else {
                continue;
            };
            if last == actual {
                continue;
            }
            if let Err(err) = self.apply_mute(pactl, std::slice::from_ref(&source), last) {
                warn!("Failed to revert external change on {}: {:#}", source, err);
                self.last_applied_mute.insert(source, actual);
                continue;
            }
            info!(
                "Reverted external change on {}: back to {}",
                source,
                if last { "muted" } else { "unmuted" }
            );
        }
    }
}

pub fn run(
    pactl: &dyn PactlRunner,
    config: config::Config,
    overrides: Overrides,
    sigs: signals::Handles,
) -> Result<()> {
    let mut state = State::new(&config, &overrides, pactl)?;
    if let Some(source) = &config.source {
        info!("Source: {}", source);
    } else {
        info!("Operating on all sources: {}", state.sources.join(", "));
    }
    if config.start_muted && !state.sources.is_empty() {
        let sources = state.sources.clone();
        state.apply_mute(pactl, &sources, true)?;
        info!("Initial state: muted (--start-muted)");
    } else if !config.start_muted {
        info!("Initial state: untouched (--no-start-muted)");
    }

    let socket_path = socket::socket_path();
    socket::cleanup_socket(&socket_path);
    let server = UnixDatagram::bind(&socket_path)?;
    server.set_read_timeout(Some(Duration::from_millis(250)))?;
    let state = Arc::new(Mutex::new(state));
    start_source_watcher(Arc::clone(&state));
    info!("pttman daemon listening on {}", socket_path.display());

    let mut buf = [0_u8; 64];
    while !sigs.stop_requested() {
        if sigs.take_reload() {
            let mut state = state.lock().expect("state mutex poisoned");
            if let Err(err) = state.reload_config(pactl) {
                warn!(
                    "Failed to reload config, keeping current settings: {:#}",
                    err
                );
            }
        }
        match server.recv(&mut buf) {
            Ok(size) => {
                let Ok(action) = Action::parse(&buf[..size]) else {
                    continue;
                };
                let action = coalesce_commands(&server, action, pactl, &state);
                let mut state = state.lock().expect("state mutex poisoned");
                if let Err(err) = state.run_action(pactl, action) {
                    warn!("{:#}", err);
                }
            }
            Err(err)
                if err.kind() == std::io::ErrorKind::Interrupted
                    || err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut => {}
            Err(err) => warn!("socket receive failed: {}", err),
        }
    }
    socket::cleanup_socket(&socket_path);
    Ok(())
}

pub fn run_direct_action(
    pactl: &dyn PactlRunner,
    action: Action,
    sources: &[String],
) -> Result<()> {
    match action {
        Action::Mute | Action::Release => pactl::set_mute(pactl, sources, true),
        Action::Press | Action::Unmute => pactl::set_mute(pactl, sources, false),
        Action::Toggle => pactl::toggle_mute(pactl, sources),
        _ => bail!("unsupported direct action: {}", action),
    }
}

fn coalesce_commands(
    server: &UnixDatagram,
    initial: Action,
    pactl: &dyn PactlRunner,
    state: &Arc<Mutex<State>>,
) -> Action {
    let mut effective = initial;
    let _ = server.set_nonblocking(true);
    let mut buf = [0_u8; 64];
    loop {
        match server.recv(&mut buf) {
            Ok(size) => match Action::parse(&buf[..size]) {
                Ok(Action::Reload) => {
                    let mut state = state.lock().expect("state mutex poisoned");
                    if let Err(err) = state.reload_config(pactl) {
                        warn!(
                            "Failed to reload config, keeping current settings: {:#}",
                            err
                        );
                    }
                }
                Ok(action) => effective = action,
                Err(err) => warn!("{:#}", err),
            },
            Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => break,
            Err(err) => {
                warn!("socket coalesce failed: {}", err);
                break;
            }
        }
    }
    let _ = server.set_nonblocking(false);
    effective
}

fn start_source_watcher(state: Arc<Mutex<State>>) {
    thread::Builder::new()
        .name("pttman-source-watcher".into())
        .spawn(move || {
            let pactl = pactl::RealPactl;
            let mut first_connect = true;
            let mut backoff = Duration::from_millis(50);
            loop {
                let started = Instant::now();
                let output = std::process::Command::new("pactl")
                    .arg("subscribe")
                    .stdout(std::process::Stdio::piped())
                    .stderr(std::process::Stdio::null())
                    .spawn();
                match output {
                    Ok(mut child) => {
                        if let Some(stdout) = child.stdout.take() {
                            if !first_connect {
                                refresh_and_reapply(&state, &pactl);
                            }
                            first_connect = false;
                            let reader = std::io::BufReader::new(stdout);
                            use std::io::BufRead;
                            for line in reader.lines().map_while(Result::ok) {
                                if line.contains("'new' on source")
                                    || line.contains("'remove' on source")
                                {
                                    refresh_and_reapply(&state, &pactl);
                                } else if line.contains("'change' on source") {
                                    state
                                        .lock()
                                        .expect("state mutex poisoned")
                                        .revert_external_change(&pactl);
                                }
                            }
                        }
                        let _ = child.wait();
                    }
                    Err(err) => warn!("source watcher: {}", err),
                }
                if started.elapsed() >= Duration::from_secs(1) {
                    backoff = Duration::from_millis(50);
                }
                thread::sleep(backoff);
                backoff = (backoff * 2).min(Duration::from_millis(400));
            }
        })
        .expect("spawning source watcher");
}

fn refresh_and_reapply(state: &Arc<Mutex<State>>, pactl: &dyn PactlRunner) {
    let mut state = state.lock().expect("state mutex poisoned");
    if let Err(err) = state.refresh_sources(pactl) {
        warn!("source refresh failed: {:#}", err);
    }
    if let Err(err) = state.reapply_desired_state(pactl) {
        warn!("state reapply failed: {:#}", err);
    }
}
