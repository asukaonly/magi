//! Cross-platform OS credential storage abstraction (macOS Keychain, Windows
//! Credential Manager, Linux Secret Service) with an injectable in-memory
//! backend for isolated testing.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

pub const SECRET_REF_PREFIX: &str = "secret_ref:";
const HEX_VALUE_PREFIX: &str = "magi_hex:";

/// Honest status disclosure of the active OS secret storage backend.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SecretStorageStatus {
    pub backend: &'static str,
    pub secure: bool,
}

/// Return true when ``value`` is a canonical ``secret_ref:...`` placeholder.
pub fn is_secret_ref(value: &str) -> bool {
    value.starts_with(SECRET_REF_PREFIX) && value.len() > SECRET_REF_PREFIX.len()
}

/// Build a canonical opaque secret reference key.
pub fn make_secret_ref(namespace: &str, key: &str) -> String {
    format!("{SECRET_REF_PREFIX}{namespace}:{key}")
}

/// Deterministic 64-bit FNV-1a hex suffix used to scope Keychain service names
/// to a specific data directory without extra hash dependencies.
pub fn scope_service_name(base_service: &str, scope: &str) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in scope.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0100_0000_01b3);
    }
    format!("{base_service}.{hash:016x}")
}

/// Platform credential store interface.
pub trait OsSecretBackend: Send + Sync {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, String>;
    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), String>;
    fn delete(&self, service: &str, account: &str) -> Result<(), String>;
    fn status(&self) -> SecretStorageStatus;
}

/// In-memory credential backend for unit tests (never touches host Keychain).
#[derive(Default)]
pub struct InMemorySecretBackend {
    items: Mutex<BTreeMap<(String, String), String>>,
    fail_writes: AtomicBool,
}

impl InMemorySecretBackend {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_fail_writes(&self, fail: bool) {
        self.fail_writes.store(fail, Ordering::SeqCst);
    }

    pub fn len(&self) -> usize {
        self.items.lock().map(|g| g.len()).unwrap_or(0)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

impl OsSecretBackend for InMemorySecretBackend {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, String> {
        let guard = self
            .items
            .lock()
            .map_err(|_| "in_memory_secret_store_poisoned".to_string())?;
        Ok(guard.get(&(service.to_string(), account.to_string())).cloned())
    }

    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), String> {
        if self.fail_writes.load(Ordering::SeqCst) {
            return Err("os_secret_store_write_denied".into());
        }
        let mut guard = self
            .items
            .lock()
            .map_err(|_| "in_memory_secret_store_poisoned".to_string())?;
        guard.insert((service.to_string(), account.to_string()), secret.to_string());
        Ok(())
    }

    fn delete(&self, service: &str, account: &str) -> Result<(), String> {
        let mut guard = self
            .items
            .lock()
            .map_err(|_| "in_memory_secret_store_poisoned".to_string())?;
        guard.remove(&(service.to_string(), account.to_string()));
        Ok(())
    }

    fn status(&self) -> SecretStorageStatus {
        SecretStorageStatus {
            backend: "memory",
            secure: true,
        }
    }
}

/// Platform-native OS credential backend.
#[derive(Default, Clone, Copy)]
pub struct NativeSecretBackend;

impl NativeSecretBackend {
    pub fn new() -> Self {
        Self
    }
}

#[cfg_attr(target_os = "windows", allow(dead_code))]
fn encode_hex_transport(secret: &str) -> String {
    let mut out = String::with_capacity(HEX_VALUE_PREFIX.len() + secret.len() * 2);
    out.push_str(HEX_VALUE_PREFIX);
    for byte in secret.as_bytes() {
        use std::fmt::Write;
        let _ = write!(&mut out, "{byte:02x}");
    }
    out
}

#[cfg_attr(target_os = "windows", allow(dead_code))]
fn decode_hex_transport(raw: &str) -> String {
    let Some(hex_part) = raw.strip_prefix(HEX_VALUE_PREFIX) else {
        return raw.to_string();
    };
    if hex_part.len() % 2 != 0 {
        return raw.to_string();
    }
    let mut bytes = Vec::with_capacity(hex_part.len() / 2);
    for chunk in hex_part.as_bytes().chunks(2) {
        let Ok(pair) = std::str::from_utf8(chunk) else {
            return raw.to_string();
        };
        let Ok(byte) = u8::from_str_radix(pair, 16) else {
            return raw.to_string();
        };
        bytes.push(byte);
    }
    String::from_utf8(bytes).unwrap_or_else(|_| raw.to_string())
}

#[cfg(target_os = "macos")]
impl OsSecretBackend for NativeSecretBackend {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, String> {
        use std::process::Command;

