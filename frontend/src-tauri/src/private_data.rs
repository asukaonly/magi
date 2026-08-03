use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PrivateDataProtectionResult {
    pub protected_directories: usize,
    pub protected_files: usize,
}

pub fn protect_magi_data_root(root: &Path) -> Result<PrivateDataProtectionResult, String> {
    ensure_private_root_exists(root)?;
    let mut result = PrivateDataProtectionResult::default();

    #[cfg(unix)]
    protect_unix_entry(root, &mut result)?;

    #[cfg(windows)]
    {
        let acl = WindowsPrivateAcl::new()?;
        protect_windows_entry(root, &acl, &mut result)?;
    }

    #[cfg(not(any(unix, windows)))]
    return Err("Private data protection is unavailable on this platform".to_string());

    Ok(result)
}

fn ensure_private_root_exists(root: &Path) -> Result<(), String> {
    match fs::symlink_metadata(root) {
        Ok(metadata) => {
            if is_link_or_reparse(&metadata) || !metadata.is_dir() {
                return Err("Magi data root must be a real directory".to_string());
            }
            Ok(())
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let parent = root
                .parent()
                .ok_or_else(|| "Magi data root has no parent directory".to_string())?;
            let parent_metadata = fs::symlink_metadata(parent)
                .map_err(|error| format!("Failed to inspect Magi data root parent: {error}"))?;
            if is_link_or_reparse(&parent_metadata) || !parent_metadata.is_dir() {
                return Err("Magi data root parent must be a real directory".to_string());
            }

            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;

                let mut builder = fs::DirBuilder::new();
                builder.mode(0o700);
                builder
                    .create(root)
                    .map_err(|error| format!("Failed to create Magi data root: {error}"))?;
            }
            #[cfg(not(unix))]
            fs::create_dir(root)
                .map_err(|error| format!("Failed to create Magi data root: {error}"))?;
            Ok(())
        }
        Err(error) => Err(format!("Failed to inspect Magi data root: {error}")),
    }
}

