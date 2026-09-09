// Hide the console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod connections;
mod desktop_log_history;
mod desktop_presence;
mod dmg_cleanup;
mod downloads;
mod external_url;
mod service_host;

use connections::runtime::ConnectionRuntime;
use std::thread;
use tauri::{AppHandle, Manager, State};

const DESKTOP_LOG_MAX_BYTES: u64 = 50 * 1024 * 1024;

#[tauri::command]
fn set_close_to_tray_enabled(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_close_to_tray_enabled(enabled)
}

#[tauri::command]
fn set_start_minimized(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_start_minimized(enabled)
}

#[tauri::command]
fn set_skip_quit_confirmation(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_skip_quit_confirmation(enabled)
}

#[tauri::command]
fn set_onboarding_completed(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    completed: bool,
) -> Result<(), String> {
    state.set_onboarding_completed(completed)
}

#[tauri::command]
fn apply_start_minimized(
    app: AppHandle,
    state: State<'_, desktop_presence::DesktopPresenceState>,
) -> Result<(), String> {
    if state.should_start_minimized()? {
        desktop_presence::hide_main_window(&app)?;
    }
    Ok(())
}

#[tauri::command]
fn confirm_exit_app(app: AppHandle) -> Result<(), String> {
    exit_after_disconnect(app);
    Ok(())
}

#[tauri::command]
fn cancel_exit_request() -> Result<(), String> {
    Ok(())
}

/// Open an approved external URL using the operating system's default handler.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    external_url::open(&url)
}

#[tauri::command]
fn clear_desktop_log_history(
    state: State<'_, desktop_log_history::DesktopLogRuntime>,
) -> Result<desktop_log_history::DesktopLogClearResult, String> {
    Ok(state.clear())
}

#[cfg(windows)]
mod dwm_caption {
    use std::ffi::c_void;

    pub const DWMWA_BORDER_COLOR: u32 = 34;
    pub const DWMWA_CAPTION_COLOR: u32 = 35;
    pub const DWMWA_TEXT_COLOR: u32 = 36;

    #[link(name = "dwmapi")]
    unsafe extern "system" {
        pub fn DwmSetWindowAttribute(
            hwnd: *mut c_void,
            attribute: u32,
            pv_attribute: *const c_void,
            cb_attribute: u32,
        ) -> i32;
    }
}

#[cfg(windows)]
fn apply_caption_color(window: &tauri::WebviewWindow, r: u8, g: u8, b: u8) -> Result<(), String> {
    use std::ffi::c_void;

    let raw = window.hwnd().map_err(|e| format!("hwnd: {e}"))?;
    let hwnd: *mut c_void = raw.0 as *mut c_void;

    let caption: u32 = ((b as u32) << 16) | ((g as u32) << 8) | (r as u32);
    // Relative luminance to pick legible caption text color.
    let lum = 0.299 * (r as f32) + 0.587 * (g as f32) + 0.114 * (b as f32);
    let text: u32 = if lum >= 140.0 { 0x00202020 } else { 0x00E8E8E8 };

    unsafe {
        let size = std::mem::size_of::<u32>() as u32;
        dwm_caption::DwmSetWindowAttribute(
            hwnd,
            dwm_caption::DWMWA_CAPTION_COLOR,
            &caption as *const _ as *const c_void,
            size,
        );
        dwm_caption::DwmSetWindowAttribute(
            hwnd,
            dwm_caption::DWMWA_TEXT_COLOR,
            &text as *const _ as *const c_void,
            size,
        );
        dwm_caption::DwmSetWindowAttribute(
            hwnd,
            dwm_caption::DWMWA_BORDER_COLOR,
            &caption as *const _ as *const c_void,
            size,
        );
    }
    Ok(())
}

#[tauri::command]
fn set_window_caption_color(
    window: tauri::WebviewWindow,
    r: u8,
    g: u8,
    b: u8,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        return apply_caption_color(&window, r, g, b);
    }
    #[cfg(not(windows))]
    {
        let _ = (window, r, g, b);
        Ok(())
    }
}

fn disconnect_for_app_exit(app: &AppHandle) {
    let state: State<'_, ConnectionRuntime> = app.state();
    if let Err(err) = state.shutdown() {
        log::warn!("Failed to disconnect service during app exit: {err}");
    }
}

