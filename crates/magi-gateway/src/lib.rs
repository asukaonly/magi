pub mod api;
pub mod db;
pub mod ipc;
pub mod notification_bridge;

// Re-export axum for consumers that need to start the server
pub use axum;
