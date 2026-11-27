//! Sahte pane + sahte saat (`tests/tui.rs` ve `parity_tui`). Günlük biçimi `harness.py::op_g4_pane` ile aynı.

#![allow(dead_code)] // iki test ikilisi farklı yardımcıları kullanır

use cops_providers::{Key, Pane};
use serde_json::{json, Value};
use std::cell::{Cell, RefCell};

#[derive(Clone, Debug)]
pub struct Script {
    /// Sıradaki yakalamalar (None = okunamadı); bitince sonuncu tekrar eder, boşsa hep None.
    pub screens: Vec<Option<String>>,
    pub send_ok: bool,
    /// Tuş gönderimlerinin sonuçları; bitince true.
    pub keys: Vec<bool>,
    pub t0: f64,
    pub send_cost: f64,
    pub capture_cost: f64,
}

impl Default for Script {
    fn default() -> Self {
        Script {
            screens: Vec::new(),
            send_ok: true,
            keys: Vec::new(),
            t0: 1000.0,
            send_cost: 0.0,
            capture_cost: 0.0,
        }
    }
}

pub struct FakePane {
    pub script: Script,
    pub log: RefCell<Vec<Value>>,
    pub now: Cell<f64>,
    captures: Cell<usize>,
    key_calls: Cell<usize>,
}

impl FakePane {
    pub fn new(script: Script) -> Self {
        let now = Cell::new(script.t0);
        FakePane {
            script,
            now,
            log: RefCell::new(Vec::new()),
            captures: Cell::new(0),
            key_calls: Cell::new(0),
        }
    }

    pub fn screens(screens: &[&str]) -> Self {
        Self::new(Script {
            screens: screens.iter().map(|s| Some(s.to_string())).collect(),
            ..Script::default()
        })
    }

    /// Basılan tuş adları, sırayla.
    pub fn keys(&self) -> Vec<String> {
        self.of("key", 2)
    }

    /// Yazılan metinler, sırayla.
    pub fn texts(&self) -> Vec<String> {
        self.of("send_text", 2)
    }

    pub fn calls(&self, kind: &str) -> usize {
        self.log.borrow().iter().filter(|e| e[0] == kind).count()
    }

    /// Sahte saatte geçen süre.
    pub fn elapsed(&self) -> f64 {
        self.now.get() - self.script.t0
    }

    fn of(&self, kind: &str, i: usize) -> Vec<String> {
        self.log
            .borrow()
            .iter()
            .filter(|e| e[0] == kind)
            .map(|e| e[i].as_str().unwrap().to_string())
            .collect()
    }

    fn push(&self, v: Value) {
        self.log.borrow_mut().push(v);
    }

    fn advance(&self, secs: f64) {
        self.now.set(self.now.get() + secs);
    }
}

fn bits(x: f64) -> i64 {
    x.to_bits() as i64
}

impl Pane for FakePane {
    fn send_text(&self, name: &str, text: &str, settle: f64) -> bool {
        self.push(json!(["send_text", name, text, bits(settle)]));
        self.advance(self.script.send_cost);
        self.script.send_ok
    }

    fn send_key(&self, name: &str, key: Key) -> bool {
        self.push(json!(["key", name, key.name()]));
        let i = self.key_calls.replace(self.key_calls.get() + 1);
        self.script.keys.get(i).copied().unwrap_or(true)
    }

    fn capture(&self, name: &str, lines: u32) -> Option<String> {
        self.push(json!(["capture", name, lines, bits(self.now.get())]));
        let i = self.captures.replace(self.captures.get() + 1);
        assert!(i < 5000, "bitmeyen bekleme");
        self.advance(self.script.capture_cost);
        let n = self.script.screens.len();
        (n > 0)
            .then(|| self.script.screens[i.min(n - 1)].clone())
            .flatten()
    }

    fn monotonic(&self) -> f64 {
        self.now.get()
    }

    fn sleep(&self, secs: f64) {
        self.push(json!(["sleep", bits(secs)]));
        self.advance(secs);
    }
}
