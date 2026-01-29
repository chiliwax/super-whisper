use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::time::Instant;
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

// Dev mode fallback paths (only used if sidecar not available)
const DEV_PYTHON_PATH: &str = "/Users/thibault/Documents/WORK/super-whisper/.venv/bin/python";
const DEV_PROJECT_PATH: &str = "/Users/thibault/Documents/WORK/super-whisper";

fn is_dev_mode() -> bool {
    cfg!(debug_assertions)
}

fn get_sidecar_path(app: &AppHandle) -> Option<PathBuf> {
    // In bundled app, sidecar is in the same directory as the main executable (Contents/MacOS/)
    // Tauri strips the target triple suffix when bundling
    
    // First, try the bundled location (no suffix)
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            let sidecar_name = if cfg!(target_os = "windows") {
                "superwhisper-backend.exe"
            } else {
                "superwhisper-backend"
            };
            let bundled_path = exe_dir.join(sidecar_name);
            if bundled_path.exists() {
                log::info!("Found bundled sidecar at: {:?}", bundled_path);
                return Some(bundled_path);
            }
        }
    }
    
    // Fallback: try with target triple (for dev builds)
    let target = if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            "superwhisper-backend-aarch64-apple-darwin"
        } else {
            "superwhisper-backend-x86_64-apple-darwin"
        }
    } else if cfg!(target_os = "windows") {
        "superwhisper-backend-x86_64-pc-windows-msvc.exe"
    } else {
        "superwhisper-backend-x86_64-unknown-linux-gnu"
    };
    
    // Try in binaries folder (for dev)
    let dev_path = PathBuf::from(DEV_PROJECT_PATH)
        .join("src-tauri")
        .join("binaries")
        .join(target);
    
    if dev_path.exists() {
        log::info!("Found dev sidecar at: {:?}", dev_path);
        return Some(dev_path);
    }
    
    log::warn!("Sidecar not found");
    None
}

fn get_config_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("super-whisper");
    fs::create_dir_all(&config_dir).ok();
    config_dir.join("config.json")
}

fn load_config_from_file() -> Config {
    let path = get_config_path();
    if let Ok(contents) = fs::read_to_string(&path) {
        if let Ok(config) = serde_json::from_str(&contents) {
            log::info!("Loaded config from {:?}", path);
            return config;
        }
    }
    log::info!("Using default config");
    Config::default()
}

fn save_config_to_file(config: &Config) -> Result<(), String> {
    let path = get_config_path();
    let json = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())?;
    log::info!("Saved config to {:?}", path);
    Ok(())
}

// Backend state
struct BackendState {
    is_recording: bool,
    recording_start: Option<Instant>,
    daemon_stdin: Option<std::process::ChildStdin>,
    config: Config,
    model_loaded: bool,
}

impl Default for BackendState {
    fn default() -> Self {
        Self {
            is_recording: false,
            recording_start: None,
            daemon_stdin: None,
            config: load_config_from_file(),
            model_loaded: false,
        }
    }
}

type SharedState = Arc<Mutex<BackendState>>;

// Config structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub device_id: Option<i32>,
    pub sample_rate: i32,
    pub model: String,
    pub use_vad: bool,
    pub hotkey: String,
    pub output_mode: String,
    pub typing_speed: f32,
    pub providers: Vec<String>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            device_id: None,
            sample_rate: 16000,
            model: "nemo-parakeet-tdt-0.6b-v3".to_string(),
            use_vad: false,
            hotkey: "alt+space".to_string(),
            output_mode: "clipboard".to_string(),
            typing_speed: 0.01,
            providers: vec!["CPUExecutionProvider".to_string()],
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDevice {
    pub id: i32,
    pub name: String,
    pub is_default: bool,
}

fn get_sidecar_or_python_command(app: Option<&AppHandle>) -> (String, Vec<String>) {
    // Try sidecar first
    if let Some(app) = app {
        if let Some(sidecar_path) = get_sidecar_path(app) {
            if sidecar_path.exists() {
                return (sidecar_path.to_string_lossy().to_string(), vec![]);
            }
        }
    }
    
    // Fallback to Python in dev mode
    if is_dev_mode() {
        let script_path = format!("{}/python/backend_daemon.py", DEV_PROJECT_PATH);
        return (DEV_PYTHON_PATH.to_string(), vec![script_path]);
    }
    
    ("".to_string(), vec![])
}

