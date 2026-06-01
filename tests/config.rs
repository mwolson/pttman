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
