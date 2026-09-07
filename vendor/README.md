# Reviewed dependency patches

## glib 0.18.5

The Linux GTK3 dependency chain requires `glib ^0.18`; the released fix for
RUSTSEC-2024-0429 / GHSA-wrw7-89jp-8q8g is in the incompatible 0.20 series.
The root Cargo workspace therefore uses the local `glib` patch.

`glib/` is the complete crates.io 0.18.5 archive, including its MIT license and
upstream tests. The only change is the two-line upstream
[VariantStrIter fix](https://github.com/gtk-rs/gtk-rs-core/pull/1343): make the
out-pointer mutable and pass `&mut p` to the variadic C function. The upstream
version is deliberately unchanged; version-only scanners may still report it.

`glib-provenance.json` records the original archive checksum, each original file
checksum and the patched file checksum. `scripts/check-vendored-glib.py` rejects
unexpected edits, missing files, and changes to the workspace patch. CI also
runs the upstream iterator tests with optimization, where the original code
crashes. The patch was verified against that failing original locally.

Validation (requires GLib development libraries and pkg-config):

```sh
python scripts/check-vendored-glib.py
cargo test --manifest-path vendor/glib/Cargo.toml --release --lib variant_iter::tests
```

Review this patch when upgrading Tauri's GTK/WebKit stack. Remove the local
override, sources, provenance and checks together once the complete supported
dependency graph resolves to a fixed registry version. Do not disable the
checks or claim that the unmodified 0.18.5 release is fixed.
