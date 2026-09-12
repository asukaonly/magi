//! English console flow; the selected Magi language controls business content.

use crate::{
    cli::{self, InitOptions},
    console_api::{array, management, string, Api, Request, SetupDocument},
    console_runtime::{self, Foreground, RunMode},
};
use magi_service_contract::config::ServerConfig;
use serde_json::{json, Value};
use std::{
    io::{IsTerminal, Read},
    path::Path,
};

fn terminal() -> Result<(), String> {
    if !std::io::stdin().is_terminal() || !std::io::stderr().is_terminal() {
        return Err("Guided setup requires a terminal. Use init and run for automation, or configure --from-stdin against a running service.".into());
    }
    if !cfg!(unix) {
        return Err("Console setup requires a Unix host in this release. Use explicit run and configure through Magi desktop.".into());
    }
    Ok(())
}

fn ui<T>(result: std::io::Result<T>) -> Result<T, String> {
    result.map_err(|error| {
        if error.kind() == std::io::ErrorKind::Interrupted {
            "Setup cancelled. Saved steps can be resumed.".into()
        } else {
            error.to_string()
        }
    })
}

fn text(prompt: &str, default: &str) -> Result<String, String> {
    ui(cliclack::input(prompt).default_input(default).interact())
}

fn clean(value: &str) -> String {
    value
        .chars()
        .filter(|c| !c.is_control())
        .take(240)
        .collect()
}

fn progress<T>(
    pending: &str,
    success: &str,
    failure: &str,
    operation: impl FnOnce() -> Result<T, String>,
) -> Result<T, String> {
    let spinner = cliclack::spinner();
    spinner.start(pending);
    let result = operation();
    if result.is_ok() {
        spinner.stop(success);
    } else {
        spinner.error(failure);
    }
    // Release the renderer before another prompt or error message writes to the terminal.
    drop(spinner);
    result
}

fn run_mode() -> Result<RunMode, String> {
    let mut select = cliclack::select("1/5 · Service settings — run mode").item(
        RunMode::Foreground,
        "Foreground",
        "Runs while this terminal is open; Ctrl+C stops it",
    );
    if cfg!(target_os = "macos") {
        select = select.item(
            RunMode::Background,
            "Background after login",
            "Install a macOS login service; keeps running after this terminal closes",
        );
    }
    ui(select.interact())
}

