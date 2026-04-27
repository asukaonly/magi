//! Guardrails for SQLite write ownership in the Rust gateway.
//!
//! Native gateway writes are intentionally narrow and documented in
//! `docs/project-overview.md`. This test keeps new write-capable modules from
//! appearing without an explicit ownership review.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

const ALLOWED_SQLITE_WRITE_FILES: &[&str] = &[
    "src/api/messages.rs",
    "src/api/metrics.rs",
    "src/api/schedules.rs",
    "src/api/tasks.rs",
    "src/db.rs",
];

const WRITE_MARKERS: &[&str] = &[
    "open_readwrite(",
    "sqlite_open_read_write",
    "insert into",
    "update ",
    "delete from",
    "create index",
    "execute_batch(",
];

#[test]
fn sqlite_write_modules_are_explicitly_owned() {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let src_dir = manifest_dir.join("src");
    let allowed: BTreeSet<String> = ALLOWED_SQLITE_WRITE_FILES
        .iter()
        .map(|path| path.to_string())
        .collect();

    let mut observed = BTreeSet::new();
    collect_write_files(&src_dir, &manifest_dir, &mut observed);

    let unexpected: Vec<_> = observed.difference(&allowed).cloned().collect();
    assert!(
        unexpected.is_empty(),
        "SQLite write markers found in unowned gateway files: {unexpected:?}. Update docs/project-overview.md and ALLOWED_SQLITE_WRITE_FILES if the new write path is intentional."
    );
}

fn collect_write_files(dir: &Path, manifest_dir: &Path, observed: &mut BTreeSet<String>) {
    for entry in fs::read_dir(dir).expect("read gateway source dir") {
        let entry = entry.expect("read source dir entry");
        let path = entry.path();
        if path.is_dir() {
            collect_write_files(&path, manifest_dir, observed);
            continue;
        }
        if path.extension().and_then(|ext| ext.to_str()) != Some("rs") {
            continue;
        }
        let content = fs::read_to_string(&path).expect("read Rust source file");
        let normalized = content.to_lowercase();
        if WRITE_MARKERS
            .iter()
            .any(|marker| normalized.contains(marker))
        {
            observed.insert(relative_path(&path, manifest_dir));
        }
    }
}

fn relative_path(path: &Path, manifest_dir: &Path) -> String {
    path.strip_prefix(manifest_dir)
        .expect("source file should live under manifest dir")
        .to_string_lossy()
        .replace('\\', "/")
}
