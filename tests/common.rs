#![allow(dead_code)]

use std::collections::HashMap;
use std::sync::Mutex;

use anyhow::{anyhow, Result};
use pttman::pactl::PactlRunner;

#[derive(Default)]
pub struct FakePactl {
    outputs: HashMap<String, String>,
    calls: Mutex<Vec<Vec<String>>>,
}

impl FakePactl {
    pub fn with_output(mut self, args: &[&str], output: &str) -> Self {
        self.outputs.insert(args.join(" "), output.to_string());
        self
    }

    pub fn calls(&self) -> Vec<Vec<String>> {
        self.calls.lock().expect("calls mutex poisoned").clone()
    }
}

impl PactlRunner for FakePactl {
    fn run(&self, args: &[&str]) -> Result<String> {
        self.calls
            .lock()
            .expect("calls mutex poisoned")
            .push(args.iter().map(|arg| (*arg).to_string()).collect());
        self.outputs
            .get(&args.join(" "))
            .cloned()
            .ok_or_else(|| anyhow!("missing fake pactl output for {}", args.join(" ")))
    }

    fn run_ok(&self, args: &[&str]) -> String {
        self.calls
            .lock()
            .expect("calls mutex poisoned")
            .push(args.iter().map(|arg| (*arg).to_string()).collect());
        self.outputs
            .get(&args.join(" "))
            .cloned()
            .unwrap_or_default()
    }
}
