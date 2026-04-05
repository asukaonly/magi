use axum::Json;
use serde_json::{json, Value};

use crate::db::backend_configs_dir;

/// Load llm_providers.yaml as a generic JSON Value.
fn load_llm_providers_yaml() -> Option<Value> {
    let path = backend_configs_dir().join("llm_providers.yaml");
    let content = std::fs::read_to_string(&path).ok()?;
    serde_yaml::from_str(&content).ok()
}

/// GET /api/llm/providers/custom-template
pub async fn get_custom_template() -> Json<Value> {
    let result = tokio::task::spawn_blocking(|| {
        let registry = match load_llm_providers_yaml() {
            Some(r) => r,
            None => {
                return json!({
                    "success": false,
                    "message": "Failed to load LLM provider registry",
                })
            }
        };

        let mut template = registry
            .get("custom_provider")
            .cloned()
            .unwrap_or_else(|| json!({}));

        // Ensure `limits` field exists with defaults (Pydantic adds it even if YAML omits it)
        if template.get("limits").is_none() {
            template.as_object_mut().map(|obj| {
                obj.insert(
                    "limits".to_string(),
                    json!({
                        "context_window": null,
                        "max_output_tokens": null,
                        "max_concurrency": null,
                    }),
                )
            });
        }

        let display_name = template
            .get("display_name")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        json!({
            "success": true,
            "message": "LLM custom provider template loaded",
            "data": {
                "template": template,
                "defaults": {
                    "enabled": true,
                    "provider_type": "custom",
                    "display_name": display_name,
                    "api_key": "",
                    "base_url": "",
                    "api_format": "openai",
                    "custom_models": [],
                    "custom_default_model": "",
                    "model_metadata_overrides": {}
                }
            }
        })
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}
