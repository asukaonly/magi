//! Console adapter for the same authenticated product APIs used by desktop.

use magi_service_contract::config::ServerConfig;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;

#[cfg(unix)]
pub use magi_server_runtime::management::Request;
#[cfg(not(unix))]
pub enum Request {
    Status,
    Pair,
    Clients,
    Revoke { client_id: String },
    OperatorSession,
}

pub fn management(config: &ServerConfig, request: Request) -> Result<Value, String> {
    #[cfg(unix)]
    {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())?
            .block_on(magi_server_runtime::management::request(
                &config.data_dir,
                request,
            ))
    }
    #[cfg(not(unix))]
    {
        let _ = (config, request);
        Err("Console management requires a Unix host in this release".into())
    }
}

pub fn string<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("Service response is missing {key}"))
}

pub fn array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("Service response is missing {key}"))
}

pub struct Api {
    config: ServerConfig,
    client: reqwest::blocking::Client,
    pub base_url: String,
    server_id: String,
}

impl Api {
    pub fn connect(config: &ServerConfig) -> Result<Self, String> {
        // Desktop workspace builds can enable TLS in the shared HTTP dependency.
        let _ = rustls::crypto::ring::default_provider().install_default();
        let status = management(config, Request::Status)?;
        let base_url = string(&status, "base_url")?.to_owned();
        validate_loopback(&base_url)?;
        Ok(Self {
            config: config.clone(),
            base_url,
            server_id: string(&status, "server_id")?.into(),
            client: reqwest::blocking::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .connect_timeout(Duration::from_secs(3))
                .timeout(Duration::from_secs(90))
                .build()
                .map_err(|e| e.to_string())?,
        })
    }

    pub fn call(&self, method: &str, path: &str, body: Option<&Value>) -> Result<Value, String> {
        // A fresh private-channel session handles long pauses without retrying mutations.
        let access = management(&self.config, Request::OperatorSession).map_err(|error| {
            format!("Local operator authorization is unavailable. Check service status; if it was started with an older executable, restart this deployment and retry. {error}")
        })?;
        if string(&access, "base_url")? != self.base_url
            || string(&access["session"], "server_id")? != self.server_id
        {
            return Err(
                "Service identity changed. Run setup again against the current instance.".into(),
            );
        }
        let mut request = self
            .client
            .request(
                method
                    .parse::<reqwest::Method>()
                    .map_err(|e| e.to_string())?,
                format!("{}{path}", self.base_url),
            )
            .header(
                "x-magi-session-token",
                string(&access["session"], "access_token")?,
            )
            .header("accept-language", "en")
            .timeout(Duration::from_secs(if method == "GET" { 8 } else { 90 }));
        if let Some(body) = body {
            request = request.json(body);
        }
        let response = request.send().map_err(|_| format!("Service request failed: {method} {path}. Check service status and logs; changes may have been saved."))?;
        let status = response.status();
        if !status.is_success() {
            return Err(if status.as_u16() == 409 {
                "Configuration changed in another client. Run configure again to reload it.".into()
            } else {
                format!("Service rejected {method} {path} (HTTP {}). Check the service log for details.", status.as_u16())
            });
        }
        let result: Value = response.json().map_err(|_| "Invalid service response")?;
        if result["success"] != true {
            return Err(format!(
                "Service could not complete {method} {path}. Check the service log for details."
            ));
        }
        Ok(result)
    }

    pub fn completed(&self) -> Result<bool, String> {
        self.call("GET", "/config/onboarding-status", None)?["data"]["completed"]
            .as_bool()
            .ok_or("Invalid setup status".into())
    }

    pub fn agent_ready(&self) -> Result<bool, String> {
        self.call("GET", "/ready", None)?["data"]["runtime_ready"]
            .as_bool()
            .ok_or("Invalid Agent readiness status".into())
    }

    pub fn snapshot(&self, completed: bool) -> Result<Value, String> {
        let response = self.call(
            "GET",
            if completed {
                "/config/"
            } else {
                "/config/onboarding-template"
            },
            None,
        )?;
        let snapshot = if completed {
            &response["data"]
        } else {
            &response["data"]["config"]
        };
        string(snapshot, "revision")?;
        if !snapshot["llm"].is_object() {
            return Err("Invalid model configuration snapshot".into());
        }
        Ok(snapshot.clone())
    }

