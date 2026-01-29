/**
 * SuperWhisper Settings - Flat Design
 */

const { invoke } = window.__TAURI__?.core ?? {};
const { listen } = window.__TAURI__?.event ?? {};

// Estimated download times (seconds) based on ~10MB/s
const MODEL_INFO = {
    "nemo-parakeet-tdt-0.6b-v3": { size: "2.4GB", bytes: 2400000000, time: 240 },
    "whisper-base": { size: "150MB", bytes: 150000000, time: 15 },
    "onnx-community/whisper-large-v3-turbo": { size: "1.6GB", bytes: 1600000000, time: 160 },
};

class SettingsApp {
    constructor() {
        this.elements = {
            microphone: document.getElementById('microphone'),
            model: document.getElementById('model'),
            modelStatus: document.getElementById('model-status'),
            modelDownloadRow: document.getElementById('model-download-row'),
            downloadText: document.getElementById('download-text'),
            downloadBtn: document.getElementById('download-model'),
            cancelBtn: document.getElementById('cancel-download'),
            progressRow: document.getElementById('download-progress-row'),
            progressFill: document.getElementById('progress-fill'),
            progressText: document.getElementById('progress-text'),
            vad: document.getElementById('vad'),
            outputMode: document.getElementById('output-mode'),
            hotkeyBtn: document.getElementById('hotkey-btn'),
            hotkeyDisplay: document.getElementById('hotkey-display'),
            hotkeyReset: document.getElementById('hotkey-reset'),
            saveBtn: document.getElementById('save-settings'),
            refreshBtn: document.getElementById('refresh-devices'),
            accessibilityWarning: document.getElementById('accessibility-warning'),
            openAccessibilityBtn: document.getElementById('open-accessibility'),
        };
        
        this.config = {};
        this.capturingHotkey = false;
        this.downloading = false;
        this.downloadCancelled = false;
        this.progressInterval = null;
        
        this.init();
    }
    
    async init() {
        if (!invoke) {
            console.error('Tauri not available');
            return;
        }
        
        try {
            await this.checkAccessibility();
            await this.loadDevices();
            await this.loadConfig();
            this.setupListeners();
            await this.checkModelStatus();
            console.log('Settings ready');
        } catch (e) {
            console.error('Init error:', e);
        }
    }
    
    async checkAccessibility() {
        try {
            const hasAccess = await invoke('check_accessibility');
            if (this.elements.accessibilityWarning) {
                this.elements.accessibilityWarning.style.display = hasAccess ? 'none' : 'flex';
            }
        } catch (e) {
            console.warn('Accessibility check failed:', e);
        }
    }
    