pub fn launch(path: &Path, options: InitOptions) -> Result<(), String> {
    terminal()?;
    ui(cliclack::intro("Magi Server"))?;
    let exists = path.try_exists().map_err(|e| e.to_string())?;
    if exists && options.supplied() {
        return Err("Deployment already exists. Initialization options cannot change it; edit its config while stopped.".into());
    }
    let config = if exists {
        ServerConfig::load(path)?
    } else {
        let default_data = match &options.data_dir {
            Some(data) => data.clone(),
            None => cli::home_path(".magi-center")?,
        };
        let data = text(
            "1/5 · Service settings — data directory (absolute path)",
            &default_data.to_string_lossy(),
        )?;
        let port: u16 = ui(
            cliclack::input("Loopback port (0 selects an available port)")
                .default_input(&options.port.unwrap_or(19080).to_string())
                .validate(|value: &String| {
                    value
                        .parse::<u16>()
                        .map(|_| ())
                        .map_err(|_| "Enter a port from 0 to 65535")
                })
                .interact(),
        )?;
        cli::create_config(path, &options, data.into(), port)?
    };
    ui(cliclack::note(
        "Deployment",
        format!(
            "Config: {}\nData: {}\nLogs: {}",
            path.display(),
            config.data_dir.display(),
            config.data_dir.join("logs").display()
        ),
    ))?;
    let running = management(&config, Request::Status).is_ok();
    let mut foreground = None;
    let mut background_started = false;
    let result: Result<(), String> = (|| {
        if !running {
            // Do not replace a recovering owner merely because management is unavailable.
            drop(magi_platform::instance::InstanceLease::runtime_owner(&config.data_dir)
                .map_err(|_| "This data directory already has an owner. Check its status/logs and retry when management is ready.")?);
            let mode = match console_runtime::saved_mode(path)? {
                Some(mode) => mode,
                None => {
                    let mode = run_mode()?;
                    console_runtime::save_mode(path, mode)?;
                    mode
                }
            };
            cli::validate_worker(&config)?;
            if mode == RunMode::Background {
                progress(
                    "Installing and starting the background service",
                    "Background service started; it will also start after login",
                    "Background service could not be started",
                    || crate::service_install::execute("install", path),
                )?;
                background_started = true;
            } else {
                foreground = Some(Foreground::start(path, &config)?);
            }
        } else {
            ui(cliclack::log::info(
                "1/5 · Service settings — using the running instance",
            ))?;
        }
        progress(
            "Waiting for the configuration service",
            "Configuration service is ready",
            "Service is not ready",
            || console_runtime::wait_ready(&config, &mut foreground),
        )?;
        let api = Api::connect(&config)?;
        if !api.completed()? {
            let in_terminal = ui(cliclack::select("2/5 · Setup method")
                .item(
                    true,
                    "Configure in this terminal",
                    "Language, model connection and default persona",
                )
                .item(
                    false,
                    "Continue in desktop",
                    "Show a pairing code and finish setup in Magi desktop",
                )
                .interact())?;
            if in_terminal {
                interactive_configure(&api)?;
            }
            pairing(&config, &api)?;
        }
        summary(path, &config, &api)?;
        if foreground.is_some() {
            ui(cliclack::outro(
                "Running in foreground. Press Ctrl+C to stop this service.",
            ))?;
        } else {
            ui(cliclack::outro(
                "Service remains running after this terminal closes.",
            ))?;
        }
        Ok(())
    })();
    if result.is_err() {
        if foreground.is_some() {
            let _ = cliclack::log::info("Stopping the foreground service started by this console. Saved configuration is retained.");
            drop(foreground.take());
        } else if running || background_started {
            let _ = cliclack::log::info(
                "The existing/background service remains running. Saved configuration is retained.",
            );
        }
    }
    result?;
    if let Some(owner) = foreground {
        owner.wait()?;
    }
    Ok(())
}

pub fn configure(path: &Path, from_stdin: bool) -> Result<(), String> {
    if !from_stdin {
        terminal()?;
        ui(cliclack::intro("Configure Magi — existing service"))?;
    }
    let config = ServerConfig::load(path)?;
    let api = Api::connect(&config)?;
    if from_stdin {
        if std::io::stdin().is_terminal() {
            return Err("Pipe a setup JSON document to --from-stdin; secrets must not be entered as command arguments.".into());
        }
        let mut bytes = Vec::new();
        std::io::stdin()
            .take(1_048_577)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        if bytes.len() > 1_048_576 {
            return Err("Setup input exceeds 1 MiB".into());
        }
        let document: SetupDocument = serde_json::from_slice(&bytes)
            .map_err(|_| "Expected a setup document with language, llm and persona_slug")?;
        apply_document(&api, document)?;
        println!("Configuration saved. The existing service remains running.");
    } else {
        interactive_configure(&api)?;
        summary(path, &config, &api)?;
        ui(cliclack::outro(
            "Configuration saved. The existing service remains running.",
        ))?;
    }
    Ok(())
}

