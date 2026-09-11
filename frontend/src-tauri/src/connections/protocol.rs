use std::time::Duration;

use reqwest::{Client, Method};
use serde::{de::DeserializeOwned, Deserialize};
use serde_json::{json, Value};
use url::Url;

const TOKEN_HEADER: &str = "x-magi-session-token";
const MAX_RESPONSE_BYTES: usize = 256 * 1024;

#[derive(Deserialize)]
pub struct ClientGrant {
    pub server_id: String,
    pub client_id: String,
    pub client_credential: String,
}

#[derive(Clone, Deserialize, serde::Serialize)]
pub struct AccessSession {
    pub server_id: String,
    pub client_id: String,
    pub access_token: String,
    pub expires_at_ms: i64,
}

#[derive(Deserialize)]
pub struct ServerInfo {
    pub server_id: String,
    pub protocol_version: u32,
    pub service_ready: bool,
    pub maintenance: MaintenanceInfo,
}

#[derive(Deserialize)]
pub struct MaintenanceInfo {
    pub data_epoch: String,
    pub content_epoch: String,
    pub phase: String,
}

#[derive(Deserialize)]
struct Envelope<T> {
    success: bool,
    data: T,
}

pub fn normalize_remote_url(raw: &str) -> Result<String, String> {
    let mut url = Url::parse(raw.trim()).map_err(|_| "Enter a valid center address")?;
    // Pin the same-machine alias to the gateway's literal bind address, without DNS.
    if url.scheme() == "http" && url.host_str() == Some("localhost") {
        url.set_host(Some("127.0.0.1"))
            .map_err(|_| "Invalid loopback center address")?;
    }
    let loopback_http = url.scheme() == "http" && url.host_str() == Some("127.0.0.1");
    if (url.scheme() != "https" && !loopback_http)
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || !matches!(url.path(), "" | "/" | "/api" | "/api/")
    {
        return Err(
            "Center address must use HTTPS or HTTP on 127.0.0.1/localhost, with no credentials, query or extra path".into(),
        );
    }
    Ok(format!("{}/api", url.origin().ascii_serialization()))
}

pub struct CenterClient {
    http: Client,
    base_url: String,
}

impl CenterClient {
    pub fn local(base_url: &str) -> Result<Self, String> {
        initialize_tls();
        let url = Url::parse(base_url).map_err(|_| "Invalid local service address")?;
        if url.scheme() != "http"
            || url.host_str() != Some("127.0.0.1")
            || url.port().is_none()
            || url.path() != "/api"
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err("Invalid local service address".into());
        }
        let http = Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(|_| "Could not initialize local service connection")?;
        Ok(Self {
            http,
            base_url: base_url.into(),
        })
    }

    pub fn remote(base_url: &str) -> Result<Self, String> {
        initialize_tls();
        let base_url = normalize_remote_url(base_url)?;
        let builder = Client::builder();
        let builder = if base_url.starts_with("http://") {
            // A loopback credential must never be sent to an environment/system proxy.
            builder.no_proxy()
        } else {
            builder.https_only(true)
        };
        let http = builder
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(20))
            .build()
            .map_err(|_| "Could not initialize the secure connection")?;
        Ok(Self { http, base_url })
    }

    pub async fn pair(&self, token: &str, name: &str) -> Result<ClientGrant, String> {
        if token.len() != 64 || !token.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("invalid_pairing_format".into());
        }
        self.request(Method::POST, "auth/pair", token, Some(json!({"name":name})))
            .await
    }

    pub async fn renew(&self, credential: &str) -> Result<AccessSession, String> {
        self.request(Method::POST, "auth/session", credential, None)
            .await
    }

    pub async fn info(&self, access: &str) -> Result<ServerInfo, String> {
        let info: ServerInfo = self
            .request(Method::GET, "server/info", access, None)
            .await?;
        if info.protocol_version != magi_service_contract::SERVER_PROTOCOL_VERSION {
            return Err("Center protocol is unsupported; update the client or center".into());
        }
        Ok(info)
    }

    async fn request<T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        token: &str,
        body: Option<Value>,
    ) -> Result<T, String> {
        let bytes = self
            .request_bytes(method, path, token, body, MAX_RESPONSE_BYTES)
            .await?;
        let envelope: Envelope<T> =
            serde_json::from_slice(&bytes).map_err(|_| "Center returned an invalid response")?;
        if !envelope.success {
            return Err("Center request was rejected".into());
        }
        Ok(envelope.data)
    }

    pub async fn file_output<T: DeserializeOwned>(
        &self,
        path: &str,
        token: &str,
    ) -> Result<T, String> {
        let bytes = self
            .request_bytes(Method::GET, path, token, None, 2 * 1024 * 1024)
            .await?;
        serde_json::from_slice(&bytes)
            .map_err(|_| "Center returned invalid file output metadata".into())
    }

    async fn request_bytes(
        &self,
        method: Method,
        path: &str,
        token: &str,
        body: Option<Value>,
        max_bytes: usize,
    ) -> Result<Vec<u8>, String> {
        if token.is_empty() || token.len() > 256 {
            return Err("Center credential is invalid".into());
        }
        let mut request = self
            .http
            .request(method, format!("{}/{path}", self.base_url))
            .header(TOKEN_HEADER, token);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let mut response = request.send().await.map_err(|_| {
            "Center connection failed; check its address, network and certificate when using HTTPS"
        })?;
        let status = response.status();
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| "Center response was interrupted")?
        {
            if bytes.len() + chunk.len() > max_bytes {
                return Err("Center response exceeds the size limit".into());
            }
            bytes.extend_from_slice(&chunk);
        }
        if !status.is_success() {
            // Preserve known protocol codes without exposing remote response text or credentials.
            let code = response_error_code(status.as_u16(), &bytes);
            log::warn!("Center request rejected (path={path}, status={status}, code={code})");
            return Err(code.into());
        }
        Ok(bytes)
    }
}

