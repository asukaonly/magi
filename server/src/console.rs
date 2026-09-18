//! English console flow; the selected Magi language controls business content.

use crate::{
    cli::{self, InitOptions},
    console_api::{array, string, Api, SetupDocument},
    console_runtime::RunMode,
};
use magi_service_contract::config::ServerConfig;
use serde_json::{json, Value};
use std::{
    io::{IsTerminal, Read},
    path::Path,
};

pub(crate) fn terminal() -> Result<(), String> {
    if !std::io::stdin().is_terminal() || !std::io::stderr().is_terminal() {
        return Err("Guided setup requires a terminal. Use init and run for automation, or configure --from-stdin against a running service.".into());
    }
    if !cfg!(unix) {
        return Err("Console setup requires a Unix host in this release. Use explicit run and configure through Magi desktop.".into());
    }
    Ok(())
}

pub(crate) fn ui<T>(result: std::io::Result<T>) -> Result<T, String> {
    result.map_err(|error| {
        if error.kind() == std::io::ErrorKind::Interrupted {
            "Setup cancelled. Saved steps can be resumed.".into()
        } else {
            error.to_string()
        }
    })
}

pub(crate) fn text(prompt: &str, default: &str) -> Result<String, String> {
    ui(cliclack::input(prompt).default_input(default).interact())
}

fn validate_data_path(value: &str) -> Result<(), String> {
    let path = Path::new(value);
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err(
            "Enter an absolute directory without '..' (for example /Users/you/.magi-center)".into(),
        );
    }
    if path.exists() && !path.is_dir() {
        return Err("Choose a directory, not a file".into());
    }
    if path.parent().is_none() || cli::home_path("").is_ok_and(|home| path == home) {
        return Err(
            "Choose a dedicated Magi directory, not the filesystem root or your home directory"
                .into(),
        );
    }
    Ok(())
}

fn validate_provider_url(value: &str) -> Result<(), String> {
    let url = reqwest::Url::parse(value).map_err(|_| "Enter a complete HTTP(S) provider URL")?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Use an HTTP(S) URL without credentials, query parameters or fragments".into());
    }
    Ok(())
}

fn provider_url(default: &str) -> Result<String, String> {
    ui(cliclack::input("Provider base URL")
        .default_input(default)
        .validate(|value: &String| validate_provider_url(value))
        .interact())
}

pub(crate) fn clean(value: &str) -> String {
    value
        .chars()
        .filter(|c| !c.is_control())
        .take(240)
        .collect()
}

