# Ripgrep Runtime Binary

Place platform-specific ripgrep binaries here when vendoring them into desktop sidecar builds.

Supported lookup paths:

- `windows-x64/rg.exe`
- `windows-arm64/rg.exe`
- `macos-x64/rg`
- `macos-arm64/rg`
- `linux-x64/rg`
- `linux-arm64/rg`

If no vendored binary is present, the sidecar build helper copies `rg` from the build machine PATH when available. At runtime, the grep tool checks this bundled location first and then falls back to PATH before using the Python search implementation.
