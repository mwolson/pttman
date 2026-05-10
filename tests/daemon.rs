mod common;

use std::collections::HashMap;

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
