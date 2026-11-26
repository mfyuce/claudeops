//! Python <-> Rust parite: `fixtures/vectors/<işlev>.jsonl.gz` (parity/record.py) her işlev için bir testte tekrar oynatılır.
#![allow(unused_braces)] // rustfmt uzun `parity!` kapanışlarını bloğa sarıyor
mod basics;
mod cards;
mod closing;
mod explain;
mod gates;
mod generated;
mod harness;
mod identity;
mod idle;
mod idletext;
mod inserts;
mod logdedup;
mod markers;
mod notify;
mod observe;
mod prompts;
mod questions;
mod recovery;
mod report;
mod store;
mod tour;
mod world;
