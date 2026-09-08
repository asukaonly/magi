use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::auth::AuthStore;
use axum::extract::Request;
use axum::http::header::{
    ACCEPT, ACCEPT_LANGUAGE, CACHE_CONTROL, CONTENT_TYPE, ORIGIN, RANGE, REFERRER_POLICY,
};
use axum::http::{HeaderName, HeaderValue, Method, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use form_urlencoded;
use tokio::sync::Semaphore;
use tower_http::cors::{AllowOrigin, CorsLayer};
use uuid::Uuid;

pub const SESSION_TOKEN_HEADER: &str = "x-magi-session-token";
pub const RESOURCE_TICKET_QUERY: &str = "resource_ticket";

const DEFAULT_RESOURCE_TICKET_TTL: Duration = Duration::from_secs(60);
const DEFAULT_RESOURCE_TICKET_CAPACITY: usize = 4096;
const ALLOWED_DESKTOP_ORIGINS: [&str; 4] = [
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
];

#[derive(Clone)]
pub struct GatewaySecurity {
    pub auth: Arc<AuthStore>,
    pub auth_operations: Arc<Semaphore>,
    allowed_origins: Arc<[HeaderValue]>,
    resource_tickets: ResourceTicketStore,
}

#[derive(Clone)]
struct ResourceTicketStore {
    entries: Arc<Mutex<HashMap<String, ResourceTicketRecord>>>,
    ttl: Duration,
    capacity: usize,
}

#[derive(Clone)]
struct ResourceTicketRecord {
    path: String,
    client_id: String,
    expires_at: Instant,
}

pub struct ResourceTicketGrant {
    pub access_path: String,
    pub expires_at_ms: u64,
}

impl GatewaySecurity {
    pub fn new(session_token: impl Into<String>) -> Self {
        Self::with_policy(
            session_token,
            ALLOWED_DESKTOP_ORIGINS,
            DEFAULT_RESOURCE_TICKET_TTL,
            DEFAULT_RESOURCE_TICKET_CAPACITY,
        )
    }

    pub fn with_policy<const N: usize>(
        session_token: impl Into<String>,
        allowed_origins: [&str; N],
        resource_ticket_ttl: Duration,
        resource_ticket_capacity: usize,
    ) -> Self {
        let token = session_token.into();
        let token = token.trim();
        assert!(!token.is_empty(), "desktop session token must not be empty");
        Self::from_parts(
            Arc::new(AuthStore::local(token)),
            allowed_origins,
            resource_ticket_ttl,
            resource_ticket_capacity,
        )
    }

    fn from_parts<const N: usize>(
        auth: Arc<AuthStore>,
        allowed_origins: [&str; N],
        resource_ticket_ttl: Duration,
        resource_ticket_capacity: usize,
    ) -> Self {
        let origins = allowed_origins
            .into_iter()
            .map(|origin| {
                HeaderValue::from_str(origin).expect("desktop origin must be a valid header value")
            })
            .collect::<Vec<_>>();
        Self {
            auth,
            auth_operations: Arc::new(Semaphore::new(8)),
            allowed_origins: Arc::from(origins),
            resource_tickets: ResourceTicketStore {
                entries: Arc::new(Mutex::new(HashMap::new())),
                ttl: resource_ticket_ttl,
                capacity: resource_ticket_capacity.max(1),
            },
        }
    }

    pub fn with_auth(auth: Arc<AuthStore>) -> Self {
        Self::from_parts(
            auth,
            ALLOWED_DESKTOP_ORIGINS,
            DEFAULT_RESOURCE_TICKET_TTL,
            DEFAULT_RESOURCE_TICKET_CAPACITY,
        )
    }

    pub fn cors_layer(&self) -> CorsLayer {
        CorsLayer::new()
            .allow_origin(AllowOrigin::list(self.allowed_origins.iter().cloned()))
            .allow_methods([
                Method::GET,
                Method::HEAD,
                Method::POST,
                Method::PUT,
                Method::PATCH,
                Method::DELETE,
                Method::OPTIONS,
            ])
            .allow_headers([
                ACCEPT,
                ACCEPT_LANGUAGE,
                CONTENT_TYPE,
                RANGE,
                HeaderName::from_static(SESSION_TOKEN_HEADER),
                HeaderName::from_static("last-event-id"),
                HeaderName::from_static("x-magi-full-clear-transaction"),
            ])
            .max_age(Duration::from_secs(600))
    }

    pub fn invalidate_resource_tickets(&self) {
        self.resource_tickets
            .entries
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clear();
    }

    pub fn issue_resource_ticket(&self, path: String, client_id: String) -> ResourceTicketGrant {
        self.resource_tickets.issue(path, client_id)
    }

    fn origin_is_allowed(&self, request: &Request) -> bool {
        let Some(origin) = request.headers().get(ORIGIN) else {
            return true;
        };
        self.allowed_origins
            .iter()
            .any(|allowed| allowed.as_bytes() == origin.as_bytes())
    }

    fn has_valid_resource_ticket(&self, request: &Request) -> bool {
        if request.method() != Method::GET && request.method() != Method::HEAD {
            return false;
        }
        if !is_private_resource_path(request.uri().path()) {
            return false;
        }
        let Some((ticket, target)) =
            resource_ticket_and_target(request.uri().path(), request.uri().query())
        else {
            return false;
        };
        self.resource_tickets
            .client(&ticket, &target)
            .is_some_and(|id| self.auth.client_is_active(&id))
    }
}

impl ResourceTicketStore {
    fn issue(&self, target: String, client_id: String) -> ResourceTicketGrant {
        let now = Instant::now();
        let expires_at = now + self.ttl;
        let ticket = Uuid::new_v4().simple().to_string();

        let mut entries = self
            .entries
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        entries.retain(|_, record| record.expires_at > now);
        if entries.len() >= self.capacity {
            if let Some(oldest) = entries
                .iter()
                .min_by_key(|(_, record)| record.expires_at)
                .map(|(key, _)| key.clone())
            {
                entries.remove(&oldest);
            }
        }
        entries.insert(
            ticket.clone(),
            ResourceTicketRecord {
                path: target.clone(),
                client_id,
                expires_at,
            },
        );
        drop(entries);

        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_millis() as u64)
            .unwrap_or_default();
        ResourceTicketGrant {
            access_path: format!(
                "{target}{}{RESOURCE_TICKET_QUERY}={ticket}",
                if target.contains('?') { '&' } else { '?' }
            ),
            expires_at_ms: now_ms.saturating_add(self.ttl.as_millis() as u64),
        }
    }

    fn client(&self, ticket: &str, request_path: &str) -> Option<String> {
        let now = Instant::now();
        let mut entries = self
            .entries
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        entries.retain(|_, record| record.expires_at > now);
        entries
            .get(ticket)
            .filter(|record| record.path == request_path)
            .map(|record| record.client_id.clone())
    }
}

