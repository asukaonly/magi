//! Compose the public gateway contract from Python schemas and native ownership.

use axum::{
    extract::{Request, State},
    http::StatusCode,
    response::{Html, IntoResponse, Response},
    Json,
};
use serde_json::{json, Value};

use super::{proxy, security, state::ApiState};

const MANIFEST: &str = include_str!("../../../../contracts/api/gateway_routes.json");
const NATIVE_SCHEMA: &str = include_str!("../../../../contracts/api/gateway_openapi.json");
const RELEASE_VERSION: &str = include_str!("../../../../VERSION");
const MAX_SCHEMA_BYTES: usize = 16 * 1024 * 1024;
const DESCRIPTION: &str = "Magi Server gateway API (native Rust and Python IPC routes). All requests require an opaque access token in x-magi-session-token except public liveness/bundled avatars and the separately authenticated pairing/device-credential exchanges. Authentication is enabled in development too. Paired owner devices share full control of one owner's data; this is not multi-tenant authorization. Collector credentials have a narrower source scope. Never send credentials in URLs. Browser Origin access is restricted to configured desktop origins; non-browser HTTP clients can omit Origin. See server/README.md for pairing, reconnect, and mutation recovery. Dynamic JSON responses intentionally retain open schemas; route coverage does not imply every domain response is strongly typed.";

pub async fn schema(State(state): State<ApiState>, request: Request) -> Response {
    match read_combined(state, request).await {
        Ok(schema) => Json(schema).into_response(),
        Err(response) => response,
    }
}