        let output = Command::new("/usr/bin/security")
            .args(["find-generic-password", "-s", service, "-a", account, "-w"])
            .output()
            .map_err(|_| "macos_keychain_exec_failed".to_string())?;
        if output.status.code() == Some(44) {
            return Ok(None);
        }
        if !output.status.success() {
            return Err("macos_keychain_read_failed".into());
        }
        let raw = String::from_utf8(output.stdout)
            .map_err(|_| "macos_keychain_invalid_utf8".to_string())?;
        Ok(Some(decode_hex_transport(raw.trim_end_matches(['\r', '\n']))))
    }

    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), String> {
        use std::io::Write;
        use std::process::{Command, Stdio};

        let encoded = encode_hex_transport(secret);
        let script = format!(
            "add-generic-password -U -s \"{service}\" -a \"{account}\" -w \"{encoded}\"\n"
        );
        let mut child = Command::new("/usr/bin/security")
            .arg("-i")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "macos_keychain_exec_failed".to_string())?;
        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(script.as_bytes())
                .map_err(|_| "macos_keychain_stdin_failed".to_string())?;
        }
        let status = child
            .wait()
            .map_err(|_| "macos_keychain_wait_failed".to_string())?;
        if !status.success() {
            return Err("macos_keychain_write_failed".into());
        }
        Ok(())
    }

    fn delete(&self, service: &str, account: &str) -> Result<(), String> {
        use std::process::Command;

        let status = Command::new("/usr/bin/security")
            .args(["delete-generic-password", "-s", service, "-a", account])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .map_err(|_| "macos_keychain_exec_failed".to_string())?;
        if !status.success() && status.code() != Some(44) {
            return Err("macos_keychain_delete_failed".into());
        }
        Ok(())
    }

    fn status(&self) -> SecretStorageStatus {
        SecretStorageStatus {
            backend: "macos_keychain",
            secure: true,
        }
    }
}

#[cfg(target_os = "windows")]
mod win32_credman {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr;

    const CRED_TYPE_GENERIC: u32 = 1;
    const CRED_PERSIST_LOCAL_MACHINE: u32 = 2;
    const ERROR_NOT_FOUND: u32 = 1168;

    #[repr(C)]
    struct FileTime {
        low_date_time: u32,
        high_date_time: u32,
    }

    #[repr(C)]
    struct CredentialW {
        flags: u32,
        cred_type: u32,
        target_name: *mut u16,
        comment: *mut u16,
        last_written: FileTime,
        credential_blob_size: u32,
        credential_blob: *mut u8,
        persist: u32,
        attribute_count: u32,
        attributes: *mut std::ffi::c_void,
        target_alias: *mut u16,
        user_name: *mut u16,
    }

    #[link(name = "advapi32")]
    extern "system" {
        fn CredReadW(
            target_name: *const u16,
            cred_type: u32,
            flags: u32,
            credential: *mut *mut CredentialW,
        ) -> i32;
        fn CredWriteW(credential: *const CredentialW, flags: u32) -> i32;
        fn CredDeleteW(target_name: *const u16, cred_type: u32, flags: u32) -> i32;
        fn CredFree(buffer: *mut std::ffi::c_void);
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetLastError() -> u32;
    }

    fn to_wide(value: &str) -> Vec<u16> {
        OsStr::new(value)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    pub fn get(target: &str) -> Result<Option<String>, String> {
        let wide_target = to_wide(target);
        let mut cred_ptr: *mut CredentialW = ptr::null_mut();
        let ok = unsafe { CredReadW(wide_target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut cred_ptr) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            if err == ERROR_NOT_FOUND {
                return Ok(None);
            }
            return Err("windows_credman_read_failed".into());
        }
        let result = unsafe {
            let cred = &*cred_ptr;
            let slice = if cred.credential_blob.is_null() || cred.credential_blob_size == 0 {
                &[]
            } else {
                std::slice::from_raw_parts(cred.credential_blob, cred.credential_blob_size as usize)
            };
            String::from_utf8(slice.to_vec())
                .map(Some)
                .map_err(|_| "windows_credman_invalid_utf8".to_string())
        };
        unsafe { CredFree(cred_ptr.cast()) };
        result
    }

    pub fn set(target: &str, account: &str, secret: &str) -> Result<(), String> {
        let mut wide_target = to_wide(target);
        let mut wide_user = to_wide(account);
        let mut blob = secret.as_bytes().to_vec();
        let cred = CredentialW {
            flags: 0,
            cred_type: CRED_TYPE_GENERIC,
            target_name: wide_target.as_mut_ptr(),
            comment: ptr::null_mut(),
            last_written: FileTime {
                low_date_time: 0,
                high_date_time: 0,
            },
            credential_blob_size: blob.len() as u32,
            credential_blob: blob.as_mut_ptr(),
            persist: CRED_PERSIST_LOCAL_MACHINE,
            attribute_count: 0,
            attributes: ptr::null_mut(),
            target_alias: ptr::null_mut(),
            user_name: wide_user.as_mut_ptr(),
        };
        let ok = unsafe { CredWriteW(&cred, 0) };
        if ok == 0 {
            return Err("windows_credman_write_failed".into());
        }
        Ok(())
    }

    pub fn delete(target: &str) -> Result<(), String> {
        let wide_target = to_wide(target);
        let ok = unsafe { CredDeleteW(wide_target.as_ptr(), CRED_TYPE_GENERIC, 0) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            if err != ERROR_NOT_FOUND {
                return Err("windows_credman_delete_failed".into());
            }
        }
        Ok(())
    }
}

#[cfg(target_os = "windows")]
impl OsSecretBackend for NativeSecretBackend {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, String> {
        win32_credman::get(&format!("{service}/{account}"))
    }

    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), String> {
        win32_credman::set(&format!("{service}/{account}"), account, secret)
    }