#[derive(Clone)]
pub struct AuthenticatedClient {
    pub client_id: String,
}

#[derive(Clone)]
pub struct PairingCredential(pub String);

pub fn generate_session_token() -> String {
    format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple())
}

pub async fn enforce_gateway_access(
    security: Arc<GatewaySecurity>,
    mut request: Request,
    next: Next,
) -> Response {
    if !security.origin_is_allowed(&request) {
        return error_response(
            StatusCode::FORBIDDEN,
            "Request origin is not allowed",
            "origin_not_allowed",
        );
    }

    if request.method() == Method::OPTIONS {
        return next.run(request).await;
    }

    let path = request.uri().path();
    let public = is_public_request(request.method(), path);
    let private_resource = is_private_resource_path(path);
    let resource_ticket = private_resource && security.has_valid_resource_ticket(&request);
    if !public && !resource_ticket {
        let token = request
            .headers()
            .get(SESSION_TOKEN_HEADER)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_owned();
        if request.method() == Method::POST && path == "/api/auth/pair" {
            if !security.auth.validates_pairing_grant(&token) {
                return error_response(
                    StatusCode::UNAUTHORIZED,
                    "Pairing grant is invalid or expired",
                    "invalid_pairing_grant",
                );
            }
            request.extensions_mut().insert(PairingCredential(token));
        } else if request.method() == Method::POST && path == "/api/auth/session" {
            let Ok(permit) = Arc::clone(&security.auth_operations).try_acquire_owned() else {
                return error_response(
                    StatusCode::TOO_MANY_REQUESTS,
                    "Authentication is busy",
                    "auth_busy",
                );
            };
            let auth = Arc::clone(&security.auth);
            let result = tokio::task::spawn_blocking(move || {
                let _permit = permit;
                auth.renew(&token)
            })
            .await;
            match result {
                Ok(Ok(session)) => {
                    request.extensions_mut().insert(session);
                }
                _ => {
                    return error_response(
                        StatusCode::UNAUTHORIZED,
                        "Client credential is invalid or revoked",
                        "invalid_client_credential",
                    )
                }
            }
        } else if let Some(client_id) = security.auth.authenticate(&token) {
            request
                .extensions_mut()
                .insert(AuthenticatedClient { client_id });
        } else {
            return error_response(
                StatusCode::UNAUTHORIZED,
                "Client authentication is required",
                "client_auth_required",
            );
        }
    }

    let mut response = next.run(request).await;
    if !public {
        response
            .headers_mut()
            .insert(CACHE_CONTROL, HeaderValue::from_static("private, no-store"));
    }
    if private_resource {
        let headers = response.headers_mut();
        headers.insert(CACHE_CONTROL, HeaderValue::from_static("private, no-store"));
        headers.insert(REFERRER_POLICY, HeaderValue::from_static("no-referrer"));
        headers.insert(
            HeaderName::from_static("x-content-type-options"),
            HeaderValue::from_static("nosniff"),
        );
        headers.insert(
            HeaderName::from_static("content-security-policy"),
            HeaderValue::from_static("sandbox; default-src 'none'"),
        );
    }
    response
}