    async loadDevices() {
        const select = this.elements.microphone;
        if (!select) return;
        
        select.innerHTML = '<option value="">Loading...</option>';
        
        try {
            const devices = await invoke('get_devices');
            select.innerHTML = '<option value="">System Default</option>';
            
            if (devices?.length) {
                devices.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d.id;
                    opt.textContent = d.name + (d.is_default ? ' ★' : '');
                    select.appendChild(opt);
                });
            }
        } catch (e) {
            select.innerHTML = '<option value="">Error loading</option>';
        }
    }
    
    async loadConfig() {
        try {
            this.config = await invoke('get_config');
            this.applyConfig();
        } catch (e) {
            console.error('Load config error:', e);
        }
    }
    
    applyConfig() {
        const { microphone, model, vad, outputMode, hotkeyDisplay } = this.elements;
        
        if (this.config.device_id != null) {
            microphone.value = this.config.device_id;
        }
        if (model) model.value = this.config.model || 'nemo-parakeet-tdt-0.6b-v3';
        if (vad) vad.checked = this.config.use_vad || false;
        if (outputMode) outputMode.value = this.config.output_mode || 'clipboard';
        if (hotkeyDisplay) hotkeyDisplay.textContent = this.formatHotkey(this.config.hotkey);
    }
    
    formatHotkey(key) {
        if (!key) return '⌥ Space';
        
        const parts = key.split('+');
        const modifierMap = {
            'alt': '⌥',
            'ctrl': '⌃',
            'cmd': '⌘',
            'shift': '⇧',
            'meta': '⌘',
        };
        
        return parts.map(p => {
            const lower = p.toLowerCase();
            if (modifierMap[lower]) return modifierMap[lower];
            if (lower === 'space') return 'Space';
            return p.toUpperCase();
        }).join(' ');
    }
    
    async checkModelStatus() {
        const model = this.elements.model?.value;
        if (!model) return;
        
        const statusEl = this.elements.modelStatus;
        const downloadRow = this.elements.modelDownloadRow;
        const info = MODEL_INFO[model];
        
        if (statusEl) {
            statusEl.textContent = '...';
            statusEl.className = 'model-status';
        }
        
        try {
            const status = await invoke('check_model_status', { model });
            
            if (status.downloaded) {
                if (statusEl) {
                    const sizeText = status.size ? ` (${status.size})` : '';
                    statusEl.textContent = `✓ Ready${sizeText}`;
                    statusEl.className = 'model-status ready';
                }
                if (downloadRow) downloadRow.style.display = 'none';
                if (this.elements.progressRow) this.elements.progressRow.style.display = 'none';
            } else {
                if (statusEl) {
                    statusEl.textContent = '⚠ Not installed';
                    statusEl.className = 'model-status missing';
                }
                if (downloadRow) {
                    downloadRow.style.display = 'flex';
                    this.elements.downloadText.textContent = `Download required (${info?.size || 'unknown'})`;
                }
            }
        } catch (e) {
            console.warn('Model check failed:', e);
            if (statusEl) {
                statusEl.textContent = '?';
                statusEl.className = 'model-status';
            }
        }
    }
    
    async downloadModel() {
        const model = this.elements.model?.value;
        if (!model || this.downloading) return;
        
        const info = MODEL_INFO[model];
        this.downloading = true;
        this.downloadCancelled = false;
        
        // Update UI
        this.elements.downloadBtn.style.display = 'none';
        this.elements.cancelBtn.style.display = 'block';
        this.elements.downloadText.textContent = 'Downloading...';
        this.elements.progressRow.style.display = 'flex';
        this.elements.progressFill.style.width = '0%';
        this.elements.progressText.textContent = '0%';
        this.elements.modelStatus.textContent = '↓ Downloading';
        this.elements.modelStatus.className = 'model-status downloading';
        
        // Start progress animation (estimated)
        let progress = 0;
        const estimatedTime = info?.time || 60;
        const startTime = Date.now();
        
        this.progressInterval = setInterval(() => {
            if (this.downloadCancelled) {
                clearInterval(this.progressInterval);
                return;
            }
            
            const elapsed = (Date.now() - startTime) / 1000;
            // Use logarithmic progress that slows down as it approaches 95%
            progress = Math.min(95, (elapsed / estimatedTime) * 100 * 0.95);
            
            this.elements.progressFill.style.width = `${progress}%`;
            this.elements.progressText.textContent = `${Math.round(progress)}%`;
        }, 200);
        
        try {
            await invoke('download_model', { model });
            
            if (!this.downloadCancelled) {
                // Complete progress
                clearInterval(this.progressInterval);
                this.elements.progressFill.style.width = '100%';
                this.elements.progressText.textContent = '100%';
                
                setTimeout(() => {
                    this.elements.modelStatus.textContent = '✓ Ready';
                    this.elements.modelStatus.className = 'model-status ready';
                    this.elements.modelDownloadRow.style.display = 'none';
                    this.elements.progressRow.style.display = 'none';
                }, 500);
            }
        } catch (e) {
            console.error('Download failed:', e);
            if (!this.downloadCancelled) {
                this.elements.modelStatus.textContent = '✗ Failed';
                this.elements.modelStatus.className = 'model-status missing';
                this.elements.downloadText.textContent = 'Download failed - try again';
            }
        } finally {
            clearInterval(this.progressInterval);
            this.downloading = false;
            this.elements.downloadBtn.style.display = 'block';
            this.elements.cancelBtn.style.display = 'none';
        }
    }
    
    cancelDownload() {
        this.downloadCancelled = true;
        clearInterval(this.progressInterval);
        
        this.elements.modelStatus.textContent = '⚠ Cancelled';
        this.elements.modelStatus.className = 'model-status missing';
        this.elements.downloadText.textContent = 'Download cancelled';
        this.elements.progressRow.style.display = 'none';
        this.elements.downloadBtn.style.display = 'block';
        this.elements.cancelBtn.style.display = 'none';
        
        // Note: The actual download process may continue in the background
        // A full implementation would need to kill the Python process
    }
    
    setupListeners() {
        // Refresh devices
        this.elements.refreshBtn?.addEventListener('click', () => {
            this.elements.refreshBtn.style.transform = 'rotate(360deg)';
            setTimeout(() => this.elements.refreshBtn.style.transform = '', 300);
            this.loadDevices();
        });
        
        // Model change - check status
        this.elements.model?.addEventListener('change', () => {
            this.checkModelStatus();
        });
        
        // Download model
        this.elements.downloadBtn?.addEventListener('click', () => {
            this.downloadModel();
        });
        
        // Cancel download
        this.elements.cancelBtn?.addEventListener('click', () => {
            this.cancelDownload();
        });
        
        // Accessibility
        this.elements.openAccessibilityBtn?.addEventListener('click', async () => {
            await invoke('open_accessibility_settings');
        });
        
        // Hotkey capture
        this.elements.hotkeyBtn?.addEventListener('click', () => {
            this.startHotkeyCapture();
        });
        
        this.elements.hotkeyReset?.addEventListener('click', () => {
            this.config.hotkey = 'alt+space';
            this.elements.hotkeyDisplay.textContent = this.formatHotkey('alt+space');
        });
        
        // Global key listener for hotkey capture
        document.addEventListener('keydown', (e) => this.handleKeyCapture(e));
        
        // Save
        this.elements.saveBtn?.addEventListener('click', () => this.save());
    }
    
    startHotkeyCapture() {
        this.capturingHotkey = true;
        this.elements.hotkeyBtn?.classList.add('capturing');
        this.elements.hotkeyDisplay.textContent = 'Press keys...';
    }
    
    stopHotkeyCapture() {
        this.capturingHotkey = false;
        this.elements.hotkeyBtn?.classList.remove('capturing');
    }
    
    handleKeyCapture(e) {
        if (!this.capturingHotkey) return;
        
        e.preventDefault();
        e.stopPropagation();
        
        // Build hotkey string
        const parts = [];
        if (e.altKey) parts.push('alt');
        if (e.ctrlKey) parts.push('ctrl');
        if (e.metaKey) parts.push('cmd');
        if (e.shiftKey) parts.push('shift');
        
        // Add the actual key if it's not just a modifier
        const key = e.key.toLowerCase();
        if (!['alt', 'control', 'meta', 'shift'].includes(key)) {
            if (key === ' ') {
                parts.push('space');
            } else if (key.length === 1) {
                parts.push(key);
            } else if (key.startsWith('f') && key.length <= 3) {
                parts.push(key);
            }
        }
        
        // Need at least a modifier + key, or just a function key
        if (parts.length >= 2 || (parts.length === 1 && parts[0].startsWith('f'))) {
            const hotkey = parts.join('+');
            this.config.hotkey = hotkey;
            this.elements.hotkeyDisplay.textContent = this.formatHotkey(hotkey);
            this.stopHotkeyCapture();
        }
    }
    
    async save() {
        const btn = this.elements.saveBtn;
        
        try {
            const config = {
                device_id: this.elements.microphone.value ? parseInt(this.elements.microphone.value) : null,
                sample_rate: 16000,
                model: this.elements.model.value,
                use_vad: this.elements.vad.checked,
                output_mode: this.elements.outputMode.value,
                hotkey: this.config.hotkey || 'alt+space',
                typing_speed: 0.01,
                providers: ['CPUExecutionProvider']
            };
            
            await invoke('save_config', { config });
            
            // Success feedback
            btn.innerHTML = '<span>✓ Saved</span>';
            btn.classList.add('saved');
            
            setTimeout(() => {
                btn.innerHTML = '<span>Save Settings</span>';
                btn.classList.remove('saved');
            }, 1500);
            
        } catch (e) {
            console.error('Save error:', e);
            btn.innerHTML = '<span>Error</span>';
            btn.style.background = '#ff3b30';
            
            setTimeout(() => {
                btn.innerHTML = '<span>Save Settings</span>';
                btn.style.background = '';
            }, 1500);
        }
    }
}

// Init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => new SettingsApp());
} else {
    new SettingsApp();
}
