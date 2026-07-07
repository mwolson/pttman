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

const MAX_REVERTS_PER_WINDOW: u32 = 3;
const REVERT_BACKOFF_WINDOW: Duration = Duration::from_secs(2);
// Safety net for source events lost while `pactl subscribe` reattaches (e.g.
// sources re-registering during a PipeWire restart): poll the live list so a
// missed 'new'/'remove' cannot strand the daemon on a stale source set.
const SOURCE_REFRESH_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Debug, Clone)]
pub struct State {
    pub auto_discover: bool,
    pub cli_all_sources: bool,
    pub cli_source: Option<String>,
    pub default_mute: bool,
    pub last_applied_mute: HashMap<String, bool>,
    pub per_source_desired: HashMap<String, bool>,
    pub ptt_active: bool,
    pub ptt_hold_expires_at: Option<Instant>,
    pub ptt_hold_timeout: Option<Duration>,
    pub revert_backoff: HashMap<String, (Instant, u32)>,
    pub sources: Vec<String>,
}

impl State {
    pub fn new(config: &config::Config, overrides: &Overrides, pactl: &dyn PactlRunner) -> Self {
        let sources = config.resolve_sources(pactl).unwrap_or_else(|err| {
            warn!(
                "Failed to list sources at startup, waiting for source events: {:#}",
                err
            );
            Vec::new()
        });
        Self {
            auto_discover: config.source.is_none(),
            cli_all_sources: overrides.all_sources,
            cli_source: overrides.source.clone(),
            default_mute: config.start_muted,
            last_applied_mute: HashMap::new(),
            per_source_desired: HashMap::new(),
            ptt_active: false,
            ptt_hold_expires_at: None,
            ptt_hold_timeout: config.ptt_hold_timeout,
            revert_backoff: HashMap::new(),
            sources,
        }
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
        self.set_ptt_hold_timeout(config.ptt_hold_timeout);
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
        let mut first_err = None;
        for source in sources {
            match pactl::set_mute(pactl, std::slice::from_ref(source), mute) {
                Ok(()) => {
                    self.last_applied_mute.insert(source.clone(), mute);
                }
                Err(err) => {
                    warn!("Failed to set mute on {}: {:#}", source, err);
                    if first_err.is_none() {
                        first_err = Some(err);
                    }
                }
            }
        }
        match first_err {
            Some(err) => Err(err),
            None => Ok(()),
        }
    }

    pub fn run_action(&mut self, pactl: &dyn PactlRunner, action: Action) -> Result<()> {
        // Any command ends the revert backoff ("accepting ... until the next
        // command"), giving the next external fight a fresh revert budget.
        self.revert_backoff.clear();
        let sources = self.sources.clone();
        match action {
            Action::Mute => {
                self.ptt_active = false;
                self.clear_ptt_hold_timeout();
                for source in &sources {
                    self.per_source_desired.insert(source.clone(), true);
                }
                self.apply_mute(pactl, &sources, true)?;
            }
            Action::Unmute => {
                self.ptt_active = false;
                self.clear_ptt_hold_timeout();
                for source in &sources {
                    self.per_source_desired.insert(source.clone(), false);
                }
                self.apply_mute(pactl, &sources, false)?;
            }
            Action::Press => {
                self.ptt_active = true;
                self.arm_ptt_hold_timeout();
                self.apply_mute(pactl, &sources, false)?;
            }
            Action::Release => {
                self.ptt_active = false;
                self.clear_ptt_hold_timeout();
                self.apply_mute(pactl, &sources, true)?;
            }
            Action::Resync => self.reapply_desired_state(pactl)?,
            Action::Toggle => {
                let new_mute = sources.iter().any(|source| !self.effective_desired(source));
                self.ptt_active = false;
                self.clear_ptt_hold_timeout();
                for source in &sources {
                    self.per_source_desired.insert(source.clone(), new_mute);
                }
                self.apply_mute(pactl, &sources, new_mute)?;
            }
            Action::Reload => self.reload_config(pactl)?,
        }
        Ok(())
    }

    pub fn enforce_ptt_hold_timeout(&mut self, pactl: &dyn PactlRunner) -> Result<()> {
        let Some(expires_at) = self.ptt_hold_expires_at else {
            return Ok(());
        };
        if Instant::now() < expires_at {
            return Ok(());
        }
        let sources = self.sources.clone();
        if !sources.is_empty() {
            if let Some(timeout) = self.ptt_hold_timeout {
                info!(
                    "PTT hold timeout expired after {}; muting managed sources",
                    format_duration(timeout)
                );
            } else {
                info!("PTT hold timeout expired; muting managed sources");
            }
        }
        self.ptt_active = false;
        self.ptt_hold_expires_at = None;
        self.apply_mute(pactl, &sources, true)?;
        Ok(())
    }