    fn delete(&self, service: &str, account: &str) -> Result<(), String> {
        win32_credman::delete(&format!("{service}/{account}"))
    }

    fn status(&self) -> SecretStorageStatus {
        SecretStorageStatus {
            backend: "windows_credential_manager",
            secure: true,
        }
    }
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
impl OsSecretBackend for NativeSecretBackend {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, String> {
        use std::process::Command;

        if std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_none() {
            return Err("os_secret_store_unavailable".into());
        }
        let output = Command::new("secret-tool")
            .args(["lookup", "service", service, "account", account])
            .output()
            .map_err(|_| "os_secret_store_unavailable".to_string())?;
        if !output.status.success() || output.stdout.is_empty() {
            return Ok(None);
        }
        let raw = String::from_utf8(output.stdout)
            .map_err(|_| "linux_secret_service_invalid_utf8".to_string())?;
        Ok(Some(decode_hex_transport(raw.trim_end_matches(['\r', '\n']))))
    }

    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), String> {
        use std::io::Write;
        use std::process::{Command, Stdio};

        if std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_none() {
            return Err("os_secret_store_unavailable".into());
        }
        let encoded = encode_hex_transport(secret);
        let mut child = Command::new("secret-tool")
            .args([
                "store",
                "--label",
                &format!("Magi ({account})"),
                "service",
                service,
                "account",
                account,
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "os_secret_store_unavailable".to_string())?;
        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(encoded.as_bytes())
                .map_err(|_| "linux_secret_service_stdin_failed".to_string())?;
        }
        let status = child
            .wait()
            .map_err(|_| "linux_secret_service_wait_failed".to_string())?;
        if !status.success() {
            return Err("linux_secret_service_write_failed".into());
        }
        Ok(())
    }

    fn delete(&self, service: &str, account: &str) -> Result<(), String> {
        use std::process::Command;

        if std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_none() {
            return Ok(());
        }
        let _ = Command::new("secret-tool")
            .args(["clear", "service", service, "account", account])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
        Ok(())
    }

    fn status(&self) -> SecretStorageStatus {
        let available = std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_some();
        SecretStorageStatus {
            backend: if available {
                "linux_secret_service"
            } else {
                "unavailable"
            },
            secure: available,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_transport_round_trips_arbitrary_utf8_and_quotes() {
        let original = "tok\"en'with spaces\nand-中文-🔑";
        let encoded = encode_hex_transport(original);
        assert!(encoded.starts_with(HEX_VALUE_PREFIX));
        assert!(!encoded.contains('"'));
        assert!(!encoded.contains('\n'));
        assert_eq!(decode_hex_transport(&encoded), original);
        assert_eq!(decode_hex_transport("plain-legacy-value"), "plain-legacy-value");
    }

    #[test]
    fn in_memory_backend_round_trips_and_honors_write_failures() {
        let backend = InMemorySecretBackend::new();
        let key = make_secret_ref("desktop_connection", "id-1");
        assert!(is_secret_ref(&key));
        assert!(!is_secret_ref("plaintext-token"));
        backend.set("com.magi.test", &key, "secret-value").unwrap();
        assert_eq!(
            backend.get("com.magi.test", &key).unwrap().as_deref(),
            Some("secret-value")
        );
        backend.set_fail_writes(true);
        assert!(backend.set("com.magi.test", &key, "next").is_err());
        assert_eq!(
            backend.get("com.magi.test", &key).unwrap().as_deref(),
            Some("secret-value")
        );
        backend.delete("com.magi.test", &key).unwrap();
        assert_eq!(backend.get("com.magi.test", &key).unwrap(), None);
    }
}
