mod common;

use clap::Parser;
use pttman::cli::{self, Cli, Command};
use pttman::config::{parse_conf, Config};
use std::time::Duration;
use tempfile::NamedTempFile;

#[test]
fn parse_conf_ignores_comments_and_blank_lines() {
    let path = std::path::Path::new("pttman.conf");
    let entries = parse_conf("# comment\n\n--source=my-source\n", path).unwrap();
    assert_eq!(entries, vec![("--source".into(), "my-source".into())]);
}

#[test]
fn parse_conf_rejects_malformed_lines() {
    let path = std::path::Path::new("pttman.conf");
    assert!(parse_conf("not a flag\n", path).is_err());
}

#[test]
fn config_reads_source() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--source=my-source\n").unwrap();
    let config = Config::build(&cli::Overrides::default(), Some(file.path())).unwrap();
    assert_eq!(config.source.as_deref(), Some("my-source"));
}

#[test]
fn config_reads_ptt_hold_timeout() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--ptt-hold-timeout=2m\n").unwrap();
    let config = Config::build(&cli::Overrides::default(), Some(file.path())).unwrap();
    assert_eq!(config.ptt_hold_timeout, Some(Duration::from_secs(120)));
}

#[test]
fn config_rejects_invalid_ptt_hold_timeout() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--ptt-hold-timeout=sometimes\n").unwrap();
    assert!(Config::build(&cli::Overrides::default(), Some(file.path())).is_err());
}

#[test]
fn config_rejects_all_sources_with_source() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--all-sources=true\n--source=my-source\n").unwrap();
    assert!(Config::build(&cli::Overrides::default(), Some(file.path())).is_err());
}

#[test]
fn config_rejects_invalid_bool() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--start-muted=sometimes\n").unwrap();
    assert!(Config::build(&cli::Overrides::default(), Some(file.path())).is_err());
}

#[test]
fn write_default_source_drops_conflicting_all_sources() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("pttman.conf");
    std::fs::write(&path, "--all-sources=true\n--ptt-hold-timeout=2m\n").unwrap();
    let dropped = pttman::config::write_default_source(&path, "my-source").unwrap();
    assert!(dropped);
    let text = std::fs::read_to_string(&path).unwrap();
    assert!(!text.contains("--all-sources"));
    assert!(text.contains("--source=my-source"));
    let config = Config::build(&cli::Overrides::default(), Some(&path)).unwrap();
    assert_eq!(config.source.as_deref(), Some("my-source"));
    assert_eq!(config.ptt_hold_timeout, Some(Duration::from_secs(120)));
}

#[test]
fn write_default_source_replaces_existing_and_creates_missing() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("pttman.conf");
    assert!(!pttman::config::write_default_source(&path, "first").unwrap());
    assert_eq!(std::fs::read_to_string(&path).unwrap(), "--source=first\n");
    assert!(!pttman::config::write_default_source(&path, "second").unwrap());
    assert_eq!(std::fs::read_to_string(&path).unwrap(), "--source=second\n");
}

#[test]
fn write_default_source_preserves_symlink_and_permissions() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let real = dir.path().join("dotfiles-pttman.conf");
    let link = dir.path().join("pttman.conf");
    std::fs::write(&real, "--ptt-hold-timeout=2m\n").unwrap();
    std::fs::set_permissions(&real, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::os::unix::fs::symlink(&real, &link).unwrap();
    pttman::config::write_default_source(&link, "my-source").unwrap();
    assert!(std::fs::symlink_metadata(&link).unwrap().is_symlink());
    let meta = std::fs::metadata(&real).unwrap();
    assert_eq!(meta.permissions().mode() & 0o777, 0o600);
    let text = std::fs::read_to_string(&real).unwrap();
    assert!(text.contains("--source=my-source"));
    assert!(text.contains("--ptt-hold-timeout=2m"));
}

#[test]
fn cli_source_overrides_config() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--source=conf-source\n").unwrap();
    let cli = Cli::try_parse_from(["pttman", "--source", "cli-source", "mute"]).unwrap();
    let config = Config::build(&cli::overrides(&cli).unwrap(), Some(file.path())).unwrap();
    assert_eq!(config.source.as_deref(), Some("cli-source"));
}

#[test]
fn cli_all_sources_overrides_config_source() {
    let mut file = NamedTempFile::new().unwrap();
    std::io::Write::write_all(&mut file, b"--source=conf-source\n").unwrap();
    let cli = Cli::try_parse_from(["pttman", "--all-sources", "mute"]).unwrap();
    let config = Config::build(&cli::overrides(&cli).unwrap(), Some(file.path())).unwrap();
    assert!(config.source.is_none());
}

#[test]
fn cli_no_subcommand_runs_daemon() {
    let cli = Cli::try_parse_from(["pttman"]).unwrap();
    assert!(cli.command.is_none());
}

#[test]
fn cli_parses_kebab_commands() {
    let cli = Cli::try_parse_from(["pttman", "get-default-source"]).unwrap();
    assert!(matches!(cli.command, Some(Command::GetDefaultSource)));
}

#[test]
fn no_start_muted_overrides_default() {
    let cli = Cli::try_parse_from(["pttman", "--no-start-muted"]).unwrap();
    let config = Config::build(&cli::overrides(&cli).unwrap(), None).unwrap();
    assert!(!config.start_muted);
}
