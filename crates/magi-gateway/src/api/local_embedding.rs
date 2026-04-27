use axum::Json;
use serde_json::{json, Value};
use std::collections::HashSet;

use crate::db::{backend_configs_dir, embedding_models_dir};

/// Load preset model IDs from local_embedding_models.yaml.
fn load_preset_model_ids() -> HashSet<String> {
    let yaml_path = backend_configs_dir().join("local_embedding_models.yaml");
    let content = match std::fs::read_to_string(&yaml_path) {
        Ok(c) => c,
        Err(_) => return HashSet::new(),
    };
    let data: Value = match serde_yaml::from_str(&content) {
        Ok(d) => d,
        Err(_) => return HashSet::new(),
    };
    data.get("models")
        .and_then(|m| m.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| {
                    item.get("id")
                        .and_then(|id| id.as_str())
                        .map(|s| s.to_string())
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Check if a directory contains .onnx files (direct or in onnx/ subdir).
fn has_onnx_files(dir: &std::path::Path) -> bool {
    let check_dir = |d: &std::path::Path| -> bool {
        std::fs::read_dir(d)
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .any(|e| e.path().extension().and_then(|ext| ext.to_str()) == Some("onnx"))
    };
    if check_dir(dir) {
        return true;
    }
    let onnx_subdir = dir.join("onnx");
    onnx_subdir.is_dir() && check_dir(&onnx_subdir)
}

/// GET /api/local-embedding/discovered
pub async fn discover_external_models() -> Json<Value> {
    let result = tokio::task::spawn_blocking(|| {
        let embed_dir = embedding_models_dir();
        if !embed_dir.exists() {
            return json!([]);
        }

        let preset_ids = load_preset_model_ids();
        let mut entries: Vec<_> = std::fs::read_dir(&embed_dir)
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .collect();
        entries.sort_by_key(|e| e.file_name());

        let discovered: Vec<Value> = entries
            .into_iter()
            .filter_map(|entry| {
                let path = entry.path();
                if !path.is_dir() {
                    return None;
                }
                let dir_name = entry.file_name().to_string_lossy().to_string();
                if preset_ids.contains(&dir_name) {
                    return None;
                }

                let has_tokenizer = path.join("tokenizer.json").exists();
                let has_config = path.join("config.json").exists();
                let dimension = if has_config {
                    std::fs::read_to_string(path.join("config.json"))
                        .ok()
                        .and_then(|c| serde_json::from_str::<Value>(&c).ok())
                        .and_then(|cfg| cfg.get("hidden_size").and_then(|v| v.as_i64()))
                } else {
                    None
                };

                Some(json!({
                    "dir_name": dir_name,
                    "path": path.to_string_lossy(),
                    "has_onnx": has_onnx_files(&path),
                    "has_tokenizer": has_tokenizer,
                    "has_config": has_config,
                    "dimension": dimension,
                }))
            })
            .collect();

        json!(discovered)
    })
    .await
    .unwrap_or_else(|_| json!([]));
    Json(result)
}
