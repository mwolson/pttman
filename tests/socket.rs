use std::os::unix::net::UnixDatagram;

use pttman::socket;

#[test]
fn daemon_is_alive_detects_listener_and_stale_socket() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("pttman.sock");
    assert!(!socket::daemon_is_alive(&path));

    let listener = UnixDatagram::bind(&path).unwrap();
    assert!(socket::daemon_is_alive(&path));

    drop(listener);
    assert!(path.exists());
    assert!(!socket::daemon_is_alive(&path));
}
