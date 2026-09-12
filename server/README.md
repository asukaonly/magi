# Magi Server

Magi Server runs the Rust gateway and Python agent runtime without a desktop
window. The desktop client can use a local instance or connect to a paired
remote center. This release targets a logged-in, always-on Mac for deployment.

## Install and start

Copy the **entire `MagiServer` folder** from the disk image to a permanent
location, for example `/Applications/MagiServer`. Do not run it from the mounted
disk image. No system Python, Node.js, or Tauri installation is required.

Start with one command:

```sh
/Applications/MagiServer/magi-server
```

The English console guide has five steps:

1. **Service settings**: dedicated data directory, loopback port, and foreground
   or background-after-login mode. Defaults are `~/.magi-center`, port `19080`,
   and `~/.config/magi-server/server.json` for deployment configuration.
2. **Setup method**: configure in this terminal or continue in Magi desktop.
3. **Magi language**: Chinese (Simplified) or English. Prompts remain English;
   persona content and the center's default conversation language follow this choice.
4. **Model configuration**: provider and plan, endpoint, hidden API key, core and
   fast models. Defaults come from the service's provider catalog. Connection
   verification makes a small real provider request and may incur provider charges.
5. **Default persona**: select and activate a builtin persona in the chosen language.

Choosing desktop setup skips steps 3–5 and prints the actual same-machine address
and a thirty-minute, single-use pairing code. Setup stays incomplete until a
client finishes it. The console summary reports Agent readiness separately from
configuration completion and does not assume an HTTPS proxy exists.
Completing terminal setup also prints a first pairing code for connecting a UI.

Run the same command again to resume saved setup. If the service is already
running, the console reuses it; configured instances show their status without
repeating setup or generating another pairing code. A stopped instance starts
using the mode saved in the adjacent `server.console.json` file. This file holds
only the console run-mode preference, never model keys or business settings.

Foreground mode keeps the console open. Ctrl+C, cancellation, or loss of its
terminal stops the headless owner it launched and its gateway/Python processes;
saved steps remain available. This adds a console coordinator while interactive
foreground mode is open. Background mode installs the login service and keeps
running after terminal exit. Editing an existing service never takes ownership
of it. `configure` explicitly changes models, language and the default persona
after setup, using the same server APIs and masked secrets as desktop:

```sh
/Applications/MagiServer/magi-server configure
```

For source development, use `./scripts/dev-server.sh --setup`. It keeps the
development config/data defaults separate from the packaged deployment:
`~/.config/magi-server/dev.json` and `~/.magi-center-dev`.

The production default data root is in the user's home directory, **not the
current working directory or the application bundle**. The first-run guide can
choose another absolute path, saved as `data_dir` in the deployment JSON.
Later launches keep using that saved path regardless of the shell's directory.
Within the data root, business configuration is in `config/agent.yaml`, persisted
domain data is in `data/`, and diagnostics are in `logs/`.

For scripts and service managers, use explicit commands. They never prompt:

```sh
/Applications/MagiServer/magi-server init \
  --config "$HOME/.config/magi-server/server.json" \
  --data-dir "$HOME/.magi-center"
/Applications/MagiServer/magi-server run \
  --config "$HOME/.config/magi-server/server.json"
```

All commands accept `--config <absolute-path>` to target a specific deployment.
`init` can also take `--development-root <absolute-repository>` for source runs.
The no-command entry requires a terminal and refuses redirected input before
creating deployment configuration or starting a process.

`run` stays in the foreground as a lightweight Rust owner. It starts a separate
Rust gateway process, which owns Python. Control-C stops the complete owned
runtime. The default
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
roots and ports. The owner retains its data-root lease during restart cooldowns,
preventing another desktop or console owner from taking over that root.

`start`, `stop`, and `restart` manage this specific LaunchAgent. `status` reports
runtime readiness through a private local management socket. Logs are under
`<data-dir>/logs`: `service.log` for the managed service and `backend.log` for
Python. Each native output log retains an 8 MiB current file and two backups.
The interactive guide displays the log directory and writes service diagnostics
to files in both foreground and background mode. Installation and startup show
step feedback; early startup failures appear after the progress indicator stops,
without overwriting active prompts. Explicit `run` keeps service diagnostics in
the terminal unless `run --log-file <absolute-path>` is supplied; explicit
service-management commands print JSON results for automation.
Each service start creates missing log directories with private permissions,
including after a stopped service's logs were cleaned. A successful launchd
start request does not guarantee readiness; the console waits for the local
management service and reports its last connection error or supervisor phase
on timeout.

