# Security Policy

## Supported Versions

Magi is under active development. Security fixes are applied to the latest
release and the current `main` branch. Older releases may not receive separate
patches; users should update to the newest stable version after a fix is
published.

## Reporting a Vulnerability

Do not disclose suspected vulnerabilities in public issues, discussions, pull
requests, logs, screenshots, or chat transcripts.

Use GitHub's private vulnerability reporting for this repository:

https://github.com/asukaonly/magi/security/advisories/new

If that form is unavailable, contact the maintainer through the GitHub profile
without including vulnerability details and request a private reporting
channel. Include the affected version or commit, platform, impact, reproduction
steps, and any suggested mitigation only after a private channel is established.

Please avoid accessing data that is not your own, disrupting other users, or
publishing exploit details before a fix is available. We will acknowledge a
complete report as soon as practical, validate its impact, coordinate a fix and
release, and credit the reporter when requested.

## Scope Notes

High-value areas include the desktop gateway and session boundary, private
resource tickets, Python sidecar IPC, plugin installation and dependency
execution, MCP transports and tools, archive handling, local data permissions,
updater and release signing, and credential or prompt leakage through API
responses and logs.

Reports about upstream dependencies are useful when they include a concrete
Magi execution path or affected shipped artifact. General product feedback and
non-security bugs should use the normal issue tracker.

## Dependency Audit Exceptions

CI audits frontend production dependencies, the clean Python environment, and
the Rust lockfile. Rust exceptions are exact and self-expiring: a changed
package version, dependency path, or feature reachability fails the check and
requires a new review.

- `RUSTSEC-2026-0194` and `RUSTSEC-2026-0195` remain associated with
  `quick-xml 0.37.5` only because `tauri-winrt-notification 0.7.2` uses its
  escaping helper when building Windows notification text. That dependency
  does not call the affected XML parsing APIs. The XML parser used by Tauri's
  plist dependency has been upgraded to patched `quick-xml 0.41.0`.
- `RUSTSEC-2026-0235` remains present only in the lockfile as an optional
  `rust_decimal` dependency. `rkyv` is not enabled or compiled by any Magi
  workspace target or feature.

These are reviewed non-reachable paths, not blanket advisory suppressions. The
enforcement and exact dependency checks live in
`scripts/check-rust-advisories.py`.
