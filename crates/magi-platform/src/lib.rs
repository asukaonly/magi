//! OS primitives shared by desktop and independent service hosts.

pub mod credentials;
pub mod instance;
pub mod private_data;
#[cfg(unix)]
pub mod worker_guardian;