fn interactive_configure(api: &Api) -> Result<(), String> {
    let completed = api.completed()?;
    let mut snapshot = api.snapshot(completed)?;
    let initial = string(&snapshot["preferences"], "language")?.to_owned();
    let language = ui(cliclack::select(
        "3/5 · Magi language — persona content and default conversation language",
    )
    .item(
        "zh".to_owned(),
        "Chinese (Simplified)",
        "Chinese persona content and default conversation language",
    )
    .item(
        "en".to_owned(),
        "English",
        "English persona content and default conversation language",
    )
    .initial_value(initial)
    .interact())?;
    snapshot = api.set_language(completed, &language)?;
    loop {
        let configured = snapshot["llm"]["selections"]["core"]["model"]
            .as_str()
            .is_some_and(|s| !s.is_empty());
        let reuse = configured
            && ui(cliclack::confirm(
                "4/5 · Model configuration — keep and verify the saved models?",
            )
            .initial_value(true)
            .interact())?;
        let llm = if reuse {
            snapshot["llm"].clone()
        } else {
            collect_model(api, &snapshot["llm"])?
        };
        let tested = progress(
            "Verifying core and fast models (a small provider request may be billed)",
            "Model connection verified",
            "Model verification failed",
            || api.test_models(&llm),
        );
        match tested {
            Ok(()) => {
                snapshot["llm"] = llm;
                snapshot = api.save(&snapshot, completed, false)?;
                break;
            }
            Err(error) => {
                ui(cliclack::log::warning(error))?;
                if !ui(cliclack::confirm("Try model configuration again?")
                    .initial_value(true)
                    .interact())?
                {
                    return Err("Model setup is incomplete. The saved draft can be resumed.".into());
                }
            }
        }
    }
    let previews = api.call(
        "GET",
        &format!("/personas/seed-previews?locale={language}"),
        None,
    )?;
    let choices = array(&previews, "data")?;
    if choices.is_empty() {
        return Err("No builtin personas are available for the selected language".into());
    }
    let mut select = cliclack::select("5/5 · Default persona");
    let active = api.call("GET", "/personas/active", None)?;
    let personas = api.call("GET", "/personas/", None)?;
    let current = array(&personas, "data")?
        .iter()
        .find(|p| p["persona_id"] == active["persona_id"] && p["locale"] == language);
    for choice in choices {
        let slug = string(choice, "seed_slug")?.to_owned();
        select = select.item(
            slug.clone(),
            clean(string(choice, "name")?),
            clean(string(choice, "description")?),
        );
        if current.is_some_and(|p| p["seed_slug"] == slug)
            || (current.is_none() && choice["is_default"] == true)
        {
            select = select.initial_value(slug);
        }
    }
    let slug = ui(select.interact())?;
    api.activate_seed(&language, &slug)?;
    if !completed {
        api.save(&snapshot, false, true)?;
    }
    Ok(())
}

fn collect_model(api: &Api, previous: &Value) -> Result<Value, String> {
    let catalog = api.call("GET", "/llm/providers/catalog", None)?;
    let providers = array(&catalog["data"], "providers")?;
    let mut select = cliclack::select("4/5 · Model configuration — provider");
    for entry in providers {
        if entry["source"] == "builtin" {
            let id = string(entry, "id")?.to_owned();
            select = select.item(id.clone(), id, "");
        }
    }
    select = select.item(
        "custom".into(),
        "Custom provider",
        "OpenAI-compatible endpoint",
    );
    let id = ui(select.interact())?;
    let mut provider = if previous["providers"][&id].is_object() {
        previous["providers"][&id].clone()
    } else if id == "custom" {
        api.call("GET", "/llm/providers/custom-template", None)?["data"]["defaults"].clone()
    } else {
        json!({"enabled":true,"provider_type":id,"display_name":id})
    };
    let mut meta = providers
        .iter()
        .find(|item| item["id"] == id)
        .cloned()
        .unwrap_or(Value::Null);
    if let Some(plans) = meta["plans"].as_array().filter(|plans| !plans.is_empty()) {
        let mut choice = cliclack::select("Provider plan");
        for plan in plans {
            let name = string(plan, "id")?.to_owned();
            choice = choice.item(name.clone(), name, "");
        }
        provider["provider_plan"] = ui(choice.interact())?.into();
        let resolved = api.call(
            "POST",
            "/llm/providers/catalog",
            Some(&json!({"providers":{id.clone():provider}})),
        )?;
        meta = array(&resolved["data"], "providers")?
            .iter()
            .find(|entry| entry["id"] == id)
            .ok_or("Provider plan is unavailable")?
            .clone();
    }
    let default_url = meta["default_base_url"].as_str().unwrap_or("");
    let base_url = text("Provider base URL", default_url)?;
    let url = reqwest::Url::parse(&base_url).map_err(|_| "Enter a valid provider URL")?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("Provider URL must be HTTP(S) without embedded credentials".into());
    }
    let key_required = meta["fields"]["api_key"]["required"]
        .as_bool()
        .unwrap_or(id != "custom");
    let mut password =
        cliclack::password("Provider API key (hidden; leave empty for keyless endpoints)");
    if !key_required {
        password = password.allow_empty();
    }
    let api_key = ui(password.interact())?;
    provider["api_key"] = api_key.clone().into();
    provider["base_url"] = base_url.clone().into();
    if !provider["services"].is_object() {
        provider["services"] = json!({"embedding":{"enabled":false},"image_generation":{"enabled":false},"tts":{"enabled":false}});
    }
    provider["services"]["chat"] = json!({"enabled":true,"api_key":api_key,"base_url":base_url});
    let core = text("Core model", meta["default_model"].as_str().unwrap_or(""))?;
    let fast = text(
        "Fast model",
        meta["default_classify_model"].as_str().unwrap_or(&core),
    )?;
    if id == "custom" {
        provider["display_name"] = "Custom provider".into();
        provider["api_format"] = "openai".into();
        provider["custom_models"] = json!([core, fast]);
        provider["custom_default_model"] = core.clone().into();
    }
    let mut llm = previous.clone();
    // Other providers and advanced scenarios remain in the server snapshot.
    llm["providers"][&id] = provider;
    llm["selections"]["core"] = json!({"provider_id":id,"model":core});
    llm["selections"]["auxiliary"] = json!({"provider_id":id,"model":fast});
    llm["selections"]["memory_summarizer"] = llm["selections"]["core"].clone();
    Ok(llm)
}

