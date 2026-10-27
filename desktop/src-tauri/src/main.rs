#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::{
    env, fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::Command,
    ptr, thread,
    time::{Duration, Instant},
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    utils::config::WebviewUrl,
    webview::{NewWindowResponse, WebviewWindowBuilder},
    Manager, WindowEvent,
};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const JARVIS_URL: &str = "http://127.0.0.1:8765";
const JARVIS_ADDRESS: &str = "127.0.0.1:8765";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(180);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(35);
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
const MB_YESNOCANCEL: u32 = 0x0000_0003;
#[cfg(windows)]
const MB_ICONQUESTION: u32 = 0x0000_0020;
#[cfg(windows)]
const MB_ICONERROR: u32 = 0x0000_0010;
#[cfg(windows)]
const MB_SETFOREGROUND: u32 = 0x0001_0000;
#[cfg(windows)]
const MB_TASKMODAL: u32 = 0x0000_2000;
#[cfg(windows)]
const IDYES: i32 = 6;
#[cfg(windows)]
const IDNO: i32 = 7;

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(
        window: *mut std::ffi::c_void,
        text: *const u16,
        caption: *const u16,
        kind: u32,
    ) -> i32;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CloseChoice {
    KeepCore,
    StopEverything,
    Cancel,
}

#[derive(Serialize)]
struct BootStatus {
    ready: bool,
    url: &'static str,
    detail: String,
}

fn project_root() -> PathBuf {
    env::var_os("JARVIS_PROJECT_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("JARVIS_PROJECT_ROOT")))
}

fn health_ready() -> bool {
    let Ok(address) = JARVIS_ADDRESS.parse::<SocketAddr>() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(700)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    if stream
        .write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response_is_healthy(&response)
}

fn response_is_healthy(response: &str) -> bool {
    response.starts_with("HTTP/1.1 200")
        && (response.contains("\"status\":\"ok\"") || response.contains("\"status\": \"ok\""))
}

fn launch_supervisor(root: &Path) -> Result<(), String> {
    let python = root.join(".venv").join("Scripts").join("pythonw.exe");
    let supervisor = root.join("scripts").join("supervise_assistant.py");
    if !python.is_file() {
        return Err(format!(
            "No encontré el entorno de Jarvis en {}.",
            python.display()
        ));
    }
    if !supervisor.is_file() {
        return Err(format!(
            "No encontré el supervisor en {}.",
            supervisor.display()
        ));
    }
    let _ = fs::remove_file(root.join(".data").join("supervisor.shutdown"));
    let _ = fs::remove_file(root.join(".data").join("server.shutdown"));
    let mut command = Command::new(python);
    command.arg(supervisor).current_dir(root);
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Windows no pudo iniciar el supervisor: {error}"))
}

fn close_choice_from_dialog_result(result: i32) -> CloseChoice {
    match result {
        IDYES => CloseChoice::StopEverything,
        IDNO => CloseChoice::KeepCore,
        _ => CloseChoice::Cancel,
    }
}

#[cfg(windows)]
fn ask_close_choice() -> CloseChoice {
    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    let title = wide("Cerrar Jarvis");
    let message = wide(
        "¿Cómo quieres cerrar Jarvis?\r\n\r\n\
         Sí — cerrar Jarvis completamente y detener su núcleo. El celular quedará desconectado.\r\n\r\n\
         No — cerrar la interfaz y mantener el núcleo en segundo plano para correo, automatizaciones y el celular.\r\n\r\n\
         Cancelar — volver a Jarvis sin cerrar nada.",
    );
    // SAFETY: the UTF-16 buffers are NUL terminated and remain alive for the duration of the call.
    let result = unsafe {
        MessageBoxW(
            ptr::null_mut(),
            message.as_ptr(),
            title.as_ptr(),
            MB_YESNOCANCEL | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TASKMODAL,
        )
    };
    close_choice_from_dialog_result(result)
}

#[cfg(not(windows))]
fn ask_close_choice() -> CloseChoice {
    CloseChoice::Cancel
}

fn prepare_interface_for_close(app: &tauri::AppHandle) {
    if let Some(webview) = app.get_webview_window("main") {
        let _ = webview.eval("window.jarvisDesktop?.prepareForHide();");
    }
}

fn request_full_shutdown() -> Result<(), String> {
    let data_dir = project_root().join(".data");
    fs::create_dir_all(&data_dir)
        .map_err(|error| format!("No pude preparar el cierre de Jarvis: {error}"))?;
    let request = data_dir.join("supervisor.shutdown");
    fs::write(&request, format!("desktop:{}", std::process::id()))
        .map_err(|error| format!("No pude solicitar el cierre de Jarvis: {error}"))?;

    let started = Instant::now();
    while started.elapsed() < SHUTDOWN_TIMEOUT {
        if !health_ready() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }
    let _ = fs::remove_file(request);
    Err(
        "El núcleo no confirmó su cierre. Jarvis quedó abierto para evitar un estado incierto."
            .into(),
    )
}

#[cfg(windows)]
fn show_close_error(detail: &str) {
    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }
    let title = wide("Jarvis sigue activo");
    let message = wide(detail);
    // SAFETY: the UTF-16 buffers are NUL terminated and valid during the synchronous call.
    unsafe {
        MessageBoxW(
            ptr::null_mut(),
            message.as_ptr(),
            title.as_ptr(),
            MB_ICONERROR | MB_SETFOREGROUND | MB_TASKMODAL,
        );
    }
}

