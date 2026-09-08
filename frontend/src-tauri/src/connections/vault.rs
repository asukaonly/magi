const SERVICE: &str = "com.magi.desktop.centers";

#[cfg(target_os = "macos")]
pub fn put(id: &str, credential: &str) -> Result<(), String> {
    security_framework::passwords::set_generic_password(SERVICE, id, credential.as_bytes())
        .map_err(|_| "Could not save the center credential in Keychain".into())
}

#[cfg(target_os = "macos")]
pub fn get(id: &str) -> Result<String, String> {
    let bytes = security_framework::passwords::get_generic_password(SERVICE, id)
        .map_err(|_| "Could not read the center credential from Keychain")?;
    String::from_utf8(bytes).map_err(|_| "Stored center credential is invalid".into())
}

#[cfg(target_os = "macos")]
pub fn remove(id: &str) -> Result<(), String> {
    match security_framework::passwords::delete_generic_password(SERVICE, id) {
        Ok(()) => Ok(()),
        Err(error) if error.code() == -25300 => Ok(()),
        Err(_) => Err("Could not remove the center credential from Keychain".into()),
    }
}

#[cfg(windows)]
mod windows {
    use windows_sys::Win32::Security::Credentials::*;

    fn target(id: &str) -> Vec<u16> {
        format!("{}/{id}\0", super::SERVICE)
            .encode_utf16()
            .collect()
    }

    pub fn put(id: &str, credential: &str) -> Result<(), String> {
        let mut target = target(id);
        let mut bytes = credential.as_bytes().to_vec();
        let record = CREDENTIALW {
            Type: CRED_TYPE_GENERIC,
            TargetName: target.as_mut_ptr(),
            CredentialBlobSize: bytes.len() as u32,
            CredentialBlob: bytes.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            ..Default::default()
        };
        // SAFETY: all pointers reference live, correctly sized buffers for this synchronous call.
        if unsafe { CredWriteW(&record, 0) } == 0 {
            return Err(
                "Could not save the center credential in Windows Credential Manager".into(),
            );
        }
        Ok(())
    }

    pub fn get(id: &str) -> Result<String, String> {
        let target = target(id);
        let mut record = std::ptr::null_mut();
        // SAFETY: the API allocates the result on success and CredFree releases it below.
        unsafe {
            if CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut record) == 0 {
                return Err(
                    "Could not read the center credential from Windows Credential Manager".into(),
                );
            }
            let bytes = if (*record).CredentialBlobSize > 0
                && (*record).CredentialBlobSize <= 256
                && !(*record).CredentialBlob.is_null()
            {
                Some(
                    std::slice::from_raw_parts(
                        (*record).CredentialBlob,
                        (*record).CredentialBlobSize as usize,
                    )
                    .to_vec(),
                )
            } else {
                None
            };
            CredFree(record.cast());
            String::from_utf8(bytes.ok_or("Stored center credential is invalid")?)
                .map_err(|_| "Stored center credential is invalid".into())
        }
    }

    pub fn remove(id: &str) -> Result<(), String> {
        let target = target(id);
        // SAFETY: target is a null-terminated UTF-16 buffer valid for the synchronous call.
        if unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) } == 0 {
            // ERROR_NOT_FOUND means deletion has already completed.
            if unsafe { windows_sys::Win32::Foundation::GetLastError() } != 1168 {
                return Err(
                    "Could not remove the center credential from Windows Credential Manager".into(),
                );
            }
        }
        Ok(())
    }
}

#[cfg(windows)]
pub use windows::{get, put, remove};

#[cfg(not(any(target_os = "macos", windows)))]
pub fn put(_id: &str, _credential: &str) -> Result<(), String> {
    Err(format!(
        "OS credential storage for {SERVICE} is not supported on this platform"
    ))
}
#[cfg(not(any(target_os = "macos", windows)))]
pub fn get(_id: &str) -> Result<String, String> {
    Err("OS credential storage is not supported on this platform".into())
}
#[cfg(not(any(target_os = "macos", windows)))]
pub fn remove(_id: &str) -> Result<(), String> {
    Err("OS credential storage is not supported on this platform".into())
}
