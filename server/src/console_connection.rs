//! Device connection guidance. Remote probes never carry operator credentials.

use crate::{
    console::{clean, progress, ui},
    console_api::{management, string, Request},
};
use magi_service_contract::config::ServerConfig;
use serde_json::Value;
use std::{collections::HashSet, io::Read, time::Duration};

fn remote_address(value: &str) -> Result<String, String> {
    let url = reqwest::Url::parse(value.trim()).map_err(|_| "Enter the full HTTPS address")?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || !matches!(url.path(), "" | "/" | "/api" | "/api/")
    {
        return Err(
            "Use an HTTPS address without credentials, query parameters or a custom path".into(),
        );
    }
    if matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]")) {
        return Err(
            "Use the hostname reachable from your other device, not a loopback address".into(),
        );
    }
    Ok(url.origin().ascii_serialization())
}

fn probe(address: &str) -> Result<(), String> {
    let _ = rustls::crypto::ring::default_provider().install_default();
    let client = reqwest::blocking::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())?;
    probe_with(&client, address)
}

fn probe_with(client: &reqwest::blocking::Client, address: &str) -> Result<(), String> {
    let response = client.get(format!("{address}/api/health")).send()
        .map_err(|_| "Cannot reach this HTTPS address. Check the hostname, certificate, proxy and network access.")?;
    if !response.status().is_success() {
        return Err(format!(
            "The address returned HTTP {}. Forward /api to this Magi service without redirects.",
            response.status().as_u16()
        ));
    }
    let mut bytes = Vec::new();
    response
        .take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| "Could not read the health response")?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| "This address did not return a Magi health response")?;
    if bytes.len() > 4096 || value["status"] != "ok" {
        return Err("This address did not return a healthy Magi response".into());
    }
    Ok(())
}

fn clients(config: &ServerConfig) -> Result<Vec<Value>, String> {
    management(config, Request::Clients)?
        .as_array()
        .cloned()
        .ok_or("Invalid paired-device response".into())
}

fn newly_paired<'a>(before: &HashSet<String>, entries: &'a [Value]) -> Option<&'a Value> {
    entries.iter().find(|entry| {
        entry["revoked_at_ms"].is_null()
            && entry["role"] == "admin"
            && entry["client_id"]
                .as_str()
                .is_some_and(|id| !before.contains(id))
    })
}

pub fn guide(config: &ServerConfig, base_url: &str) -> Result<(), String> {
    let target = ui(cliclack::select("Where will you use Magi desktop?")
        .item("local", "On this computer", "Use the local address")
        .item(
            "remote",
            "On another device",
            "Set up and check an HTTPS address",
        )
        .item(
            "later",
            "Connect later",
            "Keep the service and saved settings",
        )
        .interact())?;
    let local = base_url.trim_end_matches("/api");
    let address = match target {
        "later" => {
            ui(cliclack::log::info(
                "Device connection is pending. Choose Connect another device when ready.",
            ))?;
            return Ok(());
        }
        "remote" => {
            ui(cliclack::note("Connect from another device", format!(
                "This service is currently available only on this Mac.\nFor a private network, install Tailscale and sign in on both devices.\nOn this Mac, run in another terminal:\n  tailscale serve --bg {local}\nUse the HTTPS address printed by Tailscale.\nAn existing HTTPS proxy can also forward /api to {local}.\nAllow streaming responses without buffering.\nGuide: https://tailscale.com/kb/1242/tailscale-serve"
            )))?;
            if !ui(cliclack::confirm("Is your HTTPS address ready?")
                .initial_value(false)
                .interact())?
            {
                ui(cliclack::log::info("Local service is available. Remote access is pending; return to Connect another device after setting up HTTPS."))?;
                return Ok(());
            }
            let mut address = String::new();
            loop {
                let value: String = ui(cliclack::input("HTTPS address for your other device")
                    .default_input(&address)
                    .validate(|v: &String| remote_address(v).map(|_| ()))
                    .interact())?;
                address = remote_address(&value)?;
                match progress(
                    "Checking HTTPS access",
                    "HTTPS responds from this Mac",
                    "HTTPS check failed",
                    || probe(&address),
                ) {
                    Ok(()) => break address,
                    Err(error) => {
                        ui(cliclack::log::warning(error))?;
                        if !ui(cliclack::confirm("Edit the address or retry?")
                            .initial_value(true)
                            .interact())?
                        {
                            ui(cliclack::log::info(
                                "Remote access is still pending. No pairing code was issued.",
                            ))?;
                            return Ok(());
                        }
                    }
                }
            }
        }
        _ => local.to_owned(),
    };
    let before: HashSet<String> = clients(config)?
        .iter()
        .filter_map(|v| v["client_id"].as_str().map(str::to_owned))
        .collect();
    show_pairing(config, &address)?;
    loop {
        match ui(cliclack::select("Finish connecting your device")
            .item(
                "check",
                "Check for a paired device",
                "Pair in Magi desktop, then check here",
            )
            .item(
                "code",
                "Generate another pairing code",
                "For a new device or an expired code",
            )
            .item(
                "later",
                "Finish later",
                "Connection remains pending until a device pairs",
            )
            .interact())?
        {
            "check" => {
                let entries = clients(config)?;
                if let Some(device) = newly_paired(&before, &entries) {
                    ui(cliclack::log::success(format!(
                        "Device paired with this Magi: {}",
                        clean(string(device, "name")?)
                    )))?;
                    return Ok(());
                }
                ui(cliclack::log::info("No new device has paired yet. Open Magi desktop, choose Connect to remote Magi, and enter the address and code."))?;
            }
            "code" => show_pairing(config, &address)?,
            _ => {
                ui(cliclack::log::info(
                    "Pairing instructions are ready. Device connection has not been confirmed.",
                ))?;
                return Ok(());
            }
        }
    }
}

