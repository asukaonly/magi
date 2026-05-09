//! Guardrails for SQLite write ownership in the Rust gateway.
//!
//! Native gateway writes are intentionally narrow and documented in
//! `docs/project-overview.md`. This test keeps new write-capable modules from
//! appearing without an explicit ownership review.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

const ALLOWED_SQLITE_WRITE_FILES: &[&str] = &[
    "src/api/messages/mutations.rs",
    "src/api/memory/l2.rs",
    "src/api/schedules/write.rs",
    "src/api/tasks/write.rs",
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
        let normalized = production_source(&content).to_lowercase();
        if WRITE_MARKERS
            .iter()
            .any(|marker| normalized.contains(marker))
        {
            observed.insert(relative_path(&path, manifest_dir));
        }
    }
}

fn production_source(content: &str) -> String {
    let mut output = String::new();
    let mut lines = content.lines();

    while let Some(line) = lines.next() {
        if line.trim_start().starts_with("#[cfg(test)]") {
            skip_cfg_test_item(&mut lines);
            continue;
        }
        output.push_str(line);
        output.push('\n');
    }

    output
}

fn skip_cfg_test_item<'a, I>(lines: &mut I)
where
    I: Iterator<Item = &'a str>,
{
    let mut depth = 0i32;
    let mut opened = false;

    for line in lines.by_ref() {
        for ch in line.chars() {
            match ch {
                '{' => {
                    depth += 1;
                    opened = true;
                }
                '}' => depth -= 1,
                _ => {}
            }
        }
        if opened && depth <= 0 {
            break;
        }
    }
}

fn relative_path(path: &Path, manifest_dir: &Path) -> String {
    path.strip_prefix(manifest_dir)
        .expect("source file should live under manifest dir")
        .to_string_lossy()
        .replace('\\', "/")
}