Stop the service before moving or removing data-root directories. Removing
`runtime/` from a live service breaks console management even while the HTTP
listener is still responding. For an installed service, `magi-server restart
--config <absolute-config-path>` recreates its runtime endpoints; retry setup
afterward. Restarting does not restore removed business data.

## Change configuration

Deployment settings (data root, port, runtime executable and supervision limits)
belong to `server.json`. Inspect or check them without starting Python:

```sh
magi-server config show
magi-server config validate
```

Stop a foreground service before editing this JSON file. For an installed login
service, use `uninstall` with the original config, edit and validate the file,
then `install` again so its command and shutdown deadline remain synchronized.
Changing `data_dir` selects another store; it does not move existing data.
`init` never overwrites an existing deployment. To change the interactive launch
preference, stop/uninstall the service and remove only the adjacent
`server.console.json`; the next no-command launch asks for run mode again.

Business settings live under the configured data root and are edited through
Magi desktop or `magi-server configure`. These changes preserve unrelated
settings and apply through the service's configuration/runtime lifecycle.

Automation can configure an already running center from standard input:

```sh
magi-server configure --config "$HOME/.config/magi-server/server.json" --from-stdin < setup.json
```

The document must contain exactly `language` (`zh` or `en`), `llm` (the product
API's LLM configuration object), and `persona_slug` (a builtin seed in that
language). Core and auxiliary selections are verified before saving, then the
persona is seeded/activated; unfinished onboarding is completed only afterwards.
Saved steps remain if a later step fails; rerun with corrected input to finish.
Keep any input file containing credentials private. The CLI does not print its
contents, accepts no API key argument, and does not persist an extra copy.

## Recovery and shutdown

The owning desktop or headless `run` process probes the gateway through the
authenticated server-info endpoint. It replaces that owned gateway after
sustained failed responses, even if its PID remains alive. Missing models,
Python startup and active maintenance do not count as gateway failures. Remote
clients never restart the center. A long suspension gap resets missed-probe
accounting rather than producing a burst of catch-up timeouts.

The service probes the Python event loop independently of model and plugin
readiness. The default `supervision` policy probes every 10 seconds, waits up to
5 seconds, and replaces a worker after 3 consecutive failed probes. It restores
the restart budget after 60 healthy seconds. After `max_restarts` retries, the
service keeps diagnostics available and waits 60 seconds before retrying.
Set `max_restarts` to 0 to require an operator restart after a worker or gateway
failure. The headless owner remains alive in that failed state, so launchd does
not bypass the disabled retry policy. Gateway recovery uses the same bounded
backoff, stable-health reset and cooldown policy; its diagnostics are in the
service log. API `supervisor` fields describe the inner Python supervisor.
A failed data maintenance operation remains blocked for explicit repair.

`status` includes `supervisor.phase`, `restart_count`, `last_error` and
`next_retry_at_ms`. `ready` means the transport responds; per-capability readiness
still determines whether a particular operation is available. `/api/health` is
only gateway liveness. A critical HTTP, management or notification task failure
stops the gateway so its headless owner (or the desktop) can recover the process.
Launchd restarts the headless owner itself if that owner exits unexpectedly.

`shutdown_timeout_secs` is the worker drain budget (default 30 seconds). The
service reserves 8 additional seconds for cleanup and its owner waits 5 seconds
longer. The generated LaunchAgent derives its exit deadline from this config.
Stop and uninstall with the installed configuration before changing these limits,
then reinstall so the registered deadline matches the service configuration.

## Connect a desktop client

After the service starts, generate a one-time pairing code on the center Mac:

```sh
/Applications/MagiServer/magi-server pair \
  --config "$HOME/.config/magi-server/server.json"
```

Paste only the output's `pairing_token` value (64 characters, without quotes or
the JSON object) into the desktop connection form. It works once and expires
after 30 minutes. Restarting the service invalidates outstanding codes; generate
a new code on the center you want to connect to. If the desktop runs on this same Mac, enter
`http://127.0.0.1:19080` (or the configured port). `http://localhost:<port>` also
works and is normalized to `127.0.0.1`. This still creates a paired connection;
closing the desktop leaves the independently deployed center running. The
desktop requires HTTPS when connecting from another computer.

