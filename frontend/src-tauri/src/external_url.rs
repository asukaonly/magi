use url::Url;

#[cfg_attr(not(test), allow(dead_code))]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Platform {
    Macos,
    Windows,
    Linux,
    Unsupported,
}

fn current_platform() -> Platform {
    #[cfg(target_os = "macos")]
    {
        return Platform::Macos;
    }
    #[cfg(target_os = "windows")]
    {
        return Platform::Windows;
    }
    #[cfg(target_os = "linux")]
    {
        return Platform::Linux;
    }
    #[allow(unreachable_code)]
    Platform::Unsupported
}

fn validate_for_platform(raw_url: &str, platform: Platform) -> Result<String, String> {
    if raw_url.chars().any(char::is_control) {
        return Err("URL contains control characters".to_string());
    }

    let candidate = raw_url.trim();
    if candidate.is_empty() {
        return Err("URL is empty".to_string());
    }

    let parsed = Url::parse(candidate).map_err(|_| "URL is invalid".to_string())?;
    let scheme = parsed.scheme();

    match scheme {
        "http" | "https" => {
            if parsed.host_str().is_none() {
                return Err("Web URL must include a host".to_string());
            }
            if !parsed.username().is_empty() || parsed.password().is_some() {
                return Err("Web URL must not include credentials".to_string());
            }
        }
        "mailto" => {
            if parsed.path().trim().is_empty() {
                return Err("Email URL must include a recipient".to_string());
            }
        }
        "x-apple.systempreferences" if platform == Platform::Macos => {}
        "ms-settings" if platform == Platform::Windows => {}
        _ => return Err(format!("URL scheme is not allowed: {scheme}")),
    }

    Ok(parsed.into())
}

pub fn open(raw_url: &str) -> Result<(), String> {
    let url = validate_for_platform(raw_url, current_platform())?;

    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("/usr/bin/open")
            .arg(&url)
            .spawn()
            .map_err(|error| format!("Failed to open URL: {error}"))?;
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        use std::iter::once;
        use std::ptr;
        use windows_sys::Win32::UI::Shell::ShellExecuteW;
        use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

        let wide_url = url.encode_utf16().chain(once(0)).collect::<Vec<_>>();
        let result = unsafe {
            ShellExecuteW(
                ptr::null_mut(),
                ptr::null(),
                wide_url.as_ptr(),
                ptr::null(),
                ptr::null(),
                SW_SHOWNORMAL,
            )
        } as isize;

        if result <= 32 {
            return Err(format!("Failed to open URL: system error {result}"));
        }
        return Ok(());
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|error| format!("Failed to open URL: {error}"))?;
        return Ok(());
    }

    #[allow(unreachable_code)]
    Err("Unsupported platform".to_string())
}

#[cfg(test)]
mod tests {
    use super::{validate_for_platform, Platform};

    #[test]
    fn common_external_urls_are_allowed() {
        for platform in [Platform::Macos, Platform::Windows, Platform::Linux] {
            assert_eq!(
                validate_for_platform("https://example.com/docs?q=magi&lang=zh", platform).unwrap(),
                "https://example.com/docs?q=magi&lang=zh"
            );
            assert_eq!(
                validate_for_platform("http://localhost:8000/path", platform).unwrap(),
                "http://localhost:8000/path"
            );
            assert_eq!(
                validate_for_platform("mailto:user@example.com?subject=Magi", platform).unwrap(),
                "mailto:user@example.com?subject=Magi"
            );
        }
    }

    #[test]
    fn system_settings_urls_are_limited_to_the_current_platform() {
        let macos_url = "x-apple.systempreferences:com.apple.preference.security?Privacy_Photos";
        let windows_url = "ms-settings:privacy-webcam";

        assert_eq!(
            validate_for_platform(macos_url, Platform::Macos).unwrap(),
            macos_url
        );
        assert_eq!(
            validate_for_platform("x-apple.systempreferences:", Platform::Macos).unwrap(),
            "x-apple.systempreferences:"
        );
        assert!(validate_for_platform(windows_url, Platform::Macos).is_err());

        assert_eq!(
            validate_for_platform(windows_url, Platform::Windows).unwrap(),
            windows_url
        );
        assert_eq!(
            validate_for_platform("ms-settings:", Platform::Windows).unwrap(),
            "ms-settings:"
        );
        assert!(validate_for_platform(macos_url, Platform::Windows).is_err());

        assert!(validate_for_platform(macos_url, Platform::Linux).is_err());
        assert!(validate_for_platform(windows_url, Platform::Linux).is_err());
    }

    #[test]
    fn empty_control_character_and_relative_urls_are_rejected() {
        for raw_url in [
            "",
            "   ",
            "https://example.com/\ncalculator",
            "mailto:user@example.com\0",
            "example.com/path",
            "/relative/path",
        ] {
            assert!(
                validate_for_platform(raw_url, Platform::Windows).is_err(),
                "{raw_url:?} must be rejected"
            );
        }
    }

    #[test]
    fn unsupported_and_incomplete_urls_are_rejected() {
        for raw_url in [
            "file:///C:/Windows/System32/calc.exe",
            "javascript:alert(1)",
            "data:text/html,hello",
            "powershell:Start-Process calc",
            "https://",
            "https://user:password@example.com",
            "mailto:",
        ] {
            assert!(
                validate_for_platform(raw_url, Platform::Windows).is_err(),
                "{raw_url:?} must be rejected"
            );
        }
    }

    #[test]
    fn shell_metacharacters_remain_url_data() {
        let normalized = validate_for_platform(
            "https://example.com/search?q=a&next=b|c\"d",
            Platform::Windows,
        )
        .unwrap();

        assert_eq!(normalized, "https://example.com/search?q=a&next=b|c%22d");
    }

    #[test]
    fn unsupported_platform_has_no_system_settings_scheme() {
        assert!(validate_for_platform("ms-settings:", Platform::Unsupported).is_err());
        assert!(
            validate_for_platform("x-apple.systempreferences:", Platform::Unsupported).is_err()
        );
    }
}
