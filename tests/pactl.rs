mod common;

use common::FakePactl;
use pttman::pactl::{self, MuteState};

const SOURCES_SHORT: &str = "\
64\talsa_input.usb-046d_BRIO-03.pro-input-0\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED
65\talsa_input.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED
86\talsa_output.pci-0000_01_00.1.pro-output-3.monitor\tPipeWire\ts32le 8ch 48000Hz\tIDLE
";

#[test]
fn parse_source_names_filters_monitors() {
    assert_eq!(
        pactl::parse_source_names(SOURCES_SHORT),
        vec![
            "alsa_input.usb-046d_BRIO-03.pro-input-0",
            "alsa_input.pci-0000_00_1f.3.analog-stereo"
        ]
    );
}

#[test]
fn get_all_source_names_calls_pactl() {
    let pactl = FakePactl::default().with_output(&["list", "sources", "short"], SOURCES_SHORT);
    assert_eq!(pactl::get_all_source_names(&pactl).unwrap().len(), 2);
}

#[test]
fn parse_source_descriptions_pairs_name_and_description() {
    let dump = "\
Source #1
    Name: src1
    Description: USB Mic
Source #2
    Name: src2
    Description: Built-in Mic
";
    assert_eq!(
        pactl::parse_source_descriptions(dump),
        vec![
            ("src1".into(), "USB Mic".into()),
            ("src2".into(), "Built-in Mic".into())
        ]
    );
}

#[test]
fn mute_state_parses_yes_no_unknown() {
    let muted = FakePactl::default().with_output(&["get-source-mute", "src1"], "Mute: yes\n");
    assert_eq!(pactl::get_mute_state(&muted, "src1"), MuteState::Muted);

    let unmuted = FakePactl::default().with_output(&["get-source-mute", "src1"], "Mute: no\n");
    assert_eq!(pactl::get_mute_state(&unmuted, "src1"), MuteState::Unmuted);

    let unknown = FakePactl::default();
    assert_eq!(pactl::get_mute_state(&unknown, "src1"), MuteState::Unknown);
}

#[test]
fn set_mute_calls_pactl_for_each_source() {
    let pactl = FakePactl::default()
        .with_output(&["set-source-mute", "src1", "1"], "")
        .with_output(&["set-source-mute", "src2", "1"], "");
    pactl::set_mute(&pactl, &["src1".into(), "src2".into()], true).unwrap();
    assert_eq!(
        pactl.calls(),
        vec![
            vec!["set-source-mute", "src1", "1"],
            vec!["set-source-mute", "src2", "1"]
        ]
    );
}
