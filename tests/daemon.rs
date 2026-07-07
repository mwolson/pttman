mod common;

use std::collections::HashMap;
use std::time::{Duration, Instant};

use common::FakePactl;
use pttman::daemon::{Action, State};

fn state() -> State {
    State {
        auto_discover: true,
        cli_all_sources: false,
        cli_source: None,
        default_mute: true,
        last_applied_mute: HashMap::new(),
        per_source_desired: HashMap::new(),
        ptt_active: false,
        ptt_hold_expires_at: None,
        ptt_hold_timeout: None,
        revert_backoff: HashMap::new(),
        sources: vec!["src1".into()],
    }
}

#[test]
fn action_parse_accepts_known_commands() {
    assert_eq!(Action::parse(b"mute").unwrap(), Action::Mute);
    assert_eq!(Action::parse(b"press").unwrap(), Action::Press);
    assert_eq!(Action::parse(b"release").unwrap(), Action::Release);
    assert_eq!(Action::parse(b"reload").unwrap(), Action::Reload);
    assert_eq!(Action::parse(b"resync").unwrap(), Action::Resync);
    assert_eq!(Action::parse(b"toggle").unwrap(), Action::Toggle);
    assert_eq!(Action::parse(b"unmute").unwrap(), Action::Unmute);
    assert!(Action::parse(b"bogus").is_err());
}

#[test]
fn mute_records_preference() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.run_action(&pactl, Action::Mute).unwrap();
    assert_eq!(state.per_source_desired.get("src1"), Some(&true));
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
}

#[test]
fn press_does_not_record_preference() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "0"], "");
    let mut state = state();
    state.per_source_desired.insert("src1".into(), true);
    state.run_action(&pactl, Action::Press).unwrap();
    assert_eq!(state.per_source_desired.get("src1"), Some(&true));
    assert_eq!(state.last_applied_mute.get("src1"), Some(&false));
}

#[test]
fn press_arms_ptt_hold_timeout() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "0"], "");
    let mut state = state();
    state.ptt_hold_timeout = Some(Duration::from_secs(120));
    state.run_action(&pactl, Action::Press).unwrap();
    assert!(state.ptt_hold_expires_at.is_some());
}

#[test]
fn release_clears_ptt_hold_timeout() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.ptt_hold_expires_at = Some(Instant::now() + Duration::from_secs(120));
    state.run_action(&pactl, Action::Release).unwrap();
    assert!(state.ptt_hold_expires_at.is_none());
}

#[test]
fn ptt_hold_timeout_mutes_and_clears_expired_press() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.ptt_hold_timeout = Some(Duration::from_secs(120));
    state.ptt_hold_expires_at = Some(Instant::now() - Duration::from_secs(1));
    state.enforce_ptt_hold_timeout(&pactl).unwrap();
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
    assert!(state.ptt_hold_expires_at.is_none());
}

#[test]
fn reapply_desired_state_respects_active_ptt_hold() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "0"], "");
    let mut state = state();
    state.run_action(&pactl, Action::Press).unwrap();
    state.reapply_desired_state(&pactl).unwrap();
    assert_eq!(state.last_applied_mute.get("src1"), Some(&false));
}

#[test]
fn reapply_desired_state_unmutes_new_sources_during_ptt_hold() {
    let pactl = FakePactl::default()
        .with_output(&["set-source-mute", "src1", "0"], "")
        .with_output(&["set-source-mute", "src2", "0"], "");
    let mut state = state();
    state.run_action(&pactl, Action::Press).unwrap();
    state.sources = vec!["src1".into(), "src2".into()];
    state.reapply_desired_state(&pactl).unwrap();
    assert_eq!(state.last_applied_mute.get("src2"), Some(&false));
}

#[test]
fn release_restores_desired_state_on_reapply() {
    let pactl = FakePactl::default()
        .with_output(&["set-source-mute", "src1", "0"], "")
        .with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.run_action(&pactl, Action::Press).unwrap();
    state.run_action(&pactl, Action::Release).unwrap();
    state.reapply_desired_state(&pactl).unwrap();
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
}

#[test]
fn ptt_hold_timeout_expiry_clears_active_hold() {
    let pactl = FakePactl::default()
        .with_output(&["set-source-mute", "src1", "0"], "")
        .with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.ptt_hold_timeout = Some(Duration::from_secs(120));
    state.run_action(&pactl, Action::Press).unwrap();
    state.ptt_hold_expires_at = Some(Instant::now() - Duration::from_secs(1));
    state.enforce_ptt_hold_timeout(&pactl).unwrap();
    assert!(!state.ptt_active);
    state.reapply_desired_state(&pactl).unwrap();
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
}

#[test]
fn toggle_clears_active_ptt_hold() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "0"], "");
    let mut state = state();
    state.run_action(&pactl, Action::Press).unwrap();
    state.run_action(&pactl, Action::Toggle).unwrap();
    assert!(!state.ptt_active);
    assert_eq!(state.per_source_desired.get("src1"), Some(&false));
}

#[test]
fn apply_mute_records_only_successful_sources() {
    let pactl = FakePactl::default().with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.sources = vec!["src1".into(), "src2".into()];
    let sources = state.sources.clone();
    assert!(state.apply_mute(&pactl, &sources, true).is_err());
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
    assert_eq!(state.last_applied_mute.get("src2"), None);
}

