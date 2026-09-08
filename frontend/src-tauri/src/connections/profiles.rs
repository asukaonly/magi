use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Clone, Deserialize, Serialize)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum Profile {
    Local {
        id: String,
    },
    Remote {
        id: String,
        name: String,
        api_base_url: String,
        server_id: String,
        client_id: String,
    },
}

impl Profile {
    pub fn id(&self) -> &str {
        match self {
            Self::Local { id } | Self::Remote { id, .. } => id,
        }
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileFile {
    pub version: u8,
    pub active_profile_id: Option<String>,
    pub profiles: Vec<Profile>,
}

pub struct ProfileStore {
    path: PathBuf,
    pub data: ProfileFile,
}

impl ProfileStore {
    pub fn open(directory: &Path) -> Result<Self, String> {
        magi_platform::private_data::protect_magi_data_root(directory)?;
        let path = directory.join("connections.json");
        let data = match fs::File::open(&path) {
            Ok(file) => {
                let mut bytes = Vec::new();
                file.take(65537)
                    .read_to_end(&mut bytes)
                    .map_err(|e| e.to_string())?;
                if bytes.len() > 65536 {
                    return Err("Connection profile file exceeds size limit".into());
                }
                let data: ProfileFile = serde_json::from_slice(&bytes)
                    .map_err(|_| "Connection profiles are invalid")?;
                validate(&data)?;
                data
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => ProfileFile {
                version: 1,
                active_profile_id: None,
                profiles: vec![Profile::Local { id: "local".into() }],
            },
            Err(error) => return Err(format!("Could not read connection profiles: {error}")),
        };
        Ok(Self { path, data })
    }

    pub fn save(&mut self, data: ProfileFile) -> Result<(), String> {
        validate(&data)?;
        let parent = self
            .path
            .parent()
            .ok_or("Connection profile directory is missing")?;
        let temporary = parent.join(format!(".connections-{}.tmp", uuid::Uuid::new_v4()));
        let result: Result<(), String> = (|| {
            let mut options = OpenOptions::new();
            options.create_new(true).write(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
            file.write_all(&serde_json::to_vec(&data).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
            file.sync_all().map_err(|e| e.to_string())?;
            drop(file);
            fs::rename(&temporary, &self.path).map_err(|e| e.to_string())?;
            #[cfg(unix)]
            fs::File::open(parent)
                .and_then(|file| file.sync_all())
                .map_err(|e| e.to_string())?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(temporary);
        }
        result?;
        self.data = data;
        Ok(())
    }

    pub fn profile(&self, id: &str) -> Result<Profile, String> {
        self.data
            .profiles
            .iter()
            .find(|profile| profile.id() == id)
            .cloned()
            .ok_or("Connection profile does not exist".into())
    }
}

fn validate(data: &ProfileFile) -> Result<(), String> {
    if data.version != 1 || data.profiles.is_empty() || data.profiles.len() > 17 {
        return Err("Connection profile version or count is invalid".into());
    }
    let mut ids = std::collections::HashSet::new();
    for profile in &data.profiles {
        if !ids.insert(profile.id()) {
            return Err("Connection profile identifiers are duplicated".into());
        }
        match profile {
            Profile::Local { id } if id == "local" => {}
            Profile::Remote {
                id,
                name,
                api_base_url,
                server_id,
                client_id,
            } => {
                for value in [id, server_id, client_id] {
                    uuid::Uuid::parse_str(value).map_err(|_| "Connection identity is invalid")?;
                }
                if name.trim().is_empty() || name.len() > 128 || name.chars().any(char::is_control)
                {
                    return Err("Connection name is invalid".into());
                }
                if super::protocol::normalize_remote_url(api_base_url)? != *api_base_url {
                    return Err("Connection address is not normalized".into());
                }
            }
            _ => return Err("Local connection identity is invalid".into()),
        }
    }
    if !ids.contains("local")
        || data
            .active_profile_id
            .as_deref()
            .is_some_and(|id| !ids.contains(id))
    {
        return Err("Active connection identity is invalid".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profiles_persist_identity_without_credentials_and_reject_unknown_versions() {
        let root = std::env::temp_dir().join(format!("magi-profiles-{}", uuid::Uuid::new_v4()));
        let mut store = ProfileStore::open(&root).unwrap();
        let mut data = store.data.clone();
        let id = uuid::Uuid::new_v4().to_string();
        data.profiles.push(Profile::Remote {
            id: id.clone(),
            name: "Home".into(),
            api_base_url: "https://center.example/api".into(),
            server_id: uuid::Uuid::new_v4().to_string(),
            client_id: uuid::Uuid::new_v4().to_string(),
        });
        data.active_profile_id = Some(id.clone());
        store.save(data).unwrap();
        let reopened = ProfileStore::open(&root).unwrap();
        assert_eq!(
            reopened.data.active_profile_id.as_deref(),
            Some(id.as_str())
        );
        let bytes = fs::read_to_string(root.join("connections.json")).unwrap();
        assert!(!bytes.contains("credential"));
        assert!(!bytes.contains("token"));
        let mut future = reopened.data;
        future.version = 2;
        assert!(store.save(future).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
