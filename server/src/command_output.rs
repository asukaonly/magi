//! Command-specific summaries. Rendering never performs service mutations.

use crate::{
    console_api::{array, string},
    operator_output::{next_step, Tone},
};
use magi_service_contract::config::ServerConfig;
use serde_json::Value;
use std::path::Path;

pub fn lifecycle(path: &Path, value: &Value) -> Result<String, String> {
    let command = string(value, "command")?;
    let outcome = string(value, "outcome")?;
    let (tone, title, explanation) = match (command, outcome) {
        ("stop" | "uninstall", "not_installed") => (Tone::Info, "No background service is installed.", "No action was needed. This command does not stop a service running in another terminal or desktop."),
        ("uninstall", _) => (Tone::Success, "Background service uninstalled.", "Login startup has been removed. Your data and configuration are preserved."),
        ("stop", "already_stopped") => (Tone::Info, "Background service is already stopped.", "Your data is preserved. Login startup remains installed."),
        ("stop", "stopped") => (Tone::Success, "Background service stopped.", "Your data is preserved. Login startup remains installed."),
        (_, "already_loaded") => (Tone::Info, "Background service is already loaded.", "This command did not restart it. Check status to see whether Magi is ready."),
        ("restart", "start_requested") => (Tone::Pending, "Restart requested.", "The previous background job has stopped. macOS has accepted the new start request; readiness has not been checked."),
        ("install" | "start", "start_requested") => (Tone::Pending, "Background start requested.", "Login startup is installed. macOS has accepted the start request; readiness has not been checked."),
        _ => return Err("Unrecognized service action result; check status before retrying".into()),
    };
    let mut text = format!(
        "{}\n{explanation}\n\nConfig: {}\nData: {}",
        tone.line(title),
        path.display(),
        string(value, "data_dir")?
    );
    let (label, args): (&str, &[&str]) = match command {
        _ if outcome == "not_installed" => ("inspect this deployment", &["status"]),
        "stop" => ("review this deployment before starting again", &["status"]),
        "uninstall" => ("open setup or manage this deployment", &[]),
        _ => ("check readiness", &["status"]),
    };
    text.push_str(&next_step(path, label, args));
    Ok(text)
}

pub fn initialized(path: &Path, config: &ServerConfig) -> String {
    format!(
        "{}\nThe service has not been started.\n\nConfig: {}\nData: {}{}",
        Tone::Success.line("Deployment configuration created."),
        path.display(),
        config.data_dir.display(),
        next_step(path, "open setup", &[])
    )
}

pub fn configuration(path: &Path, config: &ServerConfig) -> Result<String, String> {
    let mut lines = vec![
        Tone::Info.line("Saved deployment settings"),
        format!("Config: {}", path.display()),
        "These are saved values; the running service may be using earlier settings.".into(),
        String::new(),
    ];
    fn fields(value: &Value, indent: usize, lines: &mut Vec<String>) {
        if let Value::Object(entries) = value {
            for (key, value) in entries {
                let label = key.replace("_secs", " (seconds)").replace('_', " ");
                let label = format!("{}{}", label[..1].to_uppercase(), &label[1..]);
                if value.is_object() {
                    lines.push(format!("{}{label}", " ".repeat(indent)));
                    fields(value, indent + 2, lines);
                } else {
                    let display = match value {
                        Value::Null => "Not set".into(),
                        Value::String(text) => text.clone(),
                        Value::Array(items) if items.is_empty() => "None".into(),
                        Value::Array(items) => items
                            .iter()
                            .map(|v| v.as_str().unwrap_or("Invalid value"))
                            .collect::<Vec<_>>()
                            .join("\n    "),
                        _ => value.to_string(),
                    };
                    lines.push(format!("{}{label}: {display}", " ".repeat(indent)));
                }
            }
        }
    }
    fields(
        &serde_json::to_value(config).map_err(|e| e.to_string())?,
        0,
        &mut lines,
    );
    lines.push(next_step(
        path,
        "edit deployment settings",
        &["config", "edit"],
    ));
    Ok(lines.join("\n"))
}

