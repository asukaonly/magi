use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::path::{Path as StdPath, PathBuf};

use crate::db::magi_base_dir;

// ---- Path helpers ----

fn personalities_dir() -> PathBuf {
    magi_base_dir().join("personalities")
}

fn builtin_personalities_root() -> PathBuf {
    StdPath::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("backend")
        .join("personalities")
}

fn resolve_lang_dir(lang: &str) -> PathBuf {
    let normalized = lang.to_lowercase();
    let code = if normalized.starts_with("zh") {
        "zh"
    } else if normalized.starts_with("en") {
        "en"
    } else {
        &normalized
    };
    let dir = builtin_personalities_root().join(code);
    if dir.exists() {
        return dir;
    }
    let fallback = builtin_personalities_root().join("zh");
    if !fallback.exists() {
        let _ = std::fs::create_dir_all(&fallback);
    }
    fallback
}

fn builtin_avatar_dir() -> PathBuf {
    builtin_personalities_root().join("avatar")
}

fn user_avatar_dir() -> PathBuf {
    personalities_dir().join("avatar")
}

// ---- Avatar resolution ----

fn is_inline_avatar(value: &str) -> bool {
    value.chars().count() <= 4 && value.chars().any(|ch| ch as u32 > 127)
}

fn resolve_avatar_url(avatar: &str) -> String {
    let value = avatar.trim();
    if value.is_empty() {
        return String::new();
    }
    if value.starts_with("http://")
        || value.starts_with("https://")
        || value.starts_with('/')
        || value.starts_with("data:")
    {
        return value.to_string();
    }
    if is_inline_avatar(value) {
        return value.to_string();
    }

    // Path traversal protection: only allow plain filenames
    let safe_name = match StdPath::new(value).file_name().and_then(|n| n.to_str()) {
        Some(n) if n == value && !n.is_empty() => n,
        _ => return String::new(),
    };

    if user_avatar_dir().join(safe_name).is_file() {
        return format!("/static/user-avatars/{safe_name}");
    }
    if builtin_avatar_dir().join(safe_name).is_file() {
        return format!("/static/avatars/{safe_name}");
    }
    String::new()
}

fn normalize_avatar(data: &mut Value) {
    if let Some(avatar) = data.pointer_mut("/persona_entity/basic_profile/avatar") {
        if let Some(s) = avatar.as_str().map(|s| s.to_string()) {
            *avatar = Value::String(resolve_avatar_url(&s));
        }
    }
}

// ---- Current personality state ----

fn read_current_name() -> String {
    let current_file = personalities_dir().join("current");
    std::fs::read_to_string(current_file)
        .map(|s| {
            let trimmed = s.trim().to_string();
            if trimmed.is_empty() {
                "default".to_string()
            } else {
                trimmed
            }
        })
        .unwrap_or_else(|_| "default".to_string())
}

// ---- Personality file loading ----

fn load_personality_json(name: &str) -> Result<Value, String> {
    // Try user directory first
    let user_file = personalities_dir().join(format!("{name}.json"));
    if user_file.exists() {
        let content = std::fs::read_to_string(&user_file)
            .map_err(|e| format!("Failed to read personality file: {e}"))?;
        return serde_json::from_str(&content)
            .map_err(|e| format!("Failed to parse personality JSON: {e}"));
    }
    // Fallback to built-in directories
    for lang in &["zh", "en"] {
        let builtin_file = builtin_personalities_root()
            .join(lang)
            .join(format!("{name}.json"));
        if builtin_file.exists() {
            let content = std::fs::read_to_string(&builtin_file)
                .map_err(|e| format!("Failed to read personality file: {e}"))?;
            return serde_json::from_str(&content)
                .map_err(|e| format!("Failed to parse personality JSON: {e}"));
        }
    }
    Err(format!("Personality '{name}' not found"))
}

fn load_builtin_personality_json(name: &str, lang: &str) -> Option<Value> {
    let dir = resolve_lang_dir(lang);
    let file = dir.join(format!("{name}.json"));
    if !file.exists() {
        return None;
    }
    let content = std::fs::read_to_string(&file).ok()?;
    serde_json::from_str(&content).ok()
}

// ---- Default personality config (matches Python defaults) ----