#[cfg(not(windows))]
fn show_close_error(_detail: &str) {}

fn close_with_choice(app: &tauri::AppHandle, choice: CloseChoice) {
    match choice {
        CloseChoice::KeepCore => {
            prepare_interface_for_close(app);
            app.exit(0);
        }
        CloseChoice::StopEverything => {
            prepare_interface_for_close(app);
            match request_full_shutdown() {
                Ok(()) => app.exit(0),
                Err(detail) => show_close_error(&detail),
            }
        }
        CloseChoice::Cancel => {}
    }
}

fn ensure_jarvis_sync() -> BootStatus {
    if health_ready() {
        return BootStatus {
            ready: true,
            url: JARVIS_URL,
            detail: "Jarvis ya estaba disponible.".into(),
        };
    }

    let root = project_root();
    if let Err(detail) = launch_supervisor(&root) {
        return BootStatus {
            ready: false,
            url: JARVIS_URL,
            detail,
        };
    }

    let started = Instant::now();
    while started.elapsed() < STARTUP_TIMEOUT {
        if health_ready() {
            return BootStatus {
                ready: true,
                url: JARVIS_URL,
                detail: "El núcleo de Jarvis está listo.".into(),
            };
        }
        thread::sleep(Duration::from_secs(1));
    }
    BootStatus {
        ready: false,
        url: JARVIS_URL,
        detail: "El supervisor inició, pero Jarvis no respondió en tres minutos. Revisa el diagnóstico local.".into(),
    }
}

#[tauri::command]
async fn ensure_jarvis() -> BootStatus {
    match tauri::async_runtime::spawn_blocking(ensure_jarvis_sync).await {
        Ok(status) => status,
        Err(error) => BootStatus {
            ready: false,
            url: JARVIS_URL,
            detail: format!("No pude completar el arranque: {error}"),
        },
    }
}

#[tauri::command]
fn open_diagnostics() -> Result<(), String> {
    let log = project_root().join(".data").join("supervised-server.log");
    let target = if log.exists() {
        log
    } else {
        project_root().join(".data")
    };
    tauri_plugin_opener::open_path(target, None::<&str>).map_err(|error| error.to_string())
}

fn allowed_navigation(url: &tauri::Url) -> bool {
    if matches!(url.scheme(), "tauri" | "about" | "blob") {
        return true;
    }
    if url.host_str() == Some("tauri.localhost") {
        return true;
    }
    url.scheme() == "http"
        && matches!(url.host_str(), Some("127.0.0.1" | "localhost"))
        && url.port_or_known_default() == Some(8765)
}