fn apply_document(api: &Api, document: SetupDocument) -> Result<(), String> {
    if !matches!(document.language.as_str(), "en" | "zh") {
        return Err("Magi language must be en or zh".into());
    }
    // Validate the selected persona before committing any configuration.
    let previews = api.call(
        "GET",
        &format!("/personas/seed-previews?locale={}", document.language),
        None,
    )?;
    if !array(&previews, "data")?
        .iter()
        .any(|p| p["seed_slug"] == document.persona_slug)
    {
        return Err("Persona is not available in the selected Magi language".into());
    }
    let completed = api.completed()?;
    api.test_models(&document.llm)?;
    let mut snapshot = api.set_language(completed, &document.language)?;
    snapshot["llm"] = document.llm;
    let snapshot = api.save(&snapshot, completed, false)?;
    api.activate_seed(&document.language, &document.persona_slug)?;
    if !completed {
        api.save(&snapshot, false, true)?;
    }
    Ok(())
}

fn pairing(config: &ServerConfig, api: &Api) -> Result<(), String> {
    let grant = management(config, Request::Pair)?;
    ui(cliclack::note("Connect Magi desktop", format!(
        "Choose Connect to remote Magi.\nSame-machine address: {}\nPairing code (single use, 30 minutes):\n{}\nCopy only the code, without quotes. Restarting the service invalidates it.",
        api.base_url.trim_end_matches("/api"), string(&grant, "pairing_token")?
    )))
}

fn summary(path: &Path, config: &ServerConfig, api: &Api) -> Result<(), String> {
    let completed = api.completed()?;
    let readiness = api.call("GET", "/ready", None)?;
    let state = if !completed {
        "Service running — setup required"
    } else if readiness["data"]["runtime_ready"] == true {
        "Service running — agent ready"
    } else {
        "Configuration saved — agent is not ready yet; check status and logs"
    };
    ui(cliclack::note("Magi Server", format!(
        "{state}\nData: {}\nSame-machine address: {}\nCross-device HTTPS: configure a same-machine HTTPS proxy separately.\nNew pairing code: magi-server pair --config '{}'\nEdit Magi settings: magi-server configure --config '{}'\nService log: {}",
        config.data_dir.display(), api.base_url.trim_end_matches("/api"),
        path.display().to_string().replace('\'', "'\\''"), path.display().to_string().replace('\'', "'\\''"), config.data_dir.join("logs/service.log").display(),
    )))
}