For a source-development center, the corresponding pairing command is
`./target/debug/magi-server pair --config "$HOME/.config/magi-server/dev.json"`.

### Connect from another computer

The gateway listens only on loopback. Put a standard HTTPS reverse proxy on the
same Mac. For a private network, an optional convenience is
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve):

```sh
tailscale serve --bg http://127.0.0.1:19080
/Applications/MagiServer/magi-server pair \
  --config "$HOME/.config/magi-server/server.json"
```

Use the HTTPS address reported by the proxy and the one-time pairing token in
Magi desktop's connection screen. Tokens expire after 30 minutes. Pair each
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

## Configure the center

There are two configuration surfaces:

- **Models and everyday settings:** pair a Magi desktop with this center, then
  complete onboarding or open Settings. Model providers, API keys, personalities,
  memory and plugins are configured on the active center. An empty center can
  accept pairing and configuration before a model is available. Changes saved
  through the UI use the center's configuration API and runtime refresh flow.
  Client preferences such as tray behavior remain on the client device.
- **Deployment settings:** the file passed to `--config`, for example
  `~/.config/magi-server/server.json`, controls `port`, `data_dir`, worker paths,
  `max_restarts`, timeouts and `supervision`. The CLI reads this file at startup;
  it is not the place for model API keys. Edit it on the center Mac and restart
  the deployment. There is currently no graphical service installer or deployment
  configuration editor.

For a managed installation, the safe workflow for changing deployment settings
is to run `uninstall --config <file>` using the original configuration, edit the
JSON, then run `install --config <file>` and `status --config <file>`. Uninstall
preserves data. Reinstallation also updates launchd's recorded log path and
shutdown deadline. For a foreground run, stop with Control-C before editing,
then run the service again. Changing `data_dir` selects a different data root;
it does not move existing conversations, settings or paired identities.

With the example `--data-dir "$HOME/.magi-center"`, center configuration lives
under `~/.magi-center/config/` (`agent.yaml`, `llm.yaml`, `lifecycle.yaml` and
plugin configuration), with personality files under `~/.magi-center/personalities/`.
Prefer the connected UI so changes receive validation and runtime activation.
If editing these files manually, stop the service first and restart afterwards.

## Upgrade and uninstall

1. Use the **existing installation and configuration** to run `uninstall --config <file>`.
   This stops the managed service and removes its launch registration while preserving data.
2. Make a verified backup of the center data before upgrading.
3. Replace the entire application folder at the **same permanent path** with the
   new release. Do not merge old Python libraries into the new folder.
4. Run `install --config <file>` to register the new service and its shutdown deadline,
   then check `status` and the logs. For foreground deployments, stop/start `run` instead.

If moving the installation or configuration to another path, use the old
executable and config to run `uninstall` first, then update the absolute worker,
plugin Python, and avatar paths in the config and install from the new location.

`uninstall --config <file>` stops and removes only the managed LaunchAgent.
It preserves the data directory, configuration, paired devices, and application
folder. Removing the desktop client does not remove the standalone center.
Do not downgrade a migrated data directory without a tested restoration plan.

## Build from source

For development on macOS or Linux, install the backend dependencies into the
repository's `.venv`, then run:

```sh
./scripts/dev-server.sh
```

The script builds the debug server as needed, creates
`~/.config/magi-server/dev.json` on first use, and runs only the center using
Python source from this checkout. Its default data directory is
`~/.magi-center-dev` and its default loopback port is `19080`. Existing config
files are reused without modification. Control-C stops the owned runtime;
source changes require a restart. Tauri, Vite and a packaged sidecar are not needed.

To create another development instance, use absolute paths:

```sh
./scripts/dev-server.sh \
  --config "$HOME/.config/magi-server/experiment.json" \
  --data-dir "$HOME/.magi-center-experiment" \
  --port 19081
```

On subsequent runs, pass only `--config` for that instance. `--data-dir` and
`--port` are initialization options and are rejected when the config exists;
edit the existing config to change those values. Use `--help` for all options.

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

For isolated lifecycle fault injection on a development checkout, run
`python scripts/smoke-service-lifecycle.py --executable target/debug/magi-server`.
It exercises a real Python event-loop hang, responsive asynchronous work, service
crash/worker lease handoff, paired-session renewal and graceful drain using a
temporary data directory. It also suspends the whole gateway process and checks
headless recovery and final Python drain. The Linux gateway CI job runs this
probe with an isolated SDK environment. It does not load business plugins or
model providers.
