//! IPC subsystem — NDJSON channel between Rust gateway and Python worker.

pub mod client;
pub mod protocol;

pub use client::IpcClient;