// Tauri commands
#[tauri::command]
async fn get_devices(app: AppHandle) -> Result<Vec<AudioDevice>, String> {
    log::info!("get_devices called");
    
    let (cmd_path, mut args) = get_sidecar_or_python_command(Some(&app));
    
    if cmd_path.is_empty() {
        log::error!("No sidecar or Python available");
        return Ok(vec![]);
    }
    
    args.push("--list-devices".to_string());
    
    let output = Command::new(&cmd_path)
        .args(&args)
        .output();
    
    match output {
        Ok(output) => {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                // Parse the JSON response
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&stdout) {
                    if let Some(devices) = json.get("devices") {
                        if let Ok(devices) = serde_json::from_value::<Vec<AudioDevice>>(devices.clone()) {
                            log::info!("Parsed {} audio devices", devices.len());
                            return Ok(devices);
                        }
                    }
                }
            } else {
                let stderr = String::from_utf8_lossy(&output.stderr);
                log::error!("Command failed: {}", stderr);
            }
        }
        Err(e) => {
            log::error!("Failed to run command: {}", e);
        }
    }
    
    Ok(vec![])
}

#[tauri::command]
async fn get_config() -> Result<Config, String> {
    Ok(load_config_from_file())
}

#[tauri::command]
async fn save_config(config: Config, state: tauri::State<'_, SharedState>) -> Result<(), String> {
    log::info!("Saving config: {:?}", config);
    save_config_to_file(&config)?;
    
    // Update in-memory state
    let mut state = state.lock().await;
    state.config = config;
    
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelStatus {
    pub downloaded: bool,
    pub path: Option<String>,
    pub size: Option<String>,
    pub error: Option<String>,
}

#[tauri::command]
async fn check_model_status(app: AppHandle, model: String) -> Result<ModelStatus, String> {
    log::info!("Checking model status: {}", model);
    
    let (cmd_path, mut args) = get_sidecar_or_python_command(Some(&app));
    
    if cmd_path.is_empty() {
        return Ok(ModelStatus {
            downloaded: false,
            path: None,
            size: None,
            error: Some("No sidecar or Python available".to_string()),
        });
    }
    
    args.push("--check-model".to_string());
    args.push(model.clone());
    
    let output = Command::new(&cmd_path)
        .args(&args)
        .output()
        .map_err(|e| e.to_string())?;
    
    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        // Parse the JSON response - it may have multiple lines
        for line in stdout.lines() {
            if let Ok(status) = serde_json::from_str::<ModelStatus>(line) {
                return Ok(status);
            }
        }
    }
    
    Ok(ModelStatus {
        downloaded: false,
        path: None,
        size: None,
        error: Some("Failed to check model".to_string()),
    })
}

#[tauri::command]
async fn download_model(app: AppHandle, model: String) -> Result<(), String> {
    log::info!("Downloading model: {}", model);
    let _ = app.emit("model_download_started", &model);
    
    let (cmd_path, mut args) = get_sidecar_or_python_command(Some(&app));
    
    if cmd_path.is_empty() {
        let _ = app.emit("model_download_error", &model);
        return Err("No sidecar or Python available".to_string());
    }
    
    args.push("--download-model".to_string());
    args.push(model.clone());
    
    let output = Command::new(&cmd_path)
        .args(&args)
        .output()
        .map_err(|e| e.to_string())?;
    
    if output.status.success() {
        log::info!("Model downloaded: {}", model);
        let _ = app.emit("model_download_done", &model);
        return Ok(());
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        log::error!("Model download failed: {}", stderr);
        let _ = app.emit("model_download_error", &model);
        return Err(format!("Download failed: {}", stderr));
    }
}