fn show_pairing(config: &ServerConfig, address: &str) -> Result<(), String> {
    let grant = management(config, Request::Pair)?;
    ui(cliclack::note("Connect Magi desktop", format!(
        "Choose Connect to remote Magi on the target device.\nMagi address: {address}\nPairing code (single use, 30 minutes):\n{}\nCopy only the code, without quotes. Restarting the service invalidates it.\nThe desktop verifies this Magi's identity during pairing.", string(&grant, "pairing_token")?
    )))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn remote_inputs_require_a_clean_https_origin() {
        assert_eq!(
            remote_address("https://magi.example:444/api/").unwrap(),
            "https://magi.example:444"
        );
        for value in [
            "http://magi.example",
            "https://user:secret@magi.example",
            "https://magi.example?key=secret",
            "https://localhost",
            "https://127.0.0.1",
            "https://magi.example/other",
        ] {
            assert!(remote_address(value).is_err(), "{value}");
        }
    }
    #[test]
    fn pairing_confirmation_ignores_existing_revoked_and_collector_devices() {
        let before = HashSet::from(["existing".to_owned()]);
        let mut entries = vec![
            json!({"client_id":"existing","role":"admin"}),
            json!({"client_id":"collector","role":"collector"}),
            json!({"client_id":"revoked","role":"admin","revoked_at_ms":1}),
        ];
        assert!(newly_paired(&before, &entries).is_none());
        entries.push(json!({"client_id":"new","role":"admin","name":"Laptop"}));
        assert_eq!(newly_paired(&before, &entries).unwrap()["name"], "Laptop");
    }

    #[test]
    fn health_probe_is_credential_free_and_rejects_redirects() {
        use std::{io::Write, net::TcpListener};
        let _ = rustls::crypto::ring::default_provider().install_default();
        for (status, body, succeeds) in [
            ("200 OK", r#"{"status":"ok"}"#, true),
            ("200 OK", r#"{"status":"wrong"}"#, false),
            ("302 Found", "", false),
        ] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let address = format!("http://{}", listener.local_addr().unwrap());
            let server = std::thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut buffer = [0; 8192];
                let size = stream.read(&mut buffer).unwrap();
                let request = String::from_utf8_lossy(&buffer[..size]).to_lowercase();
                assert!(request.starts_with("get /api/health "));
                assert!(!request.contains("authorization:"));
                assert!(!request.contains("x-magi-session-token:"));
                write!(stream, "HTTP/1.1 {status}\r\nContent-Length: {}\r\nLocation: http://127.0.0.1:1/\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
            });
            let client = reqwest::blocking::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .timeout(Duration::from_secs(5))
                .build()
                .unwrap();
            assert_eq!(probe_with(&client, &address).is_ok(), succeeds);
            server.join().unwrap();
        }
    }
}