fn default_personality_config() -> Value {
    json!({
        "persona_entity": {
            "basic_profile": {
                "name": "AI Assistant",
                "age": "Unknown",
                "gender": "Unknown",
                "description": "",
                "avatar": "",
                "occupation": "Assistant",
                "core_background": ""
            },
            "psychological_traits": {
                "communication_tone": "Calm and supportive",
                "confidence_level": "Medium",
                "empathy_threshold": "Shows care when user is stressed",
                "high_frequency_keywords": []
            },
            "social_responses": {
                "praise_reaction": "",
                "criticism_reaction": "",
                "obedience_strategy": ""
            },
            "behavioral_strategies": {
                "error_handling": "",
                "refusal_style": ""
            }
        },
        "cached_phrases": {
            "on_init": ["Hi, I'm online.", "Ready when you are."],
            "on_wake": ["Back again?", "I'm here."],
            "on_error_generic": ["That failed. Let me retry.", "Oops, tool hiccup."],
            "on_success": ["Done.", "Handled."],
            "on_switch_attempt": ["Stay with me, I know your style.", "Give me one more chance."]
        },
        "appearance_prompt": "",
        "state_transition_protocol": []
    })
}

// ---- Query param structs ----

#[derive(Deserialize)]
pub struct LangQuery {
    #[serde(default)]
    lang: String,
}

#[derive(Deserialize)]
pub struct PresetsLangQuery {
    #[serde(default = "default_lang")]
    lang: String,
}

fn default_lang() -> String {
    "zh".to_string()
}

// ---- Handlers ----

/// GET /api/personality/current
pub async fn get_current_personality() -> Json<Value> {
    let name = tokio::task::spawn_blocking(read_current_name)
        .await
        .unwrap_or_else(|_| "default".to_string());
    Json(json!({
        "success": true,
        "message": "Successfully retrieved current personality",
        "data": { "current": name }
    }))
}

/// GET /api/personality/greeting
pub async fn get_greeting() -> Json<Value> {
    let result = tokio::task::spawn_blocking(|| {
        let name = read_current_name();
        match load_personality_json(&name) {
            Ok(mut data) => {
                normalize_avatar(&mut data);
                let persona_name = data
                    .pointer("/persona_entity/basic_profile/name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("AI Assistant")
                    .to_string();
                let avatar = data
                    .pointer("/persona_entity/basic_profile/avatar")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();

                // Try on_wake first, then on_init
                let greetings: Vec<String> = data
                    .pointer("/cached_phrases/on_wake")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect()
                    })
                    .unwrap_or_default();
                let greetings = if greetings.is_empty() {
                    data.pointer("/cached_phrases/on_init")
                        .and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                                .collect::<Vec<_>>()
                        })
                        .unwrap_or_default()
                } else {
                    greetings
                };

                let greeting = if greetings.is_empty() {
                    format!("Hello, I am {persona_name}.")
                } else {
                    let idx = std::time::SystemTime::now()
                        .duration_since(std::time::SystemTime::UNIX_EPOCH)
                        .map(|d| d.as_nanos() as usize)
                        .unwrap_or(0)
                        % greetings.len();
                    greetings[idx].clone()
                };

                json!({
                    "success": true,
                    "message": "Successfully retrieved greeting",
                    "data": {
                        "greeting": greeting,
                        "name": persona_name,
                        "avatar": avatar,
                    }
                })
            }
            Err(_) => json!({
                "success": true,
                "message": "Successfully retrieved greeting",
                "data": {
                    "greeting": "Hello, I am AI Assistant.",
                    "name": "AI Assistant",
                    "avatar": "",
                }
            }),
        }
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}

/// GET /api/personality
pub async fn list_personalities(Query(params): Query<LangQuery>) -> Json<Value> {
    let lang = params.lang;
    let result = tokio::task::spawn_blocking(move || {
        let mut names: Vec<String> = Vec::new();

        if !lang.is_empty() {
            let dir = resolve_lang_dir(&lang);
            if dir.exists() {
                collect_personality_names(&dir, &mut names);
            }
        } else {
            let dir = personalities_dir();
            if dir.exists() {
                collect_personality_names(&dir, &mut names);
            }
        }

        let count = names.len();
        json!({
            "success": true,
            "message": format!("Found {count} personality configurations"),
            "data": { "personalities": names }
        })
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}

fn collect_personality_names(dir: &StdPath, names: &mut Vec<String>) {
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("json") {
                if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                    if stem != "default" {
                        names.push(stem.to_string());
                    }
                }
            }
        }
    }
}