pub fn pairing(value: &Value, scope: Option<(&str, &str)>) -> Result<String, String> {
    let code = string(value, "pairing_token")?;
    let title = if scope.is_some() {
        "Collector pairing code created."
    } else {
        "Desktop pairing code created."
    };
    let mut text = format!("{}\nSingle use · valid for 30 minutes · invalidated by a service restart\n\nPairing code:\n{code}", Tone::Success.line(title));
    if let Some((connection, source)) = scope {
        text.push_str(&format!("\n\nConnection: {connection}\nSource: {source}\nEnter this code when initializing the collector on its device.\nThis code grants access only to this source; it cannot pair a desktop administrator."));
    } else {
        text.push_str("\n\nOpen Magi desktop, choose Connect to remote Magi, and paste only the code.\nUse the service address shown by status, or use connect for guided address setup.");
    }
    Ok(text)
}

pub fn clients(path: &Path, value: &Value) -> Result<String, String> {
    let clients = value.as_array().ok_or("Invalid paired-device response")?;
    if clients.is_empty() {
        return Ok(format!(
            "{}{}",
            Tone::Info.line("No paired devices yet."),
            next_step(path, "connect a desktop", &["connect"])
        ));
    }
    let mut lines = vec![Tone::Info.line(format!("Paired devices ({})", clients.len()))];
    for client in clients {
        let state = match client.get("revoked_at_ms") {
            Some(Value::Null) => "Access allowed",
            Some(Value::Number(_)) => "Revoked",
            _ => return Err("Invalid device revocation status".into()),
        };
        lines.push(format!(
            "\n{} — {state}\n  ID: {}\n  Role: {}",
            string(client, "name")?,
            string(client, "client_id")?,
            string(client, "role")?
        ));
        if let Some(scope) = client.get("collector_scope").filter(|v| !v.is_null()) {
            lines.push(format!(
                "  Connection: {}\n  Source: {}",
                string(scope, "connection_id")?,
                string(scope, "source_type")?
            ));
        }
    }
    lines.push("\nAccess allowed does not mean the device is currently online.".into());
    lines.push(next_step(
        path,
        "revoke a device (replace DEVICE_ID)",
        &["revoke", "--client-id", "DEVICE_ID"],
    ));
    Ok(lines.join("\n"))
}

pub fn connections(plugin: &str, value: &Value) -> Result<String, String> {
    let entries = array(value, "connections")?;
    let mut text = Tone::Info.line(format!("Plugin connections — {plugin} ({})", entries.len()));
    if entries.is_empty() {
        text.push_str("\nNo connections exist. Add one in Magi desktop's plugin settings first.");
    }
    for entry in entries {
        let enabled = entry
            .get("enabled")
            .and_then(Value::as_bool)
            .ok_or("Invalid plugin connection state")?;
        text.push_str(&format!(
            "\n\n{} — {}\n  Connection ID: {}",
            string(entry, "display_name")?,
            if enabled { "Enabled" } else { "Disabled" },
            string(entry, "connection_id")?
        ));
    }
    Ok(text)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn lifecycle_summaries_distinguish_requests_and_completed_actions() {
        let path = Path::new("/tmp/deployment.json");
        for (command, outcome, title) in [
            (
                "stop",
                "not_installed",
                "No background service is installed",
            ),
            ("stop", "stopped", "Background service stopped."),
            ("stop", "already_stopped", "already stopped"),
            ("uninstall", "stopped", "uninstalled"),
            ("start", "already_loaded", "already loaded"),
            ("install", "start_requested", "start requested"),
            ("restart", "start_requested", "Restart requested"),
        ] {
            let value = json!({"command":command, "outcome":outcome, "data_dir":"/tmp/magi-data"});
            let text = lifecycle(path, &value).unwrap();
            assert!(text.contains(title), "{text}");
            assert!(text.contains("/tmp/magi-data"));
            assert!(text.contains("Next step"));
            if outcome == "start_requested" {
                assert!(text.contains("readiness has not been checked"));
            }
        }
    }

    #[test]
    fn devices_and_connections_have_empty_states_and_do_not_dump_settings() {
        assert!(clients(Path::new("/tmp/config.json"), &json!([]))
            .unwrap()
            .contains("No paired devices"));
        assert!(connections("calendar", &json!({"connections":[]}))
            .unwrap()
            .contains("Add one"));
        let text = connections("calendar", &json!({"connections":[{"display_name":"Work", "connection_id":"conn_test", "enabled":true, "settings":{"secret":"hidden"}}]})).unwrap();
        assert!(text.contains("conn_test"));
        assert!(!text.contains("hidden"));
        assert!(clients(Path::new("/tmp/config.json"), &json!([{"name":"Broken"}])).is_err());
    }
}
