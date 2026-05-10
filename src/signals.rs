use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::Result;
use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
use signal_hook::iterator::Signals;

pub struct Handles {
    pub stop: Arc<AtomicBool>,
    pub reload: Arc<AtomicBool>,
}

impl Handles {
    pub fn stop_requested(&self) -> bool {
        self.stop.load(Ordering::SeqCst)
    }

    pub fn take_reload(&self) -> bool {
        self.reload.swap(false, Ordering::SeqCst)
    }
}

pub fn install() -> Result<Handles> {
    let stop = Arc::new(AtomicBool::new(false));
    let reload = Arc::new(AtomicBool::new(false));
    let stop_for_thread = Arc::clone(&stop);
    let reload_for_thread = Arc::clone(&reload);
    let mut signals = Signals::new([SIGHUP, SIGINT, SIGTERM])?;
    std::thread::Builder::new()
        .name("pttman-signals".into())
        .spawn(move || {
            for sig in &mut signals {
                match sig {
                    SIGINT | SIGTERM => stop_for_thread.store(true, Ordering::SeqCst),
                    SIGHUP => reload_for_thread.store(true, Ordering::SeqCst),
                    _ => {}
                }
            }
        })?;
    Ok(Handles { stop, reload })
}