#[cfg(windows)]
fn is_link_or_reparse(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;

    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
fn is_link_or_reparse(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

#[cfg(unix)]
fn protect_unix_entry(path: &Path, result: &mut PrivateDataProtectionResult) -> Result<(), String> {
    use std::os::unix::fs::{MetadataExt, PermissionsExt};

    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Failed to inspect private Magi path: {error}"))?;
    if is_link_or_reparse(&metadata) {
        return Err(format!(
            "Magi data path must not be a symbolic link: {}",
            path.display()
        ));
    }
    if metadata.uid() != unsafe { libc::geteuid() } {
        return Err(format!(
            "Magi data path is not owned by the current account: {}",
            path.display()
        ));
    }
    if metadata.is_file() && metadata.nlink() != 1 {
        return Err(format!(
            "Magi data file must not have external hard links: {}",
            path.display()
        ));
    }

    #[cfg(target_os = "macos")]
    clear_macos_extended_acl(path)?;

    let mode = if metadata.is_dir() {
        0o700
    } else if metadata.mode() & 0o100 != 0 {
        0o700
    } else {
        0o600
    };
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).map_err(|error| {
        format!(
            "Failed to restrict Magi data permissions for {}: {error}",
            path.display()
        )
    })?;

    if metadata.is_dir() {
        result.protected_directories += 1;
        let children = read_children(path)?;
        for child in children {
            protect_unix_entry(&child, result)?;
        }
    } else {
        result.protected_files += 1;
    }
    Ok(())
}

fn read_children(path: &Path) -> Result<Vec<PathBuf>, String> {
    let mut children = fs::read_dir(path)
        .map_err(|error| {
            format!(
                "Failed to enumerate private Magi directory {}: {error}",
                path.display()
            )
        })?
        .map(|entry| {
            entry.map(|entry| entry.path()).map_err(|error| {
                format!(
                    "Failed to inspect private Magi directory entry in {}: {error}",
                    path.display()
                )
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    children.sort();
    Ok(children)
}

#[cfg(target_os = "macos")]
fn clear_macos_extended_acl(path: &Path) -> Result<(), String> {
    use std::ffi::{c_char, c_int, c_void, CString};
    use std::os::unix::ffi::OsStrExt;

    const ACL_TYPE_EXTENDED: c_int = 0x00000100;

    unsafe extern "C" {
        fn acl_init(count: c_int) -> *mut c_void;
        fn acl_set_file(path: *const c_char, acl_type: c_int, acl: *mut c_void) -> c_int;
        fn acl_free(value: *mut c_void) -> c_int;
    }

    let path_bytes = path.as_os_str().as_bytes();
    let c_path = CString::new(path_bytes)
        .map_err(|_| "Magi data path contains an invalid null byte".to_string())?;
    let acl = unsafe { acl_init(0) };
    if acl.is_null() {
        return Err(format!(
            "Failed to allocate an empty access-control list: {}",
            std::io::Error::last_os_error()
        ));
    }
    let set_result = unsafe { acl_set_file(c_path.as_ptr(), ACL_TYPE_EXTENDED, acl) };
    let set_error = if set_result == 0 {
        None
    } else {
        Some(std::io::Error::last_os_error())
    };
    unsafe {
        acl_free(acl);
    }
    if let Some(error) = set_error {
        return Err(format!(
            "Failed to remove extended access rules from {}: {error}",
            path.display()
        ));
    }
    Ok(())
}

#[cfg(windows)]
struct WindowsPrivateAcl {
    current_sid: windows_sys::Win32::Security::PSID,
    security_descriptor: windows_sys::Win32::Security::PSECURITY_DESCRIPTOR,
    dacl: *mut windows_sys::Win32::Security::ACL,
}

#[cfg(windows)]
impl WindowsPrivateAcl {
    fn new() -> Result<Self, String> {
        use std::ptr::null_mut;
        use windows_sys::Win32::Security::Authorization::{
            ConvertStringSecurityDescriptorToSecurityDescriptorW, ConvertStringSidToSidW,
            SDDL_REVISION_1,
        };
        use windows_sys::Win32::Security::GetSecurityDescriptorDacl;

        let sid = current_windows_user_sid_string()?;
        let mut current_sid = null_mut();
        let sid_wide = wide_string(&sid);
        if unsafe { ConvertStringSidToSidW(sid_wide.as_ptr(), &mut current_sid) } == 0 {
            return Err(format!(
                "Failed to decode the current Windows account identity: {}",
                std::io::Error::last_os_error()
            ));
        }

        let sddl = format!("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})");
        let sddl_wide = wide_string(&sddl);
        let mut security_descriptor = null_mut();
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl_wide.as_ptr(),
                SDDL_REVISION_1,
                &mut security_descriptor,
                null_mut(),
            )
        } == 0
        {
            unsafe {
                windows_sys::Win32::Foundation::LocalFree(current_sid);
            }
            return Err(format!(
                "Failed to create the private Windows access policy: {}",
                std::io::Error::last_os_error()
            ));
        }

        let mut dacl_present = 0;
        let mut dacl_defaulted = 0;
        let mut dacl = null_mut();
        if unsafe {
            GetSecurityDescriptorDacl(
                security_descriptor,
                &mut dacl_present,
                &mut dacl,
                &mut dacl_defaulted,
            )
        } == 0
            || dacl_present == 0
            || dacl.is_null()
        {
            unsafe {
                windows_sys::Win32::Foundation::LocalFree(current_sid);
                windows_sys::Win32::Foundation::LocalFree(security_descriptor);
            }
            return Err("Private Windows access policy has no access list".to_string());
        }

        Ok(Self {
            current_sid,
            security_descriptor,
            dacl,
        })
    }

    fn protect(&self, path: &Path) -> Result<(), String> {
        use std::ptr::{null, null_mut};
        use windows_sys::Win32::Foundation::{LocalFree, ERROR_SUCCESS};
        use windows_sys::Win32::Security::Authorization::{
            GetNamedSecurityInfoW, SetNamedSecurityInfoW, SE_FILE_OBJECT,
        };
        use windows_sys::Win32::Security::{
            EqualSid, DACL_SECURITY_INFORMATION, OWNER_SECURITY_INFORMATION,
            PROTECTED_DACL_SECURITY_INFORMATION,
        };

        let path_wide = wide_path(path);
        let mut owner = null_mut();
        let mut security_descriptor = null_mut();
        let owner_result = unsafe {
            GetNamedSecurityInfoW(
                path_wide.as_ptr(),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION,
                &mut owner,
                null_mut(),
                null_mut(),
                null_mut(),
                &mut security_descriptor,
            )
        };
        if owner_result != ERROR_SUCCESS {
            return Err(format!(
                "Failed to inspect Windows ownership for {}: error {owner_result}",
                path.display()
            ));
        }
        let owner_matches = !owner.is_null() && unsafe { EqualSid(owner, self.current_sid) } != 0;
        unsafe {
            LocalFree(security_descriptor);
        }
        if !owner_matches {
            return Err(format!(
                "Magi data path is not owned by the current account: {}",
                path.display()
            ));
        }

        let security_result = unsafe {
            SetNamedSecurityInfoW(
                path_wide.as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                null_mut(),
                null_mut(),
                self.dacl,
                null(),
            )
        };
        if security_result != ERROR_SUCCESS {
            return Err(format!(
                "Failed to restrict Windows access for {}: error {security_result}",
                path.display()
            ));
        }
        Ok(())
    }
}

#[cfg(windows)]
impl Drop for WindowsPrivateAcl {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::LocalFree(self.current_sid);
            windows_sys::Win32::Foundation::LocalFree(self.security_descriptor);
        }
    }
}

#[cfg(windows)]
fn protect_windows_entry(
    path: &Path,
    acl: &WindowsPrivateAcl,
    result: &mut PrivateDataProtectionResult,
) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Failed to inspect private Magi path: {error}"))?;
    if is_link_or_reparse(&metadata) {
        return Err(format!(
            "Magi data path must not be a link or reparse point: {}",
            path.display()
        ));
    }
    if metadata.is_file() && windows_file_link_count(path)? != 1 {
        return Err(format!(
            "Magi data file must not have external hard links: {}",
            path.display()
        ));
    }

    acl.protect(path)?;
    if metadata.is_dir() {
        result.protected_directories += 1;
        let children = read_children(path)?;
        for child in children {
            protect_windows_entry(&child, acl, result)?;
        }
    } else {
        result.protected_files += 1;
    }
    Ok(())
}