fn response_error_code(status: u16, bytes: &[u8]) -> &'static str {
    #[derive(Deserialize)]
    struct Failure {
        error_code: String,
    }
    let failure = serde_json::from_slice::<Failure>(bytes).ok();
    match (
        status,
        failure.as_ref().map(|value| value.error_code.as_str()),
    ) {
        (401, Some("invalid_pairing_grant")) => "invalid_pairing_grant",
        (401, Some("invalid_client_credential")) => "invalid_client_credential",
        (401, Some("client_auth_required")) => "client_auth_required",
        (403, Some("origin_not_allowed")) => "origin_not_allowed",
        (401 | 403, _) => "center_authorization_rejected",
        (429, _) => "auth_busy",
        _ => "Center connection request failed",
    }
}

fn initialize_tls() {
    static INITIALIZED: std::sync::Once = std::sync::Once::new();
    INITIALIZED.call_once(|| {
        let _ = rustls::crypto::ring::default_provider().install_default();
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    const PAIR_CODE: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    #[test]
    fn authentication_errors_preserve_codes_without_remote_messages() {
        for code in [
            "invalid_pairing_grant",
            "invalid_client_credential",
            "client_auth_required",
        ] {
            let body = json!({"error_code": code, "message": "untrusted remote text"});
            assert_eq!(response_error_code(401, body.to_string().as_bytes()), code);
        }
        assert_eq!(
            response_error_code(403, br#"{"error_code":"origin_not_allowed"}"#),
            "origin_not_allowed"
        );
        assert_eq!(
            response_error_code(401, b"not json"),
            "center_authorization_rejected"
        );
        assert_eq!(
            response_error_code(403, br#"{"error_code":"unknown_secret"}"#),
            "center_authorization_rejected"
        );
        assert_eq!(
            response_error_code(500, br#"{"error_code":"invalid_pairing_grant"}"#),
            "Center connection request failed"
        );
    }

    #[tokio::test]
    async fn pairing_rejects_full_output_and_quoted_or_malformed_codes_before_network_io() {
        let client = CenterClient::remote("http://127.0.0.1:1").unwrap();
        for token in [
            String::new(),
            format!("\"{PAIR_CODE}\""),
            json!({"pairing_token":PAIR_CODE}).to_string(),
            "g".repeat(64),
            "a".repeat(63),
        ] {
            assert_eq!(
                client.pair(&token, "Laptop").await.err().unwrap(),
                "invalid_pairing_format"
            );
        }
    }

    #[tokio::test]
    async fn pairing_rejection_reaches_the_caller_as_a_protocol_code() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = [0; 4096];
            socket.read(&mut request).await.unwrap();
            let body = r#"{"success":false,"error_code":"invalid_pairing_grant","message":"Pairing grant is invalid or expired"}"#;
            socket.write_all(format!("HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        });
        let client = CenterClient::remote(&format!("http://{address}")).unwrap();
        assert_eq!(
            client.pair(PAIR_CODE, "Laptop").await.err().unwrap(),
            "invalid_pairing_grant"
        );
        server.await.unwrap();
    }

    #[tokio::test]
    async fn download_contract_accepts_bounded_raw_json_without_native_envelopes() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = vec![0; 4096];
            let length = socket.read(&mut request).await.unwrap();
            let headers = String::from_utf8_lossy(&request[..length]);
            assert!(headers.contains("x-magi-session-token: test-access"));
            let body = serde_json::json!({"data":"x".repeat(1400000)}).to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).as_bytes()).await.unwrap();
            socket.write_all(body.as_bytes()).await.unwrap();
        });
        let client = CenterClient::local(&format!("http://{address}/api")).unwrap();
        let output: Value = client
            .file_output("files/outputs/id/chunks", "test-access")
            .await
            .unwrap();
        assert_eq!(output["data"].as_str().unwrap().len(), 1400000);
        server.await.unwrap();
    }

    #[test]
    fn remote_address_cannot_inject_paths_credentials_or_insecure_transport() {
        assert_eq!(
            normalize_remote_url(" https://center.example:9443/api/ ").unwrap(),
            "https://center.example:9443/api"
        );
        for address in [
            "http://center.example",
            "http://192.168.1.20:19080",
            "http://0.0.0.0:19080",
            "http://127.0.0.1.example:19080",
            "http://localhost.example:19080",
            "http://localhost.:19080",
            "http://[2001:db8::1]:19080",
            "http://127.0.0.1:19080/other",
            "http://127.0.0.1:19080?token=secret",
            "http://127.0.0.1:19080/#fragment",
            "http://owner:secret@127.0.0.1:19080",
            "https://owner:password@center.example",
            "https://center.example?token=secret",
            "https://center.example/other",
            "https://center.example/#fragment",
            "file:///tmp/center",
        ] {
            assert!(normalize_remote_url(address).is_err(), "{address}");
        }
    }

    #[test]
    fn same_machine_addresses_are_canonical_and_do_not_depend_on_dns() {
        for input in [
            "http://127.0.0.1:19080",
            " http://localhost:19080/api/ ",
            "http://LOCALHOST:19080/",
        ] {
            assert_eq!(
                normalize_remote_url(input).unwrap(),
                "http://127.0.0.1:19080/api"
            );
        }
    }

    #[tokio::test]
    async fn loopback_pairing_renewal_info_and_download_keep_authentication() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            for (path, token, body) in [
                (
                    "POST /api/auth/pair ",
                    PAIR_CODE,
                    json!({"success":true,"data":{
                        "server_id":"center", "client_id":"device", "client_credential":"device-key"
                    }}),
                ),
                (
                    "POST /api/auth/session ",
                    "device-key",
                    json!({"success":true,"data":{
                        "server_id":"center", "client_id":"device", "access_token":"session-key", "expires_at_ms":1
                    }}),
                ),
                (
                    "GET /api/server/info ",
                    "session-key",
                    json!({"success":true,"data":{
                        "server_id":"center", "protocol_version":magi_service_contract::SERVER_PROTOCOL_VERSION,
                        "service_ready":true, "maintenance":{"data_epoch":"data", "content_epoch":"content", "phase":"idle"}
                    }}),
                ),
                (
                    "GET /api/files/outputs/id/chunks ",
                    "session-key",
                    json!({"data":"file-content"}),
                ),
            ] {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut headers = Vec::new();
                while !headers.windows(4).any(|part| part == b"\r\n\r\n") {
                    let mut buffer = [0; 1024];
                    let length = socket.read(&mut buffer).await.unwrap();
                    assert!(length > 0 && headers.len() + length <= 8192);
                    headers.extend_from_slice(&buffer[..length]);
                }
                let headers = String::from_utf8_lossy(&headers);
                assert!(headers.starts_with(path), "{headers}");
                assert!(headers.contains(&format!("x-magi-session-token: {token}\r\n")));
                let body = body.to_string();
                socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        });
        let client = CenterClient::remote(&format!("http://localhost:{port}")).unwrap();
        let grant = client.pair(PAIR_CODE, "This computer").await.unwrap();
        let session = client.renew(&grant.client_credential).await.unwrap();
        let info = client.info(&session.access_token).await.unwrap();
        assert!(info.service_ready);
        let output: Value = client
            .file_output("files/outputs/id/chunks", &session.access_token)
            .await
            .unwrap();
        assert_eq!(output["data"], "file-content");
        server.await.unwrap();
    }

    #[tokio::test]
    async fn loopback_authentication_never_follows_redirects() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = [0; 4096];
            socket.read(&mut request).await.unwrap();
            socket.write_all(b"HTTP/1.1 302 Found\r\nLocation: http://192.0.2.1/collect\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await.unwrap();
        });
        let client = CenterClient::remote(&format!("http://{address}")).unwrap();
        let error = tokio::time::timeout(Duration::from_secs(1), client.info("test-access"))
            .await
            .unwrap()
            .err()
            .unwrap();
        assert_eq!(error, "Center connection request failed");
        server.await.unwrap();
    }
}