fn hide_main_window_for_exit(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if let Err(err) = window.hide() {
            log::warn!("Failed to hide main window during app exit: {err}");
        }
    }
}

fn exit_after_disconnect(app: AppHandle) {
    hide_main_window_for_exit(&app);
    thread::spawn(move || {
        let state: State<'_, ConnectionRuntime> = app.state();
        if let Err(err) = state.shutdown() {
            log::warn!("Failed to disconnect service during confirmed app exit: {err}");
        }
        app.exit(0);
    });
}

#[cfg(not(target_os = "macos"))]
fn disable_native_window_decorations(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        log::warn!("Main window not found while disabling native decorations");
        return;
    };
    if let Err(err) = window.set_decorations(false) {
        log::warn!("Failed to disable native window decorations: {err}");
    }
}

fn main() {
    let log_level = if cfg!(debug_assertions) {
        log::LevelFilter::Debug
    } else {
        log::LevelFilter::Info
    };
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::new().skip_logger().build())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            let _ = desktop_presence::restore_main_window(app);
        }))
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(ConnectionRuntime::default())
        .manage(desktop_presence::DesktopPresenceState::default())
        .setup(move |app| {
            let client_directory = app.path().app_config_dir()?;
            magi_platform::private_data::protect_magi_data_root(&client_directory).map_err(std::io::Error::other)?;
            let log_directory = app.path().app_log_dir()?;
            magi_platform::private_data::protect_magi_data_root(&log_directory).map_err(std::io::Error::other)?;
            app.manage(desktop_log_history::DesktopLogRuntime::install(log_directory, DESKTOP_LOG_MAX_BYTES, log_level).map_err(std::io::Error::other)?);
            let connection_directory = app.path().app_config_dir()?.join("connections");
            app.manage(connections::Connections::open(&connection_directory).map_err(std::io::Error::other)?);
            connections::runtime::start_monitor(app.handle().clone());
            let current_version = app.package_info().version.to_string();
            log::info!(
                "Magi desktop setup starting (version={current_version}, log_level={log_level:?})"
            );
            log::info!("tauri updater plugin enabled for desktop runtime");

            #[cfg(target_os = "macos")]
            dmg_cleanup::detach_installer_volume_after_launch();

            if let Err(err) = desktop_presence::setup(app.handle()) {
                log::warn!(
                    "Optional desktop presence setup is unavailable; continuing without tray integration: {err}"
                );
            }

            #[cfg(not(target_os = "macos"))]
            disable_native_window_decorations(app.handle());

            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                let state: State<'_, desktop_presence::DesktopPresenceState> = window.state();
                match state.close_action() {
                    Ok(desktop_presence::CloseAction::HideToTray) => {
                        api.prevent_close();
                        let _ = desktop_presence::hide_main_window(window.app_handle());
                    }
                    Ok(desktop_presence::CloseAction::QuitImmediately) => {
                        api.prevent_close();
                        exit_after_disconnect(window.app_handle().clone());
                    }
                    Ok(desktop_presence::CloseAction::RequestQuitConfirmation) => {
                        api.prevent_close();
                        let _ = desktop_presence::emit_quit_requested(window.app_handle());
                    }
                    Err(_) => {}
                }
            }
            tauri::WindowEvent::Destroyed => {
                let state: State<'_, ConnectionRuntime> = window.state();
                let _ = state.shutdown();
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            downloads::download_portability_file,
            connections::runtime::list_connection_profiles,
            connections::runtime::pair_center,
            connections::runtime::select_connection_profile,
            connections::runtime::forget_connection_profile,
            connections::runtime::renew_center_session,
            connections::runtime::connect_active_profile,
            connections::runtime::poll_connection_startup,
            connections::runtime::disconnect_service,
            connections::runtime::read_connection_startup_diagnostics,
            set_close_to_tray_enabled,
            set_start_minimized,
            set_skip_quit_confirmation,
            set_onboarding_completed,
            apply_start_minimized,
            confirm_exit_app,
            cancel_exit_request,
            open_url,
            clear_desktop_log_history,
            set_window_caption_color
        ])
        .build(tauri::generate_context!())
        .expect("failed to build Magi desktop application");

    app.run(|app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
            hide_main_window_for_exit(app_handle);
            disconnect_for_app_exit(app_handle);
        }
        _ => {}
    });
}
