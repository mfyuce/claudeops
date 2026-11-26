//! Python <-> Rust parite: `fixtures/vectors/<işlev>.jsonl.gz` (parity/record.py) her işlev için bir testte tekrar oynatılır.
#![allow(unused_braces)] // rustfmt uzun `parity!` kapanışlarını bloğa sarıyor
mod basics;
mod cards;
mod closing;
mod gates;
mod generated;
mod harness;
mod identity;
mod inserts;
mod logdedup;
mod markers;
mod notify;
mod prompts;
mod questions;
mod store;
mod tour;
mod world;
