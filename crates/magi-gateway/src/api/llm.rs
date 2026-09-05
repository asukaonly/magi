use axum::Json;
use serde_json::{json, Value};

const PROVIDER_REGISTRY: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../backend/configs/llm_providers.yaml"
));

/// Load llm_providers.yaml as a generic JSON Value.
fn load_llm_providers_yaml() -> Option<Value> {
    serde_yaml::from_str(PROVIDER_REGISTRY).ok()
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

#[cfg(test)]
mod tests {
    #[tokio::test]
    async fn bundled_provider_registry_produces_custom_template() {
        let axum::Json(response) = super::get_custom_template().await;
        assert_eq!(response["success"], true);
        assert!(response["data"]["template"].is_object());
        assert!(response["data"]["template"]["limits"].is_object());
        assert_eq!(response["data"]["defaults"]["api_format"], "openai");
        assert!(!super::load_llm_providers_yaml().unwrap()["providers"]
            .as_array()
            .unwrap()
            .is_empty());
    }
}