#[tauri::command]
async fn show_overlay(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.show().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn hide_overlay(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn show_settings(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("settings") {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn check_accessibility() -> Result<bool, String> {
    #[cfg(target_os = "macos")]
    {
        let output = Command::new("osascript")
            .arg("-e")
            .arg("tell application \"System Events\" to return (name of first process)")
            .output();
        
        match output {
            Ok(result) => Ok(result.status.success()),
            Err(_) => Ok(false),
        }
    }
    
    #[cfg(not(target_os = "macos"))]
    {
        Ok(true)
    }
}

#[tauri::command]
async fn open_accessibility_settings() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn setup_tray(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let _tray = TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("SuperWhisper - Option+Space to record")
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(window) = app.get_webview_window("settings") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        })
        .build(app)?;

    Ok(())
}

fn start_daemon(app: &AppHandle, state: SharedState) -> bool {
    let mut cmd: Command;
    
    // Try sidecar first (production), fallback to Python (dev)
    if let Some(sidecar_path) = get_sidecar_path(app) {
        if sidecar_path.exists() {
            log::info!("Starting daemon from sidecar: {:?}", sidecar_path);
            cmd = Command::new(sidecar_path);
        } else if is_dev_mode() {
            log::info!("Sidecar not found, using Python in dev mode");
            let script_path = format!("{}/python/backend_daemon.py", DEV_PROJECT_PATH);
            cmd = Command::new(DEV_PYTHON_PATH);
            cmd.arg(&script_path);
        } else {
            log::error!("Sidecar not found and not in dev mode!");
            return false;
        }
    } else if is_dev_mode() {
        log::info!("Using Python daemon in dev mode");
        let script_path = format!("{}/python/backend_daemon.py", DEV_PROJECT_PATH);
        cmd = Command::new(DEV_PYTHON_PATH);
        cmd.arg(&script_path);
    } else {
        log::error!("Cannot determine daemon path!");
        return false;
    }
    
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    
    match cmd.spawn() {
        Ok(mut child) => {
            log::info!("Started Python daemon (PID: {:?})", child.id());
            
            let stdin = child.stdin.take();
            
            // Spawn thread to read daemon output
            if let Some(stdout) = child.stdout.take() {
                let app_handle = app.clone();
                std::thread::spawn(move || {
                    let reader = BufReader::new(stdout);
                    for line in reader.lines() {
                        if let Ok(line) = line {
                            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&line) {
                                // Audio level updates
                                if let Some(level) = json.get("audio_level").and_then(|l| l.as_f64()) {
                                    let _ = app_handle.emit("audio_level", level);
                                }
                                // Status updates
                                if let Some(status) = json.get("status").and_then(|s| s.as_str()) {
                                    log::info!("Daemon status: {}", status);
                                    if status == "model_loaded" {
                                        let _ = app_handle.emit("model_ready", ());
                                    }
                                }
                                // Transcription result
                                if let Some(text) = json.get("text").and_then(|t| t.as_str()) {
                                    log::info!("Transcription result: {}", text);
                                    let transcription_time = json.get("transcription_time")
                                        .and_then(|t| t.as_f64())
                                        .unwrap_or(0.0);
                                    log::info!("Transcription took: {:.2}s", transcription_time);
                                    
                                    let _ = app_handle.emit("transcription_done", serde_json::json!({
                                        "text": text,
                                        "copied": json.get("copied").and_then(|c| c.as_bool()).unwrap_or(false),
                                        "typed": json.get("typed").and_then(|t| t.as_bool()).unwrap_or(false)
                                    }));
                                    
                                    // Don't hide overlay - let it stay visible
                                }
                                // Error
                                if let Some(error) = json.get("error").and_then(|e| e.as_str()) {
                                    log::warn!("Daemon error: {}", error);
                                    let _ = app_handle.emit("transcription_done", serde_json::json!({
                                        "text": "",
                                        "error": error
                                    }));
                                    
                                    // Don't hide overlay - let it stay visible
                                }
                            }
                        }
                    }
                    log::warn!("Daemon stdout reader ended");
                });
            }
            
            // Store stdin for sending commands
            let state_clone = state.clone();
            tauri::async_runtime::spawn(async move {
                let mut state = state_clone.lock().await;
                state.daemon_stdin = stdin;
            });
            
            true
        }
        Err(e) => {
            log::error!("Failed to start Python daemon: {}", e);
            false
        }
    }
}

fn send_daemon_command(stdin: &mut std::process::ChildStdin, cmd: &serde_json::Value) -> bool {
    let json_str = serde_json::to_string(cmd).unwrap_or_default();
    if let Err(e) = writeln!(stdin, "{}", json_str) {
        log::error!("Failed to send command to daemon: {}", e);
        return false;
    }
    if let Err(e) = stdin.flush() {
        log::error!("Failed to flush daemon stdin: {}", e);
        return false;
    }
    true
}

fn setup_global_shortcut(app: &AppHandle, state: SharedState) -> Result<(), Box<dyn std::error::Error>> {
    let app_handle = app.clone();
    
    // Use Option+Space as the hotkey
    let shortcut = Shortcut::new(Some(Modifiers::ALT), Code::Space);
    
    app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, event| {
        let app_clone = app_handle.clone();
        let state_clone = state.clone();
        
        match event.state() {
            ShortcutState::Pressed => {
                let app_clone2 = app_clone.clone();
                let state_clone2 = state_clone.clone();
                
                tauri::async_runtime::spawn(async move {
                    let mut state = state_clone2.lock().await;
                    
                    if state.is_recording {
                        return;
                    }
                    
                    state.is_recording = true;
                    state.recording_start = Some(Instant::now());
                    
                    // Get config before mutable borrow
                    let device = state.config.device_id;
                    
                    // Send start_recording command to daemon
                    if let Some(ref mut stdin) = state.daemon_stdin {
                        let cmd = serde_json::json!({
                            "cmd": "start_recording",
                            "device": device
                        });
                        send_daemon_command(stdin, &cmd);
                    } else {
                        log::error!("Daemon not running!");
                    }
                    
                    log::info!("Recording started");
                    
                    // Show overlay
                    if let Some(window) = app_clone2.get_webview_window("overlay") {
                        let _ = window.show();
                    }
                    
                    let _ = app_clone2.emit("recording_started", ());
                });
            }
            ShortcutState::Released => {
                let app_clone2 = app_clone.clone();
                let state_clone2 = state_clone.clone();
                
                tauri::async_runtime::spawn(async move {
                    let mut state = state_clone2.lock().await;
                    
                    if !state.is_recording {
                        return;
                    }
                    
                    state.is_recording = false;
                    
                    let duration = state.recording_start
                        .map(|start| start.elapsed().as_secs_f32())
                        .unwrap_or(0.0);
                    
                    log::info!("Recording stopped after {:.1}s", duration);
                    
                    let _ = app_clone2.emit("recording_stopped", serde_json::json!({
                        "duration": duration
                    }));
                    
                    // Get config before mutable borrow
                    let output_mode = state.config.output_mode.clone();
                    
                    // Send stop_and_transcribe command to daemon
                    if let Some(ref mut stdin) = state.daemon_stdin {
                        let _ = app_clone2.emit("transcription_started", ());
                        
                        let cmd = serde_json::json!({
                            "cmd": "stop_and_transcribe",
                            "output": output_mode
                        });
                        send_daemon_command(stdin, &cmd);
                    } else {
                        log::error!("Daemon not running!");
                        
                        // Hide overlay
                        tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                        if let Some(window) = app_clone2.get_webview_window("overlay") {
                            let _ = window.hide();
                        }
                    }
                });
            }
        }
    })?;
    
    log::info!("Global shortcut registered: Option+Space (hold to record, release to transcribe)");

    Ok(())
}