    pub fn save(&self, snapshot: &Value, completed: bool, finish: bool) -> Result<Value, String> {
        let body = if completed {
            snapshot.clone()
        } else {
            json!({
                "revision": snapshot["revision"], "language": snapshot["preferences"]["language"], "llm": snapshot["llm"],
            })
        };
        let (method, path) = if completed {
            ("PUT", "/config/")
        } else if finish {
            ("POST", "/config/onboarding-complete")
        } else {
            ("PUT", "/config/onboarding-draft")
        };
        let receipt = self.call(method, path, Some(&body))?["data"].clone();
        string(&receipt, "revision")?;
        if !receipt["llm"].is_object() {
            return Err("Configuration save did not return a valid receipt".into());
        }
        Ok(receipt)
    }

    pub fn set_language(&self, completed: bool, language: &str) -> Result<Value, String> {
        if !matches!(language, "en" | "zh") {
            return Err("Magi language must be en or zh".into());
        }
        self.call(
            "PUT",
            "/config/preferences/language",
            Some(&json!({"language":language})),
        )?;
        self.snapshot(completed)
    }

    pub fn test_models(&self, llm: &Value) -> Result<(), String> {
        let mut tested = std::collections::HashSet::new();
        for name in ["core", "auxiliary"] {
            let selection = &llm["selections"][name];
            let provider_id = string(selection, "provider_id")?;
            let model = string(selection, "model")?;
            if provider_id.is_empty() || model.is_empty() {
                return Err(format!("Choose a provider and model for {name}"));
            }
            let provider = &llm["providers"][provider_id];
            if !provider.is_object() {
                return Err(format!("Missing provider configuration for {name}"));
            }
            if tested.insert((provider_id, model)) {
                self.call(
                    "POST",
                    "/llm/providers/test",
                    Some(&json!({"provider_id":provider_id,"provider":provider,"model":model})),
                )?;
            }
        }
        Ok(())
    }

    pub fn activate_seed(&self, language: &str, slug: &str) -> Result<(), String> {
        if !matches!(language, "en" | "zh") {
            return Err("Magi language must be en or zh".into());
        }
        let previews = self.call(
            "GET",
            &format!("/personas/seed-previews?locale={language}"),
            None,
        )?;
        if !array(&previews, "data")?
            .iter()
            .any(|item| item["seed_slug"] == slug)
        {
            return Err("Persona is not available in the selected Magi language".into());
        }
        self.call("POST", &format!("/personas/seed?locale={language}"), None)?;
        let personas = self.call("GET", "/personas/", None)?;
        let persona = array(&personas, "data")?
            .iter()
            .find(|persona| {
                persona["seed_slug"] == slug
                    && persona["locale"] == language
                    && persona["is_builtin"] == true
            })
            .ok_or("Seeded persona was not found")?;
        let id = string(persona, "persona_id")?;
        let activated = self.call("PUT", "/personas/active", Some(&json!({"persona_id":id})))?;
        if activated["persona_id"] != id {
            return Err("Persona activation was not confirmed".into());
        }
        Ok(())
    }
}

fn validate_loopback(base: &str) -> Result<(), String> {
    let url = reqwest::Url::parse(base).map_err(|_| "Invalid local service address")?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.path() != "/api"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(
            "Console management requires the authenticated loopback service address".into(),
        );
    }
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SetupDocument {
    pub language: String,
    pub llm: Value,
    pub persona_slug: String,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn operator_http_cannot_leave_loopback() {
        assert!(validate_loopback("http://127.0.0.1:19080/api").is_ok());
        for url in [
            "http://example.com:19080/api",
            "https://127.0.0.1:19080/api",
            "http://key@127.0.0.1:19080/api",
            "http://127.0.0.1:19080/api?key=secret",
        ] {
            assert!(validate_loopback(url).is_err());
        }
    }
}
