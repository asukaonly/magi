use std::path::PathBuf;

/// Resolve the Magi base directory (~/.magi).
pub fn magi_base_dir() -> PathBuf {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".magi")
}

/// Path to the chat database.
pub fn chat_db_path() -> PathBuf {
    magi_base_dir().join("data").join("chat").join("chat.db")
}

/// Path to the runtime trace database.
pub fn runtime_trace_db_path() -> PathBuf {
    magi_base_dir().join("runtime").join("runtime_trace.db")
}
