//! IPC subsystem — NDJSON channel between Rust gateway and Python worker.

pub mod client;
pub mod connection;
pub mod protocol;

pub use client::IpcClient;
pub use connection::RuntimeConnection;