pub(crate) fn progress<T>(
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

pub(crate) fn run_mode(background_available: bool) -> Result<RunMode, String> {
    choose_run_mode(
        "1/5 · Service settings — run mode",
        background_available,
        None,
    )
}

pub(crate) fn choose_run_mode(
    prompt: &str,
    background_available: bool,
    initial: Option<RunMode>,
) -> Result<RunMode, String> {
    if !background_available {
        ui(cliclack::log::info(if cfg!(target_os = "macos") {
            "Background mode is unavailable: another deployment owns the login service, or its ownership cannot be verified. View diagnostics for details."
        } else {
            "Background login service is available on macOS. Use your operating system's service manager for unattended deployment."
        }))?;
    }
    let mut select = cliclack::select(prompt).item(
        RunMode::Foreground,
        "Temporary development — foreground",
        "Closing this terminal or pressing Ctrl+C stops the service",
    );
    if background_available && cfg!(target_os = "macos") {
        select = select.item(
            RunMode::Background,
            "Long-term use — background after login",
            "Keeps running after closing the terminal; stops on logout; requires an awake Mac",
        );
    }
    if let Some(mode) = initial
        .filter(|m| *m == RunMode::Foreground || background_available && cfg!(target_os = "macos"))
    {
        select = select.initial_value(mode);
    }
    ui(select.interact())
}

pub fn launch(path: &Path, options: InitOptions) -> Result<(), String> {
    terminal()?;
    ui(cliclack::intro("Magi Server"))?;
    let exists = path.try_exists().map_err(|e| e.to_string())?;
    if exists && options.supplied() {
        return Err("Deployment already exists. Initialization options cannot change it; use config edit for run mode and port settings.".into());
    }
    let config = if exists {
        cli::load_config(path)?
    } else {
        let default_data = match &options.data_dir {
            Some(data) => data.clone(),
            None => cli::home_path(".magi-center")?,
        };
        let data: String = ui(cliclack::input(
            "1/5 · Service settings — data directory (absolute path)",
        )
        .default_input(&default_data.to_string_lossy())
        .validate(|value: &String| validate_data_path(value))
        .interact())?;
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
    crate::console_manager::run(path, &config)
}

pub fn configure(path: &Path, from_stdin: bool) -> Result<(), String> {
    if !from_stdin {
        terminal()?;
        ui(cliclack::intro("Configure Magi — existing service"))?;
    }
    let config = cli::load_config(path)?;
    crate::deployment_status::require_management(&config, path, true)?;
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
        edit_configuration(&api)?;
        summary(path, &config, &api)?;
        ui(cliclack::outro(
            "Configuration session closed. Saved changes are retained; the existing service remains running.",
        ))?;
    }
    Ok(())
}

pub(crate) fn interactive_configure(api: &Api) -> Result<(), String> {
    let completed = api.completed()?;
    let snapshot = api.snapshot(completed)?;
    let language = choose_language(
        &snapshot,
        "3/5 · Magi language — persona content and default conversation language",
    )?;
    let snapshot = api.set_language(completed, &language)?;
    let snapshot = configure_models(
        api,
        snapshot,
        completed,
        "4/5 · Model configuration — keep and verify the saved models?",
    )?;
    let slug = choose_persona(api, &language, "5/5 · Default persona")?;
    api.activate_seed(&language, &slug)?;
    if !completed {
        api.save(&snapshot, false, true)?;
    }
    Ok(())
}

pub(crate) fn edit_configuration(api: &Api) -> Result<(), String> {
    if !api.completed()? {
        return interactive_configure(api);
    }
    loop {
        let action = ui(cliclack::select(
            "Configure Magi — changes apply to all connected devices",
        )
        .item("models", "Models", "Verify and save model settings")
        .item(
            "persona",
            "Magi language and default persona",
            "Choose persona content in the selected language",
        )
        .item("back", "Back", "Keep saved changes")
        .interact())?;
        if action == "back" {
            return Ok(());
        }
        let snapshot = api.snapshot(true)?;
        match action {
            "models" => {
                configure_models(api, snapshot, true, "Keep and verify the saved models?")?;
            }
            "persona" => {
                let language = choose_language(
                    &snapshot,
                    "Magi language — persona content and default conversation language",
                )?;
                let slug = choose_persona(api, &language, "Default persona")?;
                api.set_language(true, &language)?;
                api.activate_seed(&language, &slug)?;
            }
            _ => unreachable!(),
        }
        ui(cliclack::log::success("Configuration saved"))?;
    }
}

fn choose_language(snapshot: &Value, prompt: &str) -> Result<String, String> {
    let initial = string(&snapshot["preferences"], "language")?.to_owned();
    let language = ui(cliclack::select(prompt)
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
    Ok(language)
}

fn configure_models(
    api: &Api,
    mut snapshot: Value,
    completed: bool,
    prompt: &str,
) -> Result<Value, String> {
    let configured = snapshot["llm"]["selections"]["core"]["model"]
        .as_str()
        .is_some_and(|s| !s.is_empty());
    let reuse = configured && ui(cliclack::confirm(prompt).initial_value(true).interact())?;
    let mut llm = if reuse {
        snapshot["llm"].clone()
    } else {
        collect_model(api, &snapshot["llm"])?
    };
    loop {
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
                loop {
                    match ui(
                        cliclack::select("Model settings are retained in this session")
                            .item(
                                "edit",
                                "Edit a setting",
                                "Correct one field without starting over",
                            )
                            .item("retry", "Retry verification", "Use the same settings")
                            .item(
                                "back",
                                "Return to menu",
                                "Discard this unverified attempt; keep saved configuration",
                            )
                            .interact(),
                    )? {
                        "edit" => llm = edit_model(api, &llm)?,
                        "retry" => break,
                        _ => return Err(
                            "Model setup is incomplete. Previously saved settings are unchanged."
                                .into(),
                        ),
                    }
                }
            }
        }
    }
    Ok(snapshot)
}

