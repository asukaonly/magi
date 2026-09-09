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
    let url = Url::parse(raw.trim()).map_err(|_| "Enter a valid HTTPS center address")?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || !matches!(url.path(), "" | "/" | "/api" | "/api/")
    {
        return Err(
            "Center address must use HTTPS with no credentials, query or extra path".into(),
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
        let http = Client::builder()
            .https_only(true)
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(20))
            .build()
            .map_err(|_| "Could not initialize the secure connection")?;
        Ok(Self { http, base_url })
    }

    pub async fn pair(&self, token: &str, name: &str) -> Result<ClientGrant, String> {
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
            "Secure center connection failed; check its address, network and HTTPS trust"
        })?;
        if !response.status().is_success() {
            return Err(match response.status().as_u16() {
                401 | 403 => "Center authorization was rejected; pair this device again",
                429 => "Center is busy; try again shortly",
                _ => "Center connection request failed",
            }
            .into());
        }
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
        Ok(bytes)
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
            "https://owner:password@center.example",
            "https://center.example?token=secret",
            "https://center.example/other",
            "https://center.example/#fragment",
            "file:///tmp/center",
        ] {
            assert!(normalize_remote_url(address).is_err(), "{address}");
        }
    }
}
