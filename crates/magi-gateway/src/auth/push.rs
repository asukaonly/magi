//! Device push registrations share the credential owner's revocation boundary.

#[derive(Clone, PartialEq, Eq)]
pub struct PushDevice {
    pub client_id: String,
    pub token: String,
    pub environment: String,
    pub data_epoch: String,
    pub after_id: i64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::AuthStore;

    #[test]
    fn rotation_retries_epoch_and_revocation_keep_the_device_boundary() {
        let store = AuthStore::local("owner");
        let grant = store.create_pairing_grant().unwrap();
        let client = store.pair(&grant.pairing_token, "Phone").unwrap();
        let mut device = PushDevice {
            client_id: client.client_id.clone(),
            token: "ab".repeat(32),
            environment: "development".into(),
            data_epoch: "epoch".into(),
            after_id: 4,
        };
        store.register_push(&device).unwrap();
        store.advance_push(&device, 5, false).unwrap();
        device.token = "cd".repeat(32);
        device.after_id = 99;
        store.register_push(&device).unwrap();
        assert_eq!(store.push_devices().unwrap()[0].after_id, 5);
        device.data_epoch = "new".into();
        store.register_push(&device).unwrap();
        assert_eq!(store.push_devices().unwrap()[0].after_id, 99);
        let old = PushDevice {
            data_epoch: "epoch".into(),
            ..device.clone()
        };
        store.advance_push(&old, 100, true).unwrap();
        assert_eq!(store.push_devices().unwrap().len(), 1);
        store.revoke(&client.client_id).unwrap();
        assert!(store.push_devices().unwrap().is_empty());
        assert!(store.register_push(&device).is_err());
        device.token = "/invalid".into();
        assert!(store.register_push(&device).is_err());
    }
}

impl super::AuthStore {
    pub fn register_push(&self, device: &PushDevice) -> Result<(), String> {
        if !(32..=512).contains(&device.token.len())
            || device.token.len() % 2 != 0
            || !device.token.bytes().all(|b| b.is_ascii_hexdigit())
            || !matches!(device.environment.as_str(), "development" | "production")
        {
            return Err("Invalid push registration".into());
        }
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .register_push(device)
    }

    pub fn push_devices(&self) -> Result<Vec<PushDevice>, String> {
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .push_devices()
    }

    pub fn remove_push(&self, client: &str) -> Result<(), String> {
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove_push(client)
    }

    pub fn advance_push(
        &self,
        device: &PushDevice,
        next: i64,
        invalid: bool,
    ) -> Result<(), String> {
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .advance_push(device, next, invalid)
    }
}