    pub fn reapply_desired_state(&mut self, pactl: &dyn PactlRunner) -> Result<()> {
        let sources = self.sources.clone();
        let mut muted = 0;
        let mut unmuted = 0;
        for source in sources {
            // An active PTT hold overrides the recorded preference so source
            // churn (e.g. Bluetooth profile flaps) cannot mute mid-hold.
            let desired = if self.ptt_active {
                false
            } else {
                self.effective_desired(&source)
            };
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
            if self.revert_backoff_exceeded(&source) {
                warn!(
                    "External tool keeps changing mute on {}; accepting {} until the next command",
                    source,
                    if actual { "muted" } else { "unmuted" }
                );
                self.last_applied_mute.insert(source, actual);
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

    pub fn recover_missed_source_events(&mut self, pactl: &dyn PactlRunner) {
        let before = self.sources.clone();
        if let Err(err) = self.refresh_sources(pactl) {
            warn!("periodic source refresh failed: {:#}", err);
            return;
        }
        // Only reapply when the list actually drifted; an unconditional
        // reapply every tick would re-fight external tools and bypass the
        // revert backoff.
        if self.sources != before {
            if let Err(err) = self.reapply_desired_state(pactl) {
                warn!("state reapply failed: {:#}", err);
            }
        }
    }

    fn revert_backoff_exceeded(&mut self, source: &str) -> bool {
        let now = Instant::now();
        let entry = self
            .revert_backoff
            .entry(source.to_string())
            .or_insert((now, 0));
        if now.duration_since(entry.0) > REVERT_BACKOFF_WINDOW {
            *entry = (now, 0);
        }
        entry.1 += 1;
        entry.1 > MAX_REVERTS_PER_WINDOW
    }

    fn arm_ptt_hold_timeout(&mut self) {
        self.ptt_hold_expires_at = self
            .ptt_hold_timeout
            .and_then(|timeout| Instant::now().checked_add(timeout));
        if self.ptt_hold_timeout.is_some() && self.ptt_hold_expires_at.is_none() {
            warn!("PTT hold timeout is too large to schedule");
        }
    }

    fn clear_ptt_hold_timeout(&mut self) {
        self.ptt_hold_expires_at = None;
    }

    fn set_ptt_hold_timeout(&mut self, timeout: Option<Duration>) {
        self.ptt_hold_timeout = timeout;
        if self.ptt_hold_timeout.is_none() {
            self.clear_ptt_hold_timeout();
        }
        info!(
            "PTT hold timeout: {}",
            self.ptt_hold_timeout
                .map(format_duration)
                .unwrap_or_else(|| "off".into())
        );
    }
}

pub fn run(
    pactl: &dyn PactlRunner,
    config: config::Config,
    overrides: Overrides,
    sigs: signals::Handles,
) -> Result<()> {
    let socket_path = socket::socket_path();
    if socket::daemon_is_alive(&socket_path) {
        bail!(
            "another pttman daemon is already listening on {}",
            socket_path.display()
        );
    }
    let mut state = State::new(&config, &overrides, pactl);
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
    info!(
        "PTT hold timeout: {}",
        config
            .ptt_hold_timeout
            .map(format_duration)
            .unwrap_or_else(|| "off".into())
    );

    socket::cleanup_socket(&socket_path);
    let server = UnixDatagram::bind(&socket_path)?;
    server.set_read_timeout(Some(Duration::from_millis(250)))?;
    let state = Arc::new(Mutex::new(state));
    start_source_watcher(Arc::clone(&state));
    info!("pttman daemon listening on {}", socket_path.display());

    let mut buf = [0_u8; 64];
    let mut next_source_check = Instant::now() + SOURCE_REFRESH_INTERVAL;
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
                let action = match Action::parse(&buf[..size]) {
                    Ok(action) => action,
                    Err(err) => {
                        warn!("{:#}", err);
                        continue;
                    }
                };
                info!("Received action: {}", action);
                let actions = coalesce_commands(&server, action, pactl, &state);
                let mut state = state.lock().expect("state mutex poisoned");
                for action in actions {
                    if let Err(err) = state.run_action(pactl, action) {
                        warn!("{:#}", err);
                    }
                }
            }
            Err(err)
                if err.kind() == std::io::ErrorKind::Interrupted
                    || err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut => {}
            Err(err) => warn!("socket receive failed: {}", err),
        }
        let mut state = state.lock().expect("state mutex poisoned");
        if let Err(err) = state.enforce_ptt_hold_timeout(pactl) {
            warn!("PTT hold timeout failed: {:#}", err);
        }
        if Instant::now() >= next_source_check {
            next_source_check = Instant::now() + SOURCE_REFRESH_INTERVAL;
            state.recover_missed_source_events(pactl);
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
) -> Vec<Action> {
    let mut pending = vec![initial];
    let _ = server.set_nonblocking(true);
    let mut buf = [0_u8; 64];
    loop {
        match server.recv(&mut buf) {
            Ok(size) => match Action::parse(&buf[..size]) {
                Ok(Action::Reload) => {
                    info!("Received action: reload");
                    let mut state = state.lock().expect("state mutex poisoned");
                    if let Err(err) = state.reload_config(pactl) {
                        warn!(
                            "Failed to reload config, keeping current settings: {:#}",
                            err
                        );
                    }
                }
                Ok(action) => {
                    info!("Received action: {}", action);
                    pending.push(action);
                }
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
    collapse_ptt_runs(pending)
}

// Only consecutive press/release edges are interchangeable: they do not touch
// the recorded preference, so the last edge fully determines the outcome.
// Other actions must run in order.
fn collapse_ptt_runs(actions: Vec<Action>) -> Vec<Action> {
    let mut collapsed: Vec<Action> = Vec::with_capacity(actions.len());
    for action in actions {
        let is_ptt_edge = matches!(action, Action::Press | Action::Release);
        if is_ptt_edge && matches!(collapsed.last(), Some(Action::Press | Action::Release)) {
            *collapsed.last_mut().expect("checked non-empty") = action;
        } else {
            collapsed.push(action);
        }
    }
    collapsed
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
                    .env("LC_ALL", "C")
                    .stdout(std::process::Stdio::piped())
                    .stderr(std::process::Stdio::null())
                    .spawn();
                match output {
                    Ok(mut child) => {
                        if let Some(stdout) = child.stdout.take() {
                            // Refresh even on first connect if startup listing
                            // failed and left us with no sources to manage.
                            let no_sources = state
                                .lock()
                                .expect("state mutex poisoned")
                                .sources
                                .is_empty();
                            if !first_connect || no_sources {
                                refresh_and_reapply(&state, &pactl);
                            }
                            first_connect = false;
                            let reader = std::io::BufReader::new(stdout);
                            use std::io::BufRead;
                            for line in reader.lines().map_while(Result::ok) {
                                if is_source_event(&line, "new") || is_source_event(&line, "remove")
                                {
                                    refresh_and_reapply(&state, &pactl);
                                } else if is_source_event(&line, "change") {
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

fn is_source_event(line: &str, event: &str) -> bool {
    let prefix = match event {
        "change" => "Event 'change' on source",
        "new" => "Event 'new' on source",
        "remove" => "Event 'remove' on source",
        _ => return false,
    };
    line == prefix
        || line
            .strip_prefix(prefix)
            .is_some_and(|suffix| suffix.starts_with(" #"))
}

fn format_duration(duration: Duration) -> String {
    let millis = duration.as_millis();
    if millis % 3_600_000 == 0 {
        format!("{}h", millis / 3_600_000)
    } else if millis % 60_000 == 0 {
        format!("{}m", millis / 60_000)
    } else if millis % 1_000 == 0 {
        format!("{}s", millis / 1_000)
    } else {
        format!("{}ms", millis)
    }
}

#[cfg(test)]
mod tests {
    use super::{collapse_ptt_runs, is_source_event, Action};

    #[test]
    fn collapse_ptt_runs_keeps_last_edge_and_preserves_other_actions() {
        use Action::{Mute, Press, Release, Toggle};
        assert_eq!(collapse_ptt_runs(vec![Press]), vec![Press]);
        assert_eq!(collapse_ptt_runs(vec![Press, Release, Press]), vec![Press]);
        assert_eq!(
            collapse_ptt_runs(vec![Press, Release, Press, Release]),
            vec![Release]
        );
        assert_eq!(collapse_ptt_runs(vec![Mute, Toggle]), vec![Mute, Toggle]);
        assert_eq!(
            collapse_ptt_runs(vec![Press, Mute, Release]),
            vec![Press, Mute, Release]
        );
        assert_eq!(
            collapse_ptt_runs(vec![Release, Press, Toggle]),
            vec![Press, Toggle]
        );
    }

    #[test]
    fn source_event_matching_excludes_source_outputs() {
        assert!(is_source_event("Event 'new' on source #8731", "new"));
        assert!(is_source_event("Event 'remove' on source #8731", "remove"));
        assert!(is_source_event("Event 'change' on source #8731", "change"));

        assert!(!is_source_event("Event 'new' on source-output #80", "new"));
        assert!(!is_source_event(
            "Event 'remove' on source-output #80",
            "remove"
        ));
        assert!(!is_source_event(
            "Event 'change' on source-output #80",
            "change"
        ));
    }
}
