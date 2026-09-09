//! Service lifecycle and operator configuration, independent of the desktop UI.

mod full_data_clear;
pub mod instance;
pub mod logs;
pub mod supervisor;
#[cfg(windows)]
mod windows_job;

#[cfg(unix)]
pub mod management;

mod maintenance;
