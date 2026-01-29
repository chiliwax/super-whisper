use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::Instant;
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

const PYTHON_PATH: &str = "/Users/thibault/Documents/WORK/super-whisper/.venv/bin/python";
const PROJECT_PATH: &str = "/Users/thibault/Documents/WORK/super-whisper";

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
    recording_process: Option<Child>,
    config: Config,
}

impl Default for BackendState {
    fn default() -> Self {
        Self {
            is_recording: false,
            recording_start: None,
            recording_process: None,
            config: load_config_from_file(),
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

// Tauri commands
#[tauri::command]
async fn get_devices(_app: AppHandle) -> Result<Vec<AudioDevice>, String> {
    log::info!("get_devices called");
    
    let python_script = r#"
import sounddevice as sd
import json
devices = sd.query_devices()
default_input = sd.default.device[0]
result = []
for i, dev in enumerate(devices):
    if dev['max_input_channels'] > 0:
        result.append({
            'id': i,
            'name': dev['name'],
            'is_default': i == default_input
        })
print(json.dumps(result))
"#;

    let output = Command::new(PYTHON_PATH)
        .arg("-c")
        .arg(python_script)
        .output();
    
    match output {
        Ok(output) => {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Ok(devices) = serde_json::from_str::<Vec<AudioDevice>>(&stdout) {
                    log::info!("Parsed {} audio devices", devices.len());
                    return Ok(devices);
                }
            }
        }
        Err(e) => {
            log::error!("Failed to run Python: {}", e);
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
async fn check_model_status(model: String) -> Result<ModelStatus, String> {
    let script_path = format!("{}/python/model_manager.py", PROJECT_PATH);
    
    let output = Command::new(PYTHON_PATH)
        .arg(&script_path)
        .arg("--check")
        .arg(&model)
        .output()
        .map_err(|e| e.to_string())?;
    
    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        serde_json::from_str(&stdout).map_err(|e| e.to_string())
    } else {
        Ok(ModelStatus {
            downloaded: false,
            path: None,
            size: None,
            error: Some("Failed to check model".to_string()),
        })
    }
}

#[tauri::command]
async fn download_model(app: AppHandle, model: String) -> Result<(), String> {
    let script_path = format!("{}/python/model_manager.py", PROJECT_PATH);
    
    log::info!("Downloading model: {}", model);
    let _ = app.emit("model_download_started", &model);
    
    let output = Command::new(PYTHON_PATH)
        .arg(&script_path)
        .arg("--download")
        .arg(&model)
        .output()
        .map_err(|e| e.to_string())?;
    
    if output.status.success() {
        log::info!("Model downloaded: {}", model);
        let _ = app.emit("model_download_done", &model);
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        log::error!("Model download failed: {}", stderr);
        let _ = app.emit("model_download_error", &model);
        Err(format!("Download failed: {}", stderr))
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

fn start_python_recording(config: &Config, app: &AppHandle) -> Option<Child> {
    let script_path = format!("{}/python/record_and_transcribe.py", PROJECT_PATH);
    
    let mut cmd = Command::new(PYTHON_PATH);
    cmd.arg(&script_path)
        .arg("--output")
        .arg(&config.output_mode)
        .arg("--model")
        .arg(&config.model)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    
    // Add device if specified
    if let Some(device_id) = config.device_id {
        cmd.arg("--device").arg(device_id.to_string());
    }
    
    // Add VAD flag if enabled
    if config.use_vad {
        cmd.arg("--vad");
    }
    
    match cmd.spawn() {
        Ok(mut child) => {
            log::info!("Started Python recording (device {:?}, model {}, vad {}, PID: {:?})", 
                config.device_id, config.model, config.use_vad, child.id());
            
            // Spawn thread to read audio levels and transcription from stdout
            if let Some(stdout) = child.stdout.take() {
                let app_handle = app.clone();
                std::thread::spawn(move || {
                    use std::io::{BufRead, BufReader};
                    let reader = BufReader::new(stdout);
                    for line in reader.lines() {
                        if let Ok(line) = line {
                            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&line) {
                                // Audio level updates
                                if let Some(level) = json.get("audio_level").and_then(|l| l.as_f64()) {
                                    let _ = app_handle.emit("audio_level", level);
                                }
                                // Transcription result
                                if let Some(text) = json.get("text").and_then(|t| t.as_str()) {
                                    log::info!("Transcription result: {}", text);
                                    let _ = app_handle.emit("transcription_done", serde_json::json!({
                                        "text": text,
                                        "copied": true
                                    }));
                                    
                                    // Hide overlay after a delay
                                    let app_inner = app_handle.clone();
                                    std::thread::sleep(std::time::Duration::from_secs(1));
                                    if let Some(window) = app_inner.get_webview_window("overlay") {
                                        let _ = window.hide();
                                    }
                                }
                                // Error
                                if let Some(error) = json.get("error").and_then(|e| e.as_str()) {
                                    log::warn!("Transcription error: {}", error);
                                    let _ = app_handle.emit("transcription_done", serde_json::json!({
                                        "text": "",
                                        "error": error
                                    }));
                                }
                            }
                        }
                    }
                });
            }
            
            Some(child)
        }
        Err(e) => {
            log::error!("Failed to start Python recording: {}", e);
            None
        }
    }
}

fn stop_python_recording(mut child: Child) {
    // Send newline to stdin to signal stop
    if let Some(ref mut stdin) = child.stdin {
        let _ = stdin.write_all(b"\n");
        let _ = stdin.flush();
    }
    
    // Wait for the process to complete (transcription handled by reader thread)
    match child.wait() {
        Ok(status) => {
            log::info!("Python process exited with status: {:?}", status);
        }
        Err(e) => {
            log::error!("Failed to wait for Python process: {}", e);
        }
    }
}

fn setup_global_shortcut(app: &AppHandle, state: SharedState) -> Result<(), Box<dyn std::error::Error>> {
    let app_handle = app.clone();
    
    // Use Option+Space as the hotkey
    let shortcut = Shortcut::new(Some(Modifiers::ALT), Code::Space);
    
    app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, event| {
        let app_clone = app_handle.clone();
        let state_clone = state.clone();
        
        // Handle in a blocking manner to ensure proper state management
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
                    
                    // Start Python recording process with current config
                    state.recording_process = start_python_recording(&state.config, &app_clone2);
                    
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
                    
                    // Stop Python recording (transcription handled by stdout reader thread)
                    if let Some(child) = state.recording_process.take() {
                        let _ = app_clone2.emit("transcription_started", ());
                        
                        // Release the lock before blocking operation
                        drop(state);
                        
                        tauri::async_runtime::spawn_blocking(move || {
                            stop_python_recording(child);
                        });
                    } else {
                        log::warn!("No recording process to stop");
                        
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