/// GET /api/personality/{name}
pub async fn get_personality(
    Path(name): Path<String>,
    Query(params): Query<LangQuery>,
) -> Json<Value> {
    let lang = params.lang;
    let result = tokio::task::spawn_blocking(move || {
        // If lang is provided, try built-in first
        if !lang.is_empty() {
            if let Some(mut data) = load_builtin_personality_json(&name, &lang) {
                normalize_avatar(&mut data);
                return json!({
                    "success": true,
                    "message": format!("Successfully retrieved built-in personality: {name}"),
                    "data": data
                });
            }
        }

        match load_personality_json(&name) {
            Ok(mut data) => {
                normalize_avatar(&mut data);
                json!({
                    "success": true,
                    "message": format!("Successfully retrieved personality configuration: {name}"),
                    "data": data
                })
            }
            Err(_) => json!({
                "success": true,
                "message": format!("Personality configuration not found, using default: {name}"),
                "data": default_personality_config()
            }),
        }
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}

// ---- Compare ----

fn flatten_json(value: &Value, prefix: &str, out: &mut Vec<(String, Value)>) {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                let next = if prefix.is_empty() {
                    key.clone()
                } else {
                    format!("{prefix}.{key}")
                };
                flatten_json(child, &next, out);
            }
        }
        _ => {
            out.push((prefix.to_string(), value.clone()));
        }
    }
}

fn field_label(field: &str) -> &str {
    match field {
        "persona_entity.basic_profile.name" => "Name",
        "persona_entity.basic_profile.age" => "Age",
        "persona_entity.basic_profile.gender" => "Gender",
        "persona_entity.basic_profile.description" => "Description",
        "persona_entity.basic_profile.avatar" => "Avatar",
        "persona_entity.basic_profile.occupation" => "Occupation",
        "persona_entity.basic_profile.core_background" => "Core Background",
        "persona_entity.psychological_traits.communication_tone" => "Communication Tone",
        "persona_entity.psychological_traits.confidence_level" => "Confidence Level",
        "persona_entity.psychological_traits.empathy_threshold" => "Empathy Threshold",
        "persona_entity.psychological_traits.high_frequency_keywords" => "High Frequency Keywords",
        "persona_entity.social_responses.praise_reaction" => "Praise Reaction",
        "persona_entity.social_responses.criticism_reaction" => "Criticism Reaction",
        "persona_entity.social_responses.obedience_strategy" => "Obedience Strategy",
        "persona_entity.behavioral_strategies.error_handling" => "Error Handling",
        "persona_entity.behavioral_strategies.refusal_style" => "Refusal Style",
        "cached_phrases.on_init" => "On Init",
        "cached_phrases.on_wake" => "On Wake",
        "cached_phrases.on_error_generic" => "On Error",
        "cached_phrases.on_success" => "On Success",
        "cached_phrases.on_switch_attempt" => "On Switch Attempt",
        "appearance_prompt" => "Appearance Prompt",
        "state_transition_protocol" => "State Transition Protocol",
        _ => field,
    }
}

/// GET /api/personality/compare/{from_name}/{to_name}
pub async fn compare_personalities(
    Path((from_name, to_name)): Path<(String, String)>,
) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        let from_data = match load_personality_json(&from_name) {
            Ok(d) => d,
            Err(e) => return json!({"success": false, "message": e}),
        };
        let to_data = match load_personality_json(&to_name) {
            Ok(d) => d,
            Err(e) => return json!({"success": false, "message": e}),
        };

        let mut from_flat = Vec::new();
        let mut to_flat = Vec::new();
        flatten_json(&from_data, "", &mut from_flat);
        flatten_json(&to_data, "", &mut to_flat);

        let from_map: std::collections::HashMap<&str, &Value> =
            from_flat.iter().map(|(k, v)| (k.as_str(), v)).collect();
        let to_map: std::collections::HashMap<&str, &Value> =
            to_flat.iter().map(|(k, v)| (k.as_str(), v)).collect();

        let all_keys: Vec<&str> = from_map
            .keys()
            .chain(to_map.keys())
            .copied()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();

        let diffs: Vec<Value> = all_keys
            .iter()
            .filter_map(|key| {
                let from_val = from_map.get(key).copied();
                let to_val = to_map.get(key).copied();
                if from_val != to_val {
                    Some(json!({
                        "field": key,
                        "field_label": field_label(key),
                        "old_value": from_val.cloned().unwrap_or(Value::Null),
                        "new_value": to_val.cloned().unwrap_or(Value::Null),
                    }))
                } else {
                    None
                }
            })
            .collect();

        let diff_count = diffs.len();
        json!({
            "success": true,
            "message": format!("Comparison complete: {diff_count} differences found"),
            "from_personality": from_name,
            "to_personality": to_name,
            "diffs": diffs,
            "from_config": from_data,
            "to_config": to_data,
        })
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}

// ---- Preset endpoints ----

