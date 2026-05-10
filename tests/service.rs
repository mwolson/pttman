use pttman::service;
use pttman::service_files;

#[test]
fn parses_openrc_version() {
    assert_eq!(
        service::parse_openrc_version("OpenRC 0.60.1 abc"),
        Some((0, 60))
    );
    assert_eq!(service::parse_openrc_version("OpenRC 0.59"), Some((0, 59)));
    assert_eq!(service::parse_openrc_version("no version"), None);
}

#[test]
fn bundled_service_files_have_expected_names() {
    assert!(service_files::SYSTEMD_UNIT.contains("ExecStart=%h/.local/bin/pttman"));
    assert!(service_files::OPENRC_USER.contains("command=\"$HOME/.local/bin/pttman\""));
    assert!(service_files::OPENRC_SYSTEM.contains("command=\"/usr/local/bin/pttman\""));
}