#[cfg(windows)]
fn windows_file_link_count(path: &Path) -> Result<u32, String> {
    use std::fs::File;
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    let file = File::open(path).map_err(|error| {
        format!(
            "Failed to open private Magi file {}: {error}",
            path.display()
        )
    })?;
    let mut information = BY_HANDLE_FILE_INFORMATION::default();
    if unsafe {
        GetFileInformationByHandle(
            file.as_raw_handle() as windows_sys::Win32::Foundation::HANDLE,
            &mut information,
        )
    } == 0
    {
        return Err(format!(
            "Failed to inspect private Magi file links for {}: {}",
            path.display(),
            std::io::Error::last_os_error()
        ));
    }
    Ok(information.nNumberOfLinks)
}

#[cfg(windows)]
fn current_windows_user_sid_string() -> Result<String, String> {
    use std::ptr::{null_mut, read_unaligned};
    use windows_sys::Win32::Foundation::{CloseHandle, LocalFree, HANDLE};
    use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
    use windows_sys::Win32::Security::{GetTokenInformation, TokenUser, TOKEN_QUERY, TOKEN_USER};
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    let mut token: HANDLE = null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return Err(format!(
            "Failed to open the current Windows account token: {}",
            std::io::Error::last_os_error()
        ));
    }

    let result = (|| {
        let mut required = 0u32;
        unsafe {
            GetTokenInformation(token, TokenUser, null_mut(), 0, &mut required);
        }
        if required == 0 {
            return Err(format!(
                "Failed to size the current Windows account identity: {}",
                std::io::Error::last_os_error()
            ));
        }
        let word_size = std::mem::size_of::<usize>();
        let mut buffer = vec![0usize; (required as usize).div_ceil(word_size)];
        if unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                buffer.as_mut_ptr().cast(),
                required,
                &mut required,
            )
        } == 0
        {
            return Err(format!(
                "Failed to read the current Windows account identity: {}",
                std::io::Error::last_os_error()
            ));
        }
        let token_user = unsafe { read_unaligned(buffer.as_ptr().cast::<TOKEN_USER>()) };
        let mut sid_text = null_mut();
        if unsafe { ConvertSidToStringSidW(token_user.User.Sid, &mut sid_text) } == 0 {
            return Err(format!(
                "Failed to format the current Windows account identity: {}",
                std::io::Error::last_os_error()
            ));
        }
        let mut length = 0usize;
        while unsafe { *sid_text.add(length) } != 0 {
            length += 1;
        }
        let sid = String::from_utf16(unsafe { std::slice::from_raw_parts(sid_text, length) })
            .map_err(|_| "Current Windows account identity is invalid".to_string());
        unsafe {
            LocalFree(sid_text.cast());
        }
        sid
    })();

    unsafe {
        CloseHandle(token);
    }
    result
}