fn is_public_request(method: &Method, path: &str) -> bool {
    (method == Method::GET || method == Method::HEAD)
        && (path == "/api/health"
            || path == "/static/avatars"
            || path.starts_with("/static/avatars/"))
}

fn is_private_resource_path(path: &str) -> bool {
    path == "/static/user-avatars"
        || path.starts_with("/static/user-avatars/")
        || path.starts_with("/api/timeline/asset/")
        || (path.starts_with("/api/messages/session/")
            && path.contains("/attachments/")
            && path.ends_with("/content"))
}

fn resource_ticket_and_target(path: &str, query: Option<&str>) -> Option<(String, String)> {
    let mut ticket = None;
    let mut target_query = form_urlencoded::Serializer::new(String::new());
    for (key, value) in form_urlencoded::parse(query?.as_bytes()) {
        if key == RESOURCE_TICKET_QUERY {
            if value.is_empty() || ticket.replace(value.into_owned()).is_some() {
                return None;
            }
        } else {
            target_query.append_pair(&key, &value);
        }
    }
    let ticket = ticket?;
    let target_query = target_query.finish();
    let target = if target_query.is_empty() {
        path.to_string()
    } else {
        format!("{path}?{target_query}")
    };
    Some((ticket, target))
}

fn error_response(status: StatusCode, message: &str, error_code: &str) -> Response {
    (
        status,
        axum::Json(serde_json::json!({
            "success": false,
            "message": message,
            "error_code": error_code,
        })),
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use super::{resource_ticket_and_target, GatewaySecurity};
    use std::time::Duration;

    #[test]
    fn resource_ticket_is_scoped_reusable_and_expires() {
        let security = GatewaySecurity::with_policy(
            "test-token",
            ["tauri://localhost"],
            Duration::from_millis(15),
            4,
        );
        let grant = security
            .issue_resource_ticket("/private/a".to_string(), crate::auth::LOCAL_OWNER.into());
        let (ticket, target) = resource_ticket_and_target(
            "/private/a",
            grant.access_path.split_once('?').map(|value| value.1),
        )
        .expect("ticket");

        assert_eq!(target, "/private/a");
        assert!(security.resource_tickets.client(&ticket, &target).is_some());
        assert!(security.resource_tickets.client(&ticket, &target).is_some());
        assert!(!security
            .resource_tickets
            .client(&ticket, "/private/b")
            .is_some());
        std::thread::sleep(Duration::from_millis(20));
        assert!(!security.resource_tickets.client(&ticket, &target).is_some());
    }

    #[test]
    fn resource_ticket_query_preserves_bound_parameters_and_rejects_duplicates() {
        assert_eq!(
            resource_ticket_and_target(
                "/private/a",
                Some("user_id=local_user&resource_ticket=abc")
            ),
            Some((
                "abc".to_string(),
                "/private/a?user_id=local_user".to_string()
            ))
        );
        assert!(resource_ticket_and_target(
            "/private/a",
            Some("resource_ticket=abc&resource_ticket=other")
        )
        .is_none());
        assert!(resource_ticket_and_target("/private/a", Some("other=abc")).is_none());
    }
}
