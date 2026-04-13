use std::sync::Mutex;

use tauri::{
    image::Image,
    menu::{MenuBuilder, MenuEvent},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, Runtime,
};

const MAIN_WINDOW_LABEL: &str = "main";
const TRAY_ID: &str = "desktop-presence";
const MENU_OPEN_ID: &str = "desktop-open";
const MENU_SETTINGS_ID: &str = "desktop-settings";
const MENU_QUIT_ID: &str = "desktop-quit";

pub const OPEN_SETTINGS_EVENT: &str = "desktop-presence://open-settings";
pub const QUIT_REQUESTED_EVENT: &str = "desktop-presence://quit-requested";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CloseAction {
    HideToTray,
    RequestQuitConfirmation,
}

#[derive(Debug)]
struct DesktopPresenceRuntime {
    close_to_tray_enabled: bool,
    start_minimized: bool,
}

impl Default for DesktopPresenceRuntime {
    fn default() -> Self {
        Self {
            close_to_tray_enabled: true,
            start_minimized: false,
        }
    }
}

#[derive(Default)]
pub struct DesktopPresenceState {
    runtime: Mutex<DesktopPresenceRuntime>,
}

impl DesktopPresenceState {
    pub fn set_close_to_tray_enabled(&self, enabled: bool) -> Result<(), String> {
        let mut runtime = self
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire desktop presence lock".to_string())?;
        runtime.close_to_tray_enabled = enabled;
        Ok(())
    }

    pub fn set_start_minimized(&self, enabled: bool) -> Result<(), String> {
        let mut runtime = self
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire desktop presence lock".to_string())?;
        runtime.start_minimized = enabled;
        Ok(())
    }

    pub fn should_start_minimized(&self) -> Result<bool, String> {
        let runtime = self
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire desktop presence lock".to_string())?;
        Ok(runtime.start_minimized)
    }

    pub fn close_action(&self) -> Result<CloseAction, String> {
        let runtime = self
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire desktop presence lock".to_string())?;
        Ok(if runtime.close_to_tray_enabled {
            CloseAction::HideToTray
        } else {
            CloseAction::RequestQuitConfirmation
        })
    }
}

#[cfg(target_os = "macos")]
fn macos_template_icon_path() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("icons")
        .join("tray-template-macos.png")
}

#[cfg(target_os = "macos")]
fn load_tray_icon() -> Result<Image<'static>, String> {
    Image::from_path(macos_template_icon_path())
        .map(|image| image.to_owned())
        .map_err(|err| format!("Failed to load macOS tray template icon: {err}"))
}

pub fn setup<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let menu = MenuBuilder::new(app)
        .text(MENU_OPEN_ID, "Open")
        .text(MENU_SETTINGS_ID, "Settings")
        .text(MENU_QUIT_ID, "Quit")
        .build()
        .map_err(|err| format!("Failed to build desktop presence menu: {err}"))?;

    let mut tray_builder = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip("Magi")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            handle_menu_event(app, &event);
        })
        .on_tray_icon_event(|tray, event| {
            handle_tray_event(tray, &event);
        });

    #[cfg(target_os = "macos")]
    {
        tray_builder = tray_builder.icon(load_tray_icon()?);
    }

    #[cfg(target_os = "macos")]
    {
        tray_builder = tray_builder.icon_as_template(true);
    }

    #[cfg(not(target_os = "macos"))]
    {
        if let Some(icon) = app.default_window_icon().cloned() {
            tray_builder = tray_builder.icon(icon);
        }
    }

    tray_builder
        .build(app)
        .map_err(|err| format!("Failed to create desktop presence tray icon: {err}"))?;

    Ok(())
}

pub fn hide_main_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or_else(|| "Main window not found".to_string())?;
    window
        .hide()
        .map_err(|err| format!("Failed to hide main window: {err}"))?;
    Ok(())
}

pub fn restore_main_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or_else(|| "Main window not found".to_string())?;
    let _ = window.unminimize();
    window
        .show()
        .map_err(|err| format!("Failed to show main window: {err}"))?;
    window
        .set_focus()
        .map_err(|err| format!("Failed to focus main window: {err}"))?;
    Ok(())
}

pub fn emit_open_settings<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    app.emit(OPEN_SETTINGS_EVENT, ())
        .map_err(|err| format!("Failed to emit desktop open-settings event: {err}"))
}

pub fn emit_quit_requested<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    app.emit(QUIT_REQUESTED_EVENT, ())
        .map_err(|err| format!("Failed to emit desktop quit-requested event: {err}"))
}

fn handle_menu_event<R: Runtime>(app: &AppHandle<R>, event: &MenuEvent) {
    match event.id().as_ref() {
        MENU_OPEN_ID => {
            let _ = restore_main_window(app);
        }
        MENU_SETTINGS_ID => {
            let _ = restore_main_window(app);
            let _ = emit_open_settings(app);
        }
        MENU_QUIT_ID => {
            let _ = emit_quit_requested(app);
        }
        _ => {}
    }
}

fn handle_tray_event<R: Runtime>(tray: &tauri::tray::TrayIcon<R>, event: &TrayIconEvent) {
    match event {
        TrayIconEvent::Click {
            button: MouseButton::Left,
            button_state: MouseButtonState::Up,
            ..
        }
        | TrayIconEvent::DoubleClick {
            button: MouseButton::Left,
            ..
        } => {
            let _ = restore_main_window(tray.app_handle());
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::{CloseAction, DesktopPresenceState};

    #[test]
    fn desktop_presence_defaults_to_hiding_on_close() {
        let state = DesktopPresenceState::default();

        assert_eq!(state.close_action().unwrap(), CloseAction::HideToTray);
    }

    #[test]
    fn desktop_presence_can_switch_to_quit_confirmation_mode() {
        let state = DesktopPresenceState::default();
        state.set_close_to_tray_enabled(false).unwrap();

        assert_eq!(
            state.close_action().unwrap(),
            CloseAction::RequestQuitConfirmation
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn desktop_presence_includes_a_macos_template_icon_asset() {
        let icon_path = super::macos_template_icon_path();

        let icon_bytes =
            std::fs::read(&icon_path).expect("expected macOS tray template icon asset");
        assert!(icon_bytes.starts_with(&[0x89, b'P', b'N', b'G']));
        let image = tauri::image::Image::from_path(&icon_path)
            .expect("expected macOS tray template icon to load");
        assert!(image.width() > 0);
        assert!(image.height() > 0);
    }
}