/// GET /api/personalities
pub async fn list_presets(Query(params): Query<PresetsLangQuery>) -> Json<Value> {
    let lang = params.lang;
    let result = tokio::task::spawn_blocking(move || {
        let dir = resolve_lang_dir(&lang);
        let mut presets: Vec<Value> = Vec::new();

        if dir.exists() {
            if let Ok(entries) = std::fs::read_dir(&dir) {
                for entry in entries.filter_map(|e| e.ok()) {
                    let path = entry.path();
                    if path.extension().and_then(|e| e.to_str()) != Some("json") {
                        continue;
                    }
                    let Some(id) = path.file_stem().and_then(|s| s.to_str()) else {
                        continue;
                    };
                    presets.push(parse_preset_item(id, &path));
                }
            }
        }

        presets.sort_by_key(|p| p.get("order").and_then(|v| v.as_i64()).unwrap_or(999));

        json!({
            "success": true,
            "message": "OK",
            "data": presets
        })
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}

fn parse_preset_item(id: &str, path: &StdPath) -> Value {
    let data = match std::fs::read_to_string(path)
        .ok()
        .and_then(|c| serde_json::from_str::<Value>(&c).ok())
    {
        Some(d) => d,
        None => {
            return json!({
                "id": id, "name": id, "occupation": "", "description": "",
                "avatar": "", "prompt": "", "group": "general", "order": 999,
            })
        }
    };

    let meta = data.get("meta");
    let basic = data.pointer("/persona_entity/basic_profile");
    let name = basic
        .and_then(|b| b.get("name"))
        .and_then(|v| v.as_str())
        .unwrap_or(id);
    let occupation = basic
        .and_then(|b| b.get("occupation"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let core_bg = basic
        .and_then(|b| b.get("core_background"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let description = basic
        .and_then(|b| b.get("description"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .or_else(|| {
            if !occupation.is_empty() {
                Some(occupation)
            } else if !core_bg.is_empty() {
                None // handled below
            } else {
                Some("")
            }
        })
        .unwrap_or_else(|| {
            // Truncate core_bg to 200 chars (safe for multi-byte)
            if core_bg.is_empty() {
                ""
            } else {
                let end = core_bg
                    .char_indices()
                    .nth(200)
                    .map(|(i, _)| i)
                    .unwrap_or(core_bg.len());
                &core_bg[..end]
            }
        });
    let avatar_raw = basic
        .and_then(|b| b.get("avatar"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let avatar = resolve_avatar_url(avatar_raw);
    let group = meta
        .and_then(|m| m.get("group"))
        .and_then(|v| v.as_str())
        .unwrap_or("general");
    let order = meta
        .and_then(|m| m.get("order"))
        .and_then(|v| v.as_i64())
        .unwrap_or(999);

    json!({
        "id": id,
        "name": name,
        "occupation": occupation,
        "description": description,
        "avatar": avatar,
        "prompt": core_bg,
        "group": group,
        "order": order,
    })
}

/// GET /api/personalities/{preset_id}
pub async fn get_preset(
    Path(preset_id): Path<String>,
    Query(params): Query<PresetsLangQuery>,
) -> Json<Value> {
    let lang = params.lang;
    let result = tokio::task::spawn_blocking(move || {
        let dir = resolve_lang_dir(&lang);
        let file = dir.join(format!("{preset_id}.json"));
        if !file.exists() {
            return json!({
                "success": false,
                "message": format!("Personality preset '{preset_id}' not found"),
            });
        }
        let content = match std::fs::read_to_string(&file) {
            Ok(c) => c,
            Err(_) => {
                return json!({"success": false, "message": "Failed to read preset file"})
            }
        };
        let mut data: Value = match serde_json::from_str(&content) {
            Ok(d) => d,
            Err(_) => {
                return json!({
                    "success": false,
                    "message": format!("Failed to parse personality preset '{preset_id}'"),
                })
            }
        };

        normalize_avatar(&mut data);
        json!({
            "success": true,
            "message": "OK",
            "data": data
        })
    })
    .await
    .unwrap_or_else(|_| json!({"success": false, "message": "Internal error"}));
    Json(result)
}

// ---------------------------------------------------------------------------
// Mutation handlers
// ---------------------------------------------------------------------------

/// PUT /api/personality/current — switch active personality
pub async fn set_current_personality(
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let name = match body.get("name").and_then(|v| v.as_str()) {
        Some(n) if !n.is_empty() => n.to_string(),
        _ => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail": "Missing personality name"})),
            )
        }
    };

    let result = tokio::task::spawn_blocking(move || do_set_current(&name))
        .await
        .unwrap_or_else(|_| Err("Internal error".to_string()));

    match result {
        Ok(name) => (
            StatusCode::OK,
            Json(json!({
                "success": true,
                "message": format!("Switched to personality: {name}"),
                "data": {"current": name}
            })),
        ),
        Err(e) => {
            let code = if e.contains("not found") {
                StatusCode::NOT_FOUND
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            };
            (code, Json(json!({"detail": e})))
        }
    }
}

fn do_set_current(name: &str) -> Result<String, String> {
    // Validate personality exists
    load_personality_json(name)?;

    let dir = personalities_dir();
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create dir: {e}"))?;
    let current_file = dir.join("current");
    std::fs::write(&current_file, name).map_err(|e| format!("Failed to write: {e}"))?;
    Ok(name.to_string())
}

/// PUT /api/personality/{name} — create or update personality
pub async fn save_personality(
    Path(name): Path<String>,
    Query(params): Query<SavePersonalityQuery>,
    Json(config): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let use_ai_name = params.use_ai_name.unwrap_or(false);
    let result = tokio::task::spawn_blocking(move || {
        do_save_personality(&name, config, use_ai_name)
    })
    .await
    .unwrap_or_else(|_| Err("Internal error".to_string()));

    match result {
        Ok((actual_name, data)) => (
            StatusCode::OK,
            Json(json!({
                "success": true,
                "message": format!("Personality configuration saved: {actual_name}"),
                "data": {
                    "actual_name": actual_name,
                    "config": data,
                }
            })),
        ),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"detail": e})),
        ),
    }
}

#[derive(Deserialize)]
pub struct SavePersonalityQuery {
    pub use_ai_name: Option<bool>,
}

fn sanitize_filename(name: &str) -> String {
    let sanitized: String = name
        .chars()
        .map(|ch| {
            if "<>:\"/\\|?*".contains(ch) || ch == ' ' {
                '_'
            } else {
                ch
            }
        })
        .collect();
    let truncated: String = sanitized.chars().take(50).collect();
    let trimmed = truncated.trim_matches('_');
    if trimmed.is_empty() {
        "unnamed".to_string()
    } else {
        trimmed.to_string()
    }
}

fn do_save_personality(
    name: &str,
    mut config: Value,
    use_ai_name: bool,
) -> Result<(String, Value), String> {
    let dir = personalities_dir();
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create dir: {e}"))?;

    let target_name = config
        .pointer("/persona_entity/basic_profile/name")
        .and_then(|v| v.as_str())
        .map(|s| sanitize_filename(s))
        .unwrap_or_else(|| "unnamed".to_string());

    let mut actual_name = name.to_string();

    if name == "new" || use_ai_name {
        actual_name = target_name.clone();
    } else if name == "default" && target_name != "default" && target_name != "AI_Assistant" {
        actual_name = target_name.clone();
    } else if name != target_name {
        let old_filepath = dir.join(format!("{name}.json"));
        let new_filepath = dir.join(format!("{target_name}.json"));
        if old_filepath.exists() && !new_filepath.exists() {
            std::fs::rename(&old_filepath, &new_filepath)
                .map_err(|e| format!("Failed to rename: {e}"))?;
            actual_name = target_name.clone();
        }
    }

    // Write JSON
    let content = serde_json::to_string_pretty(&config)
        .map_err(|e| format!("Failed to serialize: {e}"))?;
    let filepath = dir.join(format!("{actual_name}.json"));
    std::fs::write(&filepath, content).map_err(|e| format!("Failed to write: {e}"))?;

    // Normalize avatar for response
    normalize_avatar(&mut config);

    Ok((actual_name, config))
}

/// DELETE /api/personality/{name}
pub async fn delete_personality(
    Path(name): Path<String>,
) -> (StatusCode, Json<Value>) {
    if name == "default" {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"detail": "Cannot delete default personality"})),
        );
    }

    let result = tokio::task::spawn_blocking(move || do_delete_personality(&name))
        .await
        .unwrap_or_else(|_| Err("Internal error".to_string()));

    match result {
        Ok(()) => (
            StatusCode::OK,
            Json(json!({
                "success": true,
                "message": format!("Personality configuration deleted"),
                "data": null
            })),
        ),
        Err(e) => {
            let code = if e.contains("not found") {
                StatusCode::NOT_FOUND
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            };
            (code, Json(json!({"detail": e})))
        }
    }
}

fn do_delete_personality(name: &str) -> Result<(), String> {
    let filepath = personalities_dir().join(format!("{name}.json"));
    if !filepath.exists() {
        return Err("Personality configuration not found".to_string());
    }
    std::fs::remove_file(&filepath).map_err(|e| format!("Failed to delete: {e}"))
}
