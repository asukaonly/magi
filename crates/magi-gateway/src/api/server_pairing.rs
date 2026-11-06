use std::collections::BTreeSet;
use std::net::{IpAddr, SocketAddr};

use serde::Serialize;
use sysinfo::Networks;

use crate::auth::PairingGrant;

#[derive(Serialize)]
pub(super) struct OwnerPairingGrant {
    #[serde(flatten)]
    pub grant: PairingGrant,
    pub network: Option<PairingNetwork>,
}

#[derive(Serialize)]
pub(super) struct PairingNetwork {
    listen_host: String,
    listen_port: u16,
    lan_ips: Vec<String>,
}

/// Read the center's interfaces locally; an egress IP does not identify an ingress URL.
pub(super) fn network_info(listener: SocketAddr) -> PairingNetwork {
    let networks = Networks::new_with_refreshed_list();
    let addresses = networks
        .values()
        .flat_map(|network| network.ip_networks().iter().map(|network| network.addr));
    PairingNetwork {
        listen_host: listener.ip().to_string(),
        listen_port: listener.port(),
        lan_ips: private_addresses(addresses),
    }
}

fn private_addresses(addresses: impl IntoIterator<Item = IpAddr>) -> Vec<String> {
    addresses
        .into_iter()
        .filter(|address| match address {
            IpAddr::V4(ip) => {
                // Include private LAN and shared address space used by VPNs.
                ip.is_private() || (ip.octets()[0] == 100 && (64..=127).contains(&ip.octets()[1]))
            }
            IpAddr::V6(ip) => ip.is_unique_local(),
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .take(32)
        .map(|address| address.to_string())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lists_private_lan_and_vpn_addresses_without_claiming_public_reachability() {
        let addresses = [
            "127.0.0.1",
            "0.0.0.0",
            "192.168.1.2",
            "192.168.1.2",
            "10.0.0.5",
            "172.16.0.3",
            "100.100.0.7",
            "169.254.1.3",
            "8.8.8.8",
            "224.0.0.1",
            "::1",
            "::",
            "fe80::1",
            "fd00::7",
            "2606:4700:4700::1111",
        ]
        .map(|address| address.parse().unwrap());
        assert_eq!(
            private_addresses(addresses),
            vec![
                "10.0.0.5",
                "100.100.0.7",
                "172.16.0.3",
                "192.168.1.2",
                "fd00::7",
            ]
        );
    }

    #[test]
    fn retains_the_actual_bound_listener_port() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let info = network_info(address);
        assert_eq!(info.listen_host, "127.0.0.1");
        assert_eq!(info.listen_port, address.port());
        assert_ne!(info.listen_port, 0);
    }
}