fn open_appa() {
    let Some(profile) = env::var_os("USERPROFILE") else {
        return;
    };
    let executable = PathBuf::from(profile)
        .join("Desktop")
        .join("Appa Jarvis.exe");
    if executable.is_file() {
        let mut command = Command::new(executable);
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW);
        let _ = command.spawn();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(
            |app, _arguments, _cwd| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            },
        ))
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![ensure_jarvis, open_diagnostics])
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    close_with_choice(window.app_handle(), ask_close_choice());
                }
            }
        })
        .setup(|app| {
            let navigation_handle = app.handle().clone();
            let new_window_handle = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Jarvis")
                .inner_size(1440.0, 900.0)
                .min_inner_size(980.0, 650.0)
                .resizable(true)
                .center()
                .initialization_script("window.__JARVIS_DESKTOP__ = true;")
                .on_navigation(move |url| {
                    if allowed_navigation(url) {
                        true
                    } else {
                        use tauri_plugin_opener::OpenerExt;
                        let _ = navigation_handle
                            .opener()
                            .open_url(url.as_str(), None::<&str>);
                        false
                    }
                })
                .on_new_window(move |url, _features| {
                    use tauri_plugin_opener::OpenerExt;
                    let _ = new_window_handle
                        .opener()
                        .open_url(url.as_str(), None::<&str>);
                    NewWindowResponse::Deny
                })
                .build()?;

            let show = MenuItem::with_id(app, "show", "Mostrar Jarvis", true, None::<&str>)?;
            let reload = MenuItem::with_id(app, "reload", "Recargar interfaz", true, None::<&str>)?;
            let appa = MenuItem::with_id(app, "appa", "Abrir Appa", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "Ocultar ventana", true, None::<&str>)?;
            let background = MenuItem::with_id(
                app,
                "background",
                "Cerrar interfaz (Jarvis sigue activo)",
                true,
                None::<&str>,
            )?;
            let quit_all = MenuItem::with_id(
                app,
                "quit_all",
                "Cerrar Jarvis completamente...",
                true,
                None::<&str>,
            )?;
            let menu =
                Menu::with_items(app, &[&show, &reload, &appa, &hide, &background, &quit_all])?;
            let mut tray = TrayIconBuilder::new()
                .tooltip("Jarvis")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                    "reload" => {
                        if let Some(window) = app.get_webview_window("main") {
                            if let Ok(url) = window.url() {
                                let _ = window.navigate(url);
                            }
                            let _ = window.show();
                        }
                    }
                    "appa" => open_appa(),
                    "hide" => {
                        prepare_interface_for_close(app);
                        if let Some(window) = app.get_webview_window("main") {
                            if let Ok(loader_url) = "http://tauri.localhost/index.html".parse() {
                                let _ = window.navigate(loader_url);
                            }
                            let _ = window.hide();
                        }
                    }
                    "background" => close_with_choice(app, CloseChoice::KeepCore),
                    "quit_all" => close_with_choice(app, ask_close_choice()),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                });
            if let Some(icon) = app.default_window_icon().cloned() {
                tray = tray.icon(icon);
            }
            tray.build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run Jarvis desktop");
}

#[cfg(test)]
mod tests {
    use super::{
        allowed_navigation, close_choice_from_dialog_result, project_root, response_is_healthy,
        CloseChoice,
    };

    #[test]
    fn accepts_only_jarvis_local_navigation() {
        assert!(allowed_navigation(
            &"http://127.0.0.1:8765/organizer".parse().unwrap()
        ));
        assert!(allowed_navigation(
            &"http://localhost:8765/mail".parse().unwrap()
        ));
        assert!(!allowed_navigation(
            &"https://accounts.google.com/".parse().unwrap()
        ));
        assert!(!allowed_navigation(
            &"http://127.0.0.1:9999/".parse().unwrap()
        ));
    }

    #[test]
    fn accepts_only_successful_jarvis_health_response() {
        assert!(response_is_healthy(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!response_is_healthy(
            "HTTP/1.1 503 Service Unavailable\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!response_is_healthy(
            "HTTP/1.1 200 OK\r\n\r\n{\"status\":\"error\"}"
        ));
    }

    #[test]
    fn compiled_project_root_contains_the_supervisor() {
        assert!(project_root()
            .join("scripts")
            .join("supervise_assistant.py")
            .is_file());
    }

    #[test]
    fn close_dialog_maps_every_safe_choice() {
        assert_eq!(
            close_choice_from_dialog_result(6),
            CloseChoice::StopEverything
        );
        assert_eq!(close_choice_from_dialog_result(7), CloseChoice::KeepCore);
        assert_eq!(close_choice_from_dialog_result(2), CloseChoice::Cancel);
        assert_eq!(close_choice_from_dialog_result(0), CloseChoice::Cancel);
    }
}