#[allow(dead_code)]
async fn spawn_python_backend(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let sidecar = app.shell().sidecar("superwhisper-backend")?;
    let (mut _rx, mut _child) = sidecar.spawn()?;
    log::info!("Python backend started");
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let state: SharedState = Arc::new(Mutex::new(BackendState::default()));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(state.clone())
        .setup(move |app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            if let Err(e) = setup_tray(app.handle()) {
                log::error!("Failed to setup tray: {}", e);
            }

            let state_clone = state.clone();
            if let Err(e) = setup_global_shortcut(app.handle(), state_clone) {
                log::error!("Failed to setup global shortcut: {}", e);
            }
            
            // Start daemon and load model
            let state_clone = state.clone();
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                // Start daemon
                if start_daemon(&app_handle, state_clone.clone()) {
                    // Give daemon time to start
                    std::thread::sleep(std::time::Duration::from_millis(500));
                    
                    // Load model
                    let config = tauri::async_runtime::block_on(async {
                        let state = state_clone.lock().await;
                        state.config.clone()
                    });
                    
                    tauri::async_runtime::block_on(async {
                        let mut state = state_clone.lock().await;
                        if let Some(ref mut stdin) = state.daemon_stdin {
                            let cmd = serde_json::json!({
                                "cmd": "load_model",
                                "model": config.model
                            });
                            send_daemon_command(stdin, &cmd);
                            state.model_loaded = true;
                            log::info!("Model load command sent: {}", config.model);
                        }
                    });
                }
            });

            // Center overlay at top of screen
            if let Some(window) = app.get_webview_window("overlay") {
                if let Some(monitor) = window.current_monitor().ok().flatten() {
                    let screen_width = monitor.size().width as i32;
                    let window_width = 400;
                    let x = (screen_width - window_width) / 2;
                    let y = 30; // Below menu bar
                    let _ = window.set_position(tauri::PhysicalPosition::new(x, y));
                    log::info!("Overlay positioned at ({}, {})", x, y);
                }
            }

            log::info!("SuperWhisper initialized - Hold Option+Space to record");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_devices,
            get_config,
            save_config,
            show_overlay,
            hide_overlay,
            show_settings,
            check_accessibility,
            open_accessibility_settings,
            check_model_status,
            download_model,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
