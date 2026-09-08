//! Service lifecycle and operator configuration, independent of the desktop UI.

pub mod config;
pub mod instance;
pub mod logs;
pub mod supervisor;
#[cfg(windows)]
mod windows_job;

#[cfg(unix)]
pub mod management;

mod maintenance;