fn edit_model(api: &Api, previous: &Value) -> Result<Value, String> {
    let field = ui(
        cliclack::select("Which model setting would you like to change?")
            .item("key", "API key", "Keep the provider, address and models")
            .item("url", "Provider address", "Keep the credential and models")
            .item(
                "models",
                "Model names",
                "Core: conversations; fast: lightweight tasks",
            )
            .item("provider", "Change provider", "Choose another provider")
            .item("back", "Back", "Keep this attempt")
            .interact(),
    )?;
    if field == "provider" {
        return collect_model(api, previous);
    }
    let mut llm = previous.clone();
    let id = string(&llm["selections"]["core"], "provider_id")?.to_owned();
    match field {
        "key" => {
            let key: String = ui(cliclack::password("Provider API key (hidden)")
                .allow_empty()
                .interact())?;
            llm["providers"][&id]["api_key"] = key.clone().into();
            llm["providers"][&id]["services"]["chat"]["api_key"] = key.into();
        }
        "url" => {
            let url = provider_url(llm["providers"][&id]["base_url"].as_str().unwrap_or(""))?;
            llm["providers"][&id]["base_url"] = url.clone().into();
            llm["providers"][&id]["services"]["chat"]["base_url"] = url.into();
        }
        "models" => {
            let core = text("Core model", string(&llm["selections"]["core"], "model")?)?;
            let fast = text(
                "Fast model",
                string(&llm["selections"]["auxiliary"], "model")?,
            )?;
            llm["selections"]["core"]["model"] = core.clone().into();
            llm["selections"]["memory_summarizer"] = llm["selections"]["core"].clone();
            llm["selections"]["auxiliary"]["model"] = fast.clone().into();
            if id == "custom" {
                llm["providers"][&id]["custom_models"] = json!([core, fast]);
                llm["providers"][&id]["custom_default_model"] = core.into();
            }
        }
        _ => {}
    }
    Ok(llm)
}

fn choose_persona(api: &Api, language: &str, prompt: &str) -> Result<String, String> {
    let previews = api.call(
        "GET",
        &format!("/personas/seed-previews?locale={language}"),
        None,
    )?;
    let choices = array(&previews, "data")?;
    if choices.is_empty() {
        return Err("No builtin personas are available for the selected language".into());
    }
    let mut select = cliclack::select(prompt);
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
    ui(select.interact())
}

fn collect_model(api: &Api, previous: &Value) -> Result<Value, String> {
    let catalog = api.call("GET", "/llm/providers/catalog", None)?;
    let providers = array(&catalog["data"], "providers")?;
    let mut select = cliclack::select("Model provider");
    for entry in providers {
        if entry["source"] == "builtin" {
            let id = string(entry, "id")?.to_owned();
            let label = entry["display_name"].as_str().unwrap_or(&id);
            select = select.item(id.clone(), clean(label), "");
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
    let base_url = provider_url(default_url)?;
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

pub(crate) fn pairing(config: &ServerConfig, api: &Api) -> Result<(), String> {
    crate::console_connection::guide(config, &api.base_url)
}

pub(crate) fn summary(path: &Path, config: &ServerConfig, api: &Api) -> Result<(), String> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn input_validation_rejects_unusable_values_before_advancing() {
        assert!(validate_data_path("relative").is_err());
        assert!(validate_data_path("/tmp/../data").is_err());
        assert!(validate_data_path("/tmp/magi-test-data").is_ok());
        for value in [
            "oops",
            "file:///tmp/file",
            "https://key@host",
            "https://host?key=secret",
        ] {
            assert!(validate_provider_url(value).is_err());
        }
        assert!(validate_provider_url("http://127.0.0.1:1234/v1").is_ok());
        assert!(validate_provider_url("https://example.com/v1").is_ok());
    }
}