#[test]
fn revert_external_change_backs_off_after_repeated_fights() {
    let pactl = FakePactl::default()
        .with_output(&["get-source-mute", "src1"], "Mute: no\n")
        .with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.last_applied_mute.insert("src1".into(), true);
    for _ in 0..4 {
        state.revert_external_change(&pactl);
    }
    assert_eq!(state.last_applied_mute.get("src1"), Some(&false));
    let reverts = pactl
        .calls()
        .iter()
        .filter(|call| call[0] == "set-source-mute")
        .count();
    assert_eq!(reverts, 3);

    state.run_action(&pactl, Action::Mute).unwrap();
    assert!(state.revert_backoff.is_empty());
    state.revert_external_change(&pactl);
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
}

#[test]
fn recover_missed_source_events_adopts_drifted_list_and_reapplies() {
    let pactl = FakePactl::default()
        .with_output(
            &["list", "sources", "short"],
            "1\tsrc1\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n\
             2\tsrc2\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n",
        )
        .with_output(&["set-source-mute", "src1", "1"], "")
        .with_output(&["set-source-mute", "src2", "1"], "");
    let mut state = state();
    state.recover_missed_source_events(&pactl);
    assert_eq!(state.sources, vec!["src1".to_string(), "src2".to_string()]);
    assert_eq!(state.last_applied_mute.get("src2"), Some(&true));
}

#[test]
fn recover_missed_source_events_skips_reapply_when_list_unchanged() {
    let pactl = FakePactl::default().with_output(
        &["list", "sources", "short"],
        "1\tsrc1\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n",
    );
    let mut state = state();
    state.recover_missed_source_events(&pactl);
    assert_eq!(state.sources, vec!["src1".to_string()]);
    assert!(pactl
        .calls()
        .iter()
        .all(|call| call[0] != "set-source-mute"));
}

#[test]
fn recover_missed_source_events_drops_removed_sources() {
    let pactl = FakePactl::default()
        .with_output(
            &["list", "sources", "short"],
            "2\tsrc2\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n",
        )
        .with_output(&["set-source-mute", "src2", "1"], "");
    let mut state = state();
    state.recover_missed_source_events(&pactl);
    assert_eq!(state.sources, vec!["src2".to_string()]);
    assert_eq!(state.last_applied_mute.get("src2"), Some(&true));
}

#[test]
fn recover_missed_source_events_keeps_sources_on_refresh_failure() {
    let pactl = FakePactl::default();
    let mut state = state();
    state.recover_missed_source_events(&pactl);
    assert_eq!(state.sources, vec!["src1".to_string()]);
    assert!(pactl
        .calls()
        .iter()
        .all(|call| call[0] != "set-source-mute"));
}

#[test]
fn recover_missed_source_events_noops_with_fixed_source() {
    let pactl = FakePactl::default();
    let mut state = state();
    state.auto_discover = false;
    state.recover_missed_source_events(&pactl);
    assert_eq!(state.sources, vec!["src1".to_string()]);
    assert!(pactl.calls().is_empty());
}

#[test]
fn state_new_starts_empty_when_pactl_unavailable() {
    let pactl = FakePactl::default();
    let config = pttman::config::Config::default();
    let state = State::new(&config, &pttman::cli::Overrides::default(), &pactl);
    assert!(state.sources.is_empty());
    assert!(state.auto_discover);
}

#[test]
fn toggle_mutes_when_any_source_effectively_unmuted() {
    let pactl = FakePactl::default()
        .with_output(&["set-source-mute", "src1", "1"], "")
        .with_output(&["set-source-mute", "src2", "1"], "");
    let mut state = state();
    state.sources = vec!["src1".into(), "src2".into()];
    state.per_source_desired.insert("src1".into(), true);
    state.per_source_desired.insert("src2".into(), false);
    state.run_action(&pactl, Action::Toggle).unwrap();
    assert_eq!(state.per_source_desired.get("src1"), Some(&true));
    assert_eq!(state.per_source_desired.get("src2"), Some(&true));
}

#[test]
fn reapply_desired_state_mixes_overrides_with_default() {
    let pactl = FakePactl::default()
        .with_output(&["set-source-mute", "src1", "0"], "")
        .with_output(&["set-source-mute", "src2", "1"], "");
    let mut state = state();
    state.sources = vec!["src1".into(), "src2".into()];
    state.per_source_desired.insert("src1".into(), false);
    state.reapply_desired_state(&pactl).unwrap();
    assert_eq!(state.last_applied_mute.get("src1"), Some(&false));
    assert_eq!(state.last_applied_mute.get("src2"), Some(&true));
}

#[test]
fn revert_external_change_restores_last_applied_without_preference_change() {
    let pactl = FakePactl::default()
        .with_output(&["get-source-mute", "src1"], "Mute: no\n")
        .with_output(&["set-source-mute", "src1", "1"], "");
    let mut state = state();
    state.last_applied_mute.insert("src1".into(), true);
    state.per_source_desired.insert("src1".into(), true);
    state.revert_external_change(&pactl);
    assert_eq!(state.last_applied_mute.get("src1"), Some(&true));
    assert_eq!(state.per_source_desired.get("src1"), Some(&true));
}
