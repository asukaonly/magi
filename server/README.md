# Magi Server

Magi Server runs the Rust gateway and Python agent runtime without a desktop
window. The desktop client can use a local instance or connect to a paired
remote center. This release targets a logged-in, always-on Mac for deployment.

## Install and start

Copy the **entire `MagiServer` folder** from the disk image to a permanent
location, for example `/Applications/MagiServer`. Do not run it from the mounted
disk image. No system Python, Node.js, or Tauri installation is required.

Initialize a dedicated data directory (choose a different one if this Mac also
runs a separate local desktop instance):

```sh
/Applications/MagiServer/magi-server init \
  --config "$HOME/.config/magi-server/server.json" \
  --data-dir "$HOME/.magi-center"
/Applications/MagiServer/magi-server run \
  --config "$HOME/.config/magi-server/server.json"
```

`run` stays in the foreground; Control-C stops the owned worker. The default
HTTP listener is `127.0.0.1:19080`. Use `init --port <port>` to choose another.
The configuration records absolute bundle paths, so choose the permanent bundle
location before initialization. `init` refuses to overwrite an existing config.

For automatic startup after login, stop the foreground process, then run:

```sh
/Applications/MagiServer/magi-server install \
  --config "$HOME/.config/magi-server/server.json"
```

This registers and starts the current user's `app.magi.server` LaunchAgent.
Do not use `sudo`. It does not run before login, survive logout, or prevent Mac
sleep. Configure the host's power settings to keep it available. One managed
center is supported per macOS user; foreground instances can use separate data
roots and ports. The data-root lock prevents two processes opening the same root.

`start`, `stop`, and `restart` manage this specific LaunchAgent. `status` reports
runtime readiness through a private local management socket. Logs are under
`<data-dir>/logs`, including `service.stderr.log` and `service.stdout.log`.

## Connect another device

The gateway listens only on loopback. Put a standard HTTPS reverse proxy on the
same Mac. For a private network, an optional convenience is
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve):

```sh
tailscale serve --bg http://127.0.0.1:19080
/Applications/MagiServer/magi-server pair \
  --config "$HOME/.config/magi-server/server.json"
```

Use the HTTPS address reported by the proxy and the one-time pairing token in
Magi desktop's connection screen. Tokens expire after five minutes. Pair each
device separately. The private Serve endpoint is sufficient; public Funnel is
not required. Choose a hostname without private information because public TLS
certificate names appear in certificate transparency logs. Magi does not require
the Tailscale SDK or manually exported certificate files.

Other HTTPS proxies work too. Preserve the `/api` path and authentication headers,
disable buffering for `/api/events`, and allow long-running SSE with heartbeats
and streaming file transfers. Clients verify the certificate, center identity,
and protocol version. Do not use certificate-ignore options or expose the raw
HTTP port to another machine. The reverse proxy is part of the trusted host.

Paired devices have full owner access, including center data and plugin settings.
List and revoke individual devices with:

```sh
/Applications/MagiServer/magi-server clients --config "$HOME/.config/magi-server/server.json"
/Applications/MagiServer/magi-server revoke --config "$HOME/.config/magi-server/server.json" --client-id <id>
```

All plugins and their filesystem paths refer to the center. A remote desktop
does not silently start a local collector. Photos, Calendar, and protected folders
may require permissions on the center Mac; a background core does not grant those
permissions. Plugin availability and macOS permission behavior must be checked
on the installed host.

## Upgrade and uninstall

1. Use the **existing installation** to run `stop --config <file>`.
2. Make a verified backup of the center data before upgrading.
3. Replace the entire application folder at the **same permanent path** with the
   new release. Do not merge old Python libraries into the new folder.
4. Run `start --config <file>` and check `status` and the logs.

If moving the installation or configuration to another path, use the old
executable and config to run `uninstall` first, then update the absolute worker,
plugin Python, and avatar paths in the config and install from the new location.

`uninstall --config <file>` stops and removes only the managed LaunchAgent.
It preserves the data directory, configuration, paired devices, and application
folder. Removing the desktop client does not remove the standalone center.
Do not downgrade a migrated data directory without a tested restoration plan.

## Build from source

From the repository, `node scripts/prepare-service-bundle.mjs` stages the shared
service component under `build/service`. Release builds must supply a verified,
relocatable plugin Python runtime with `MAGI_PLUGIN_PYTHON_SOURCE`; a development
venv is not evidence of a self-contained release. The desktop packaging process
uses this same component. `node scripts/package-service-macos.mjs --target <triple>`
creates the standalone Mac image. Release CI also checks the signed component
copied into the desktop bundle before packaging it independently.

For source development only, `init` accepts `--development-root <absolute-repo>`.
Use a separate data directory for tests. The service is not production-validated
until the packaged runtime, plugin permissions, proxy transfers, and recovery
matrix have passed on the target devices.