#[cfg(windows)]
fn wide_string(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn wide_path(path: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;

    path.as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, PermissionsExt};
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    fn test_parent(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "magi-private-data-{label}-{}-{}",
            std::process::id(),
            TEST_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        path
    }

    fn mode(path: &Path) -> u32 {
        fs::symlink_metadata(path).unwrap().permissions().mode() & 0o777
    }

    #[test]
    fn protects_legacy_directories_files_and_executables() {
        let parent = test_parent("modes");
        let root = parent.join(".magi");
        let nested = root.join("config");
        fs::create_dir(&root).unwrap();
        fs::create_dir(&nested).unwrap();
        let file = nested.join("llm.yaml");
        let executable = nested.join("helper");
        fs::write(&file, b"secret").unwrap();
        fs::write(&executable, b"binary").unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o755)).unwrap();
        fs::set_permissions(&nested, fs::Permissions::from_mode(0o775)).unwrap();
        fs::set_permissions(&file, fs::Permissions::from_mode(0o644)).unwrap();
        fs::set_permissions(&executable, fs::Permissions::from_mode(0o755)).unwrap();

        let result = protect_magi_data_root(&root).unwrap();

        assert_eq!(mode(&root), 0o700);
        assert_eq!(mode(&nested), 0o700);
        assert_eq!(mode(&file), 0o600);
        assert_eq!(mode(&executable), 0o700);
        assert_eq!(result.protected_directories, 2);
        assert_eq!(result.protected_files, 2);
        fs::remove_dir_all(parent).unwrap();
    }

    #[test]
    fn rejects_symlinks_without_touching_the_target() {
        let parent = test_parent("symlink");
        let root = parent.join(".magi");
        let external = parent.join("external.txt");
        fs::create_dir(&root).unwrap();
        fs::write(&external, b"outside").unwrap();
        fs::set_permissions(&external, fs::Permissions::from_mode(0o644)).unwrap();
        symlink(&external, root.join("linked-secret")).unwrap();

        let error = protect_magi_data_root(&root).unwrap_err();

        assert!(error.contains("must not be a symbolic link"));
        assert_eq!(mode(&external), 0o644);
        fs::remove_dir_all(parent).unwrap();
    }

    #[test]
    fn rejects_hard_links_without_changing_the_external_name() {
        let parent = test_parent("hard-link");
        let root = parent.join(".magi");
        let external = parent.join("external.txt");
        fs::create_dir(&root).unwrap();
        fs::write(&external, b"outside").unwrap();
        fs::set_permissions(&external, fs::Permissions::from_mode(0o644)).unwrap();
        fs::hard_link(&external, root.join("linked-secret")).unwrap();

        let error = protect_magi_data_root(&root).unwrap_err();

        assert!(error.contains("must not have external hard links"));
        assert_eq!(mode(&external), 0o644);
        fs::remove_dir_all(parent).unwrap();
    }

    #[test]
    fn rejects_a_symlinked_root() {
        let parent = test_parent("root-link");
        let external = parent.join("external");
        let root = parent.join(".magi");
        fs::create_dir(&external).unwrap();
        symlink(&external, &root).unwrap();

        let error = protect_magi_data_root(&root).unwrap_err();

        assert_eq!(error, "Magi data root must be a real directory");
        fs::remove_dir_all(parent).unwrap();
    }
}