pub async fn docs(State(state): State<ApiState>, request: Request) -> Response {
    let schema = match read_combined(state, request).await {
        Ok(schema) => schema,
        Err(response) => return response,
    };
    // Embed the contract, never the caller's credential. Avoid an unauthenticated
    // second schema fetch, and prevent documentation strings closing the script.
    let serialized = schema
        .to_string()
        .replace('<', "\\u003c")
        .replace('\u{2028}', "\\u2028")
        .replace('\u{2029}', "\\u2029");
    Html(format!(r#"<!doctype html><html><head><meta charset="utf-8"><title>Magi Server API</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head><body><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({{spec:{serialized},dom_id:'#swagger-ui',persistAuthorization:false}});</script></body></html>"#)).into_response()
}

async fn read_combined(state: ApiState, mut request: Request) -> Result<Value, Response> {
    *request.uri_mut() = "/api/openapi.json".parse().expect("static schema URI");
    let response = proxy::proxy_handler(State(state), request)
        .await
        .into_response();
    if !response.status().is_success() {
        return Err(response);
    }
    let bytes = axum::body::to_bytes(response.into_body(), MAX_SCHEMA_BYTES)
        .await
        .map_err(|_| schema_error())?;
    let python: Value = serde_json::from_slice(&bytes).map_err(|_| schema_error())?;
    combine(python).map_err(|_| schema_error())
}

fn schema_error() -> Response {
    (StatusCode::BAD_GATEWAY, Json(json!({"success":false,"error_code":"OPENAPI_UNAVAILABLE","message":"The complete API schema is unavailable"}))).into_response()
}

fn listed(policy: &Value, list: &str, path: &str) -> bool {
    policy[list]
        .as_array()
        .is_some_and(|items| items.iter().any(|item| item == path))
}

fn below(policy: &Value, list: &str, path: &str) -> bool {
    policy[list].as_array().is_some_and(|prefixes| {
        prefixes.iter().any(|prefix| {
            prefix
                .as_str()
                .is_some_and(|prefix| path.starts_with(&format!("{prefix}/")))
        })
    })
}

fn combine(mut python: Value) -> Result<Value, &'static str> {
    let manifest: Value = serde_json::from_str(MANIFEST).expect("gateway route manifest");
    let native: Value = serde_json::from_str(NATIVE_SCHEMA).expect("native OpenAPI contract");
    if !python["openapi"]
        .as_str()
        .is_some_and(|value| value.starts_with("3."))
    {
        return Err("invalid Python OpenAPI version");
    }
    let paths = python["paths"]
        .as_object_mut()
        .ok_or("missing Python paths")?;
    for route in manifest["native_routes"]
        .as_array()
        .ok_or("missing native routes")?
    {
        let path = route["path"].as_str().ok_or("invalid route path")?;
        for method in route["methods"].as_array().ok_or("invalid methods")? {
            let method = method.as_str().ok_or("invalid method")?.to_lowercase();
            if let Some(operation) = native["paths"][path].get(&method) {
                paths.entry(path).or_insert_with(|| json!({}))[&method] = operation.clone();
            }
            let operation = paths
                .get_mut(path)
                .and_then(|item| item.get_mut(&method))
                .ok_or("native operation has no contract")?;
            operation["x-magi-owner"] = route["owner"].clone();
            operation["x-magi-response-envelope"] = route["response_envelope"].clone();
        }
    }
    let policy = &manifest["access_policy"];
    // Static mounts are real gateway surfaces; wildcard paths denote nested assets.
    for mount in manifest["static_mounts"]
        .as_array()
        .ok_or("missing mounts")?
    {
        let path = mount["path"].as_str().ok_or("invalid mount")?;
        paths.insert(format!("{path}/{{asset_path}}"), json!({"get":{
            "summary":"Read avatar asset", "tags":["Gateway"],
            "parameters":[{"name":"asset_path","in":"path","required":true,"schema":{"type":"string"},"description":"Relative asset path, possibly containing subdirectories."}],
            "responses":{"200":{"description":"Asset content","content":{"*/*":{"schema":{"type":"string","format":"binary"}}}},"404":{"description":"Asset not found"}}
        }}));
    }
    for (path, item) in paths.iter_mut() {
        for (method, operation) in item.as_object_mut().ok_or("invalid path item")? {
            if !matches!(
                method.as_str(),
                "get" | "post" | "put" | "patch" | "delete" | "head" | "options"
            ) {
                continue;
            }
            let access = if listed(policy, "public_native_routes", path)
                || below(policy, "public_static_mounts", path)
            {
                json!([])
            } else if listed(policy, "pairing_exchange_routes", path) {
                json!([{"MagiPairingGrant":[]}])
            } else if listed(policy, "credential_exchange_routes", path) {
                json!([{"MagiDeviceCredential":[]}])
            } else if listed(policy, "ticket_native_routes", path)
                || below(policy, "ticket_proxied_prefixes", path)
                || below(policy, "ticket_static_mounts", path)
            {
                json!([{"MagiSession":[]},{"MagiResourceTicket":[]}])
            } else {
                json!([{"MagiSession":[]}])
            };
            operation["security"] = access;
            let responses = operation["responses"]
                .as_object_mut()
                .ok_or("missing responses")?;
            responses.entry("401").or_insert_with(|| json!({"description":"Missing, expired, or revoked credential for this operation."}));
            responses.entry("403").or_insert_with(
                || json!({"description":"Browser origin or collector scope denied."}),
            );
            responses.entry("503").or_insert_with(|| json!({"description":"Runtime unavailable, maintenance, or IPC_BUSY. IPC_BUSY includes admitted:false; back off before retrying."}));
            responses.entry("504").or_insert_with(|| json!({"description":"IPC_READ_TIMEOUT for reads; IPC_OUTCOME_UNKNOWN for mutations. The mutation may still finish; inspect its receipt/state before retrying. A timeout is not rollback."}));
        }
    }
    python["info"] = json!({"title":"Magi Server API","version":RELEASE_VERSION.trim(),"description":DESCRIPTION});
    python["servers"] = json!([{"url":"/","description":"The authenticated gateway origin"}]);
    python["security"] = json!([{"MagiSession":[]}]);
    if !python["components"].is_object() {
        python["components"] = json!({});
    }
    if !python["components"]["schemas"].is_object() {
        python["components"]["schemas"] = json!({});
    }
    for (name, schema) in native["components"]["schemas"]
        .as_object()
        .ok_or("missing native schemas")?
    {
        if python["components"]["schemas"].get(name).is_some() {
            return Err("schema name collision");
        }
        python["components"]["schemas"][name] = schema.clone();
    }
    let mut schemes = json!({});
    for (name, description) in [
        ("MagiSession", "Opaque access_token returned by /api/auth/session (15-minute lifetime), or the process-local owner session credential."),
        ("MagiPairingGrant", "Single-use opaque pairing_token, valid for 30 minutes; only for /api/auth/pair."),
        ("MagiDeviceCredential", "Persisted opaque client_credential; only for /api/auth/session. Revocation requires pairing again."),
    ] { schemes[name] = json!({"type":"apiKey","in":"header","name":security::SESSION_TOKEN_HEADER,"description":description}); }
    schemes["MagiResourceTicket"] = json!({"type":"apiKey","in":"query","name":security::RESOURCE_TICKET_QUERY,"description":"Short-lived path/query-bound resource ticket, issued by /api/private-resource-tickets. Never substitute a session token."});
    python["components"]["securitySchemes"] = schemes;
    Ok(python)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn python_fixture() -> Value {
        let manifest: Value = serde_json::from_str(MANIFEST).unwrap();
        let mut paths =
            json!({"/api/config/":{"get":{"responses":{"200":{"description":"Python config"}}}}});
        for route in manifest["native_routes"].as_array().unwrap() {
            if route.get("python_parity").is_some() {
                for method in route["methods"].as_array().unwrap() {
                    paths[route["path"].as_str().unwrap()]
                        [method.as_str().unwrap().to_lowercase()] =
                        json!({"responses":{"200":{"description":"Python operation"}}});
                }
            }
        }
        json!({"openapi":"3.1.0","paths":paths})
    }

    #[test]
    fn native_contract_covers_manifest_and_applies_real_security() {
        let mut python = python_fixture();
        python["paths"]["/api/config/"]["get"]["security"] = json!([]);
        let combined = combine(python).unwrap();
        let manifest: Value = serde_json::from_str(MANIFEST).unwrap();
        let native: Value = serde_json::from_str(NATIVE_SCHEMA).unwrap();
        for (path, item) in native["paths"].as_object().unwrap() {
            let route = manifest["native_routes"]
                .as_array()
                .unwrap()
                .iter()
                .find(|route| route["path"] == *path)
                .expect("overlay must have a registered native route");
            for method in item.as_object().unwrap().keys() {
                assert!(route["methods"].as_array().unwrap().iter().any(|m| m
                    .as_str()
                    .unwrap()
                    .to_lowercase()
                    == *method));
            }
        }
        for route in manifest["native_routes"].as_array().unwrap() {
            for method in route["methods"].as_array().unwrap() {
                assert!(combined["paths"][route["path"].as_str().unwrap()]
                    .get(method.as_str().unwrap().to_lowercase())
                    .is_some());
            }
        }
        assert_eq!(combined["info"]["version"], RELEASE_VERSION.trim());
        assert_eq!(
            combined["paths"]["/api/health"]["get"]["security"],
            json!([])
        );
        assert_eq!(
            combined["paths"]["/api/auth/pair"]["post"]["security"],
            json!([{"MagiPairingGrant":[]}])
        );
        assert_eq!(
            combined["paths"]["/api/auth/session"]["post"]["security"],
            json!([{"MagiDeviceCredential":[]}])
        );
        assert_eq!(
            combined["paths"]["/api/config/"]["get"]["security"],
            json!([{"MagiSession":[]}])
        );
        assert_eq!(
            combined["components"]["securitySchemes"]["MagiSession"]["name"],
            security::SESSION_TOKEN_HEADER
        );
        assert!(
            combined["paths"]["/api/memory/clear"]["delete"]["responses"]
                .get("200")
                .is_none()
        );
        assert!(
            combined["paths"]["/api/memory/clear"]["delete"]["responses"]
                .get("202")
                .is_some()
        );
    }

    #[test]
    fn incomplete_python_schema_fails_instead_of_publishing_partial_contract() {
        assert!(combine(json!({"openapi":"3.1.0","paths":{}})).is_err());
    }
}
