//! Desktop Butler shell: two windows (floating butler + dashboard), a menu-bar
//! icon, and a supervised Python backend that does the arXiv work.

use std::fs::{self, File};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_window_state::StateFlags;

const BACKEND_PORT: u16 = 8765;

/// The backend child process we started (None if one was already running).
struct Backend(Mutex<Option<Child>>);

/// Repo root: `BUTLER_REPO` if set, otherwise the Cadbury checkout this app was built from.
fn repo_root() -> PathBuf {
    if let Ok(p) = std::env::var("BUTLER_REPO") {
        return PathBuf::from(p);
    }
    let compiled = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    compiled.canonicalize().unwrap_or(compiled)
}

fn backend_up() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn python_path(root: &PathBuf) -> PathBuf {
    if let Ok(p) = std::env::var("BUTLER_PYTHON") {
        return PathBuf::from(p);
    }
    let venv = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    if venv.exists() {
        venv
    } else {
        PathBuf::from("python3")
    }
}

fn spawn_backend(app: &AppHandle) -> Option<Child> {
    if backend_up() {
        eprintln!("[butler] backend already running on port {BACKEND_PORT}");
        return None;
    }
    let root = repo_root();
    let script = root.join("services").join("butler").join("butler_main.py");
    let python = python_path(&root);

    // stdout/stderr of the backend go to the app's log folder (startup errors land here)
    let log_dir = app.path().app_log_dir().unwrap_or_else(|_| std::env::temp_dir());
    let _ = fs::create_dir_all(&log_dir);
    let out = File::create(log_dir.join("backend.out.log")).ok();
    let err = out.as_ref().and_then(|f| f.try_clone().ok());

    let mut cmd = Command::new(&python);
    cmd.arg(&script).current_dir(&root).stdin(Stdio::null());
    cmd.stdout(out.map(Stdio::from).unwrap_or_else(Stdio::null));
    cmd.stderr(err.map(Stdio::from).unwrap_or_else(Stdio::null));
    match cmd.spawn() {
        Ok(child) => {
            eprintln!("[butler] started backend: {} {}", python.display(), script.display());
            Some(child)
        }
        Err(e) => {
            eprintln!("[butler] could not start backend with {}: {e}", python.display());
            None
        }
    }
}

/// Restart the backend if it dies (the "auto-restart" requirement).
fn supervise_backend(app: AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(30));
        let state = app.state::<Backend>();
        let mut guard = state.0.lock().unwrap();
        let exited = match guard.as_mut() {
            Some(child) => matches!(child.try_wait(), Ok(Some(_))),
            None => true,
        };
        if exited && !backend_up() {
            eprintln!("[butler] backend not running; restarting");
            *guard = spawn_backend(&app);
        }
    });
}

fn stop_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<Backend>() {
        if let Some(mut child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn show_window(app: &AppHandle, label: &str) {
    if let Some(w) = app.get_webview_window(label) {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

/// Roaming speed multiplier; BUTLER_BEHAVIOR_FAST=1 makes him busier (for testing).
#[tauri::command]
fn behavior_speed() -> f64 {
    match std::env::var("BUTLER_BEHAVIOR_FAST").as_deref() {
        Ok("1") | Ok("true") => 6.0,
        _ => 1.0,
    }
}

#[tauri::command]
fn backend_info() -> serde_json::Value {
    let root = repo_root();
    serde_json::json!({
        "repo": root.display().to_string(),
        "python": python_path(&root).display().to_string(),
        "port": BACKEND_PORT,
        "up": backend_up(),
    })
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show butler", true, None::<&str>)?;
    let open = MenuItem::with_id(app, "open", "Open briefing", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Desktop Butler", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&show, &open, &sep, &quit])?;
    let mut tray = TrayIconBuilder::with_id("butler-tray")
        .tooltip("Desktop Butler")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_window(app, "butler"),
            "open" => {
                show_window(app, "dashboard");
                let _ = app.emit("dashboard-section", "briefing");
            }
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // a second launch (e.g. login item + manual open) just shows the existing butler
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_window(app, "butler")))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, None))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::POSITION | StateFlags::SIZE)
                // notes are short-lived; only the butler and dashboard remember where they were
                .with_filter(|label| !label.starts_with("note-"))
                .build(),
        )
        .invoke_handler(tauri::generate_handler![quit_app, backend_info, behavior_speed])
        .setup(|app| {
            // menu-bar app: no Dock icon on macOS
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let handle = app.handle().clone();
            app.manage(Backend(Mutex::new(spawn_backend(&handle))));
            supervise_backend(handle.clone());
            build_tray(&handle)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // closing the butler or dashboard hides it; quitting is explicit (menu / tray).
            // Notes close for real.
            if window.label().starts_with("note-") {
                return;
            }
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Desktop Butler");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(handle);
        }
    });
}
