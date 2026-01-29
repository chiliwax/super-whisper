/**
 * SuperWhisper Overlay - Flat Design
 */

function waitForTauri(callback, maxAttempts = 50) {
    let attempts = 0;
    const check = () => {
        attempts++;
        if (window.__TAURI__) {
            callback();
        } else if (attempts < maxAttempts) {
            setTimeout(check, 100);
        } else {
            console.error('Tauri API not available');
        }
    };
    check();
}

class OverlayApp {
    constructor() {
        this.overlay = document.getElementById('overlay');
        this.status = document.querySelector('.status');
        this.timer = document.querySelector('.timer');
        this.canvas = document.getElementById('waveform');
        this.ctx = this.canvas.getContext('2d');
        
        this.startTime = null;
        this.timerInterval = null;
        this.animationFrame = null;
        this.audioLevel = 0;
        this.targetAudioLevel = 0;  // For smooth interpolation
        this.waveformBars = new Array(24).fill(0);
        
        this.setupCanvas();
        this.init();
    }
    
    setupCanvas() {
        // High DPI support
        const dpr = window.devicePixelRatio || 1;
        const rect = { width: 140, height: 32 };
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
        this.ctx.scale(dpr, dpr);
    }
    
    async init() {
        try {
            const { listen } = window.__TAURI__.event;
            const { invoke } = window.__TAURI__.core;
            
            this.listen = listen;
            this.invoke = invoke;
            
            await this.setupEventListeners();
            this.startIdleAnimation();
            console.log('Overlay ready');
        } catch (e) {
            console.error('Init error:', e);
        }
    }
    
    async setupEventListeners() {
        await this.listen('recording_started', () => this.onRecordingStarted());
        await this.listen('audio_level', (e) => this.onAudioLevel(e.payload));
        await this.listen('recording_stopped', (e) => this.onRecordingStopped(e.payload));
        await this.listen('transcription_started', () => this.onTranscriptionStarted());
        await this.listen('transcription_done', (e) => this.onTranscriptionDone(e.payload));
    }
    
    setState(state) {
        this.overlay.className = state;
    }
    
    onRecordingStarted() {
        this.setState('recording');
        this.status.textContent = 'Recording';
        this.startTime = Date.now();
        this.audioLevel = 0;
        this.targetAudioLevel = 0;
        this.startTimer();
        this.startRecordingAnimation();
    }
    
    onAudioLevel(level) {
        // Level is a number from 0 to 1 sent by Python
        if (typeof level === 'number') {
            this.targetAudioLevel = level;
        }
    }
    
    onRecordingStopped(data) {
        this.stopTimer();
        this.audioLevel = 0;
        this.targetAudioLevel = 0;
        if (data?.duration) {
            this.timer.textContent = this.formatTime(data.duration);
        }
    }
    
    onTranscriptionStarted() {
        this.setState('transcribing');
        this.status.textContent = 'Transcribing';
        this.startProcessingAnimation();
    }
    
    onTranscriptionDone(data) {
        this.stopAnimation();
        this.audioLevel = 0;
        this.targetAudioLevel = 0;
        this.setState('done');
        
        if (data?.text) {
            this.status.textContent = 'Copied!';
        } else {
            this.status.textContent = 'No speech';
        }
        
        setTimeout(() => {
            this.setState('idle');
            this.status.textContent = 'Ready';
            this.timer.textContent = '0:00';
            this.startIdleAnimation();
            this.hideOverlay();
        }, 1200);
    }
    
    startTimer() {
        this.timerInterval = setInterval(() => {
            const elapsed = (Date.now() - this.startTime) / 1000;
            this.timer.textContent = this.formatTime(elapsed);
        }, 100);
    }
    
    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }
    
    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
    
    // === WAVEFORM ANIMATIONS ===
    
    startIdleAnimation() {
        this.stopAnimation();
        const draw = () => {
            this.drawIdleWaveform();
            this.animationFrame = requestAnimationFrame(draw);
        };
        draw();
    }
    
    startRecordingAnimation() {
        this.stopAnimation();
        const draw = () => {
            this.drawRecordingWaveform();
            this.animationFrame = requestAnimationFrame(draw);
        };
        draw();
    }
    
    startProcessingAnimation() {
        this.stopAnimation();
        const draw = () => {
            this.drawProcessingWaveform();
            this.animationFrame = requestAnimationFrame(draw);
        };
        draw();
    }
    
    stopAnimation() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
    }
    
    drawIdleWaveform() {
        const { width, height } = { width: 140, height: 32 };
        this.ctx.clearRect(0, 0, width, height);
        
        const centerY = height / 2;
        const time = Date.now() / 1000;
        
        // Subtle breathing line
        this.ctx.beginPath();
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        this.ctx.lineWidth = 1.5;
        
        for (let x = 0; x < width; x++) {
            const wave = Math.sin(x * 0.05 + time * 2) * 2;
            const y = centerY + wave;
            if (x === 0) this.ctx.moveTo(x, y);
            else this.ctx.lineTo(x, y);
        }
        this.ctx.stroke();
    }
    
    drawRecordingWaveform() {
        const { width, height } = { width: 140, height: 32 };
        this.ctx.clearRect(0, 0, width, height);
        
        const barCount = this.waveformBars.length;
        const barWidth = 3;
        const gap = (width - barCount * barWidth) / (barCount + 1);
        const centerY = height / 2;
        const maxBarHeight = height * 0.8;
        
        // Smooth interpolation from target level (sent by Python)
        const speed = this.targetAudioLevel > this.audioLevel ? 0.4 : 0.15;
        this.audioLevel += (this.targetAudioLevel - this.audioLevel) * speed;
        
        // Update each bar based on audio level
        for (let i = 0; i < barCount; i++) {
            // Each bar gets slightly different value for wave effect
            const variation = 0.7 + Math.random() * 0.6;
            const target = this.audioLevel * variation;
            
            // Smooth interpolation (fast attack, slower decay)
            const barSpeed = target > this.waveformBars[i] ? 0.5 : 0.12;
            this.waveformBars[i] += (target - this.waveformBars[i]) * barSpeed;
            
            // Minimum bar height when there's sound, very small when silent
            const minHeight = this.audioLevel > 0.05 ? 0.1 : 0.02;
            this.waveformBars[i] = Math.max(minHeight, this.waveformBars[i]);
        }
        
        // Draw bars (mirrored from center)
        for (let i = 0; i < barCount; i++) {
            const x = gap + i * (barWidth + gap);
            const barHeight = this.waveformBars[i] * maxBarHeight;
            
            // Gradient from center - color intensity based on level
            const intensity = 0.6 + this.audioLevel * 0.4;
            const gradient = this.ctx.createLinearGradient(0, centerY - barHeight/2, 0, centerY + barHeight/2);
            gradient.addColorStop(0, `rgba(255, 59, 48, ${intensity * 0.9})`);
            gradient.addColorStop(0.5, `rgba(255, 59, 48, ${intensity})`);
            gradient.addColorStop(1, `rgba(255, 59, 48, ${intensity * 0.9})`);
            
            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.ctx.roundRect(x, centerY - barHeight/2, barWidth, barHeight, 1.5);
            this.ctx.fill();
        }
    }
    
    drawProcessingWaveform() {
        const { width, height } = { width: 140, height: 32 };
        this.ctx.clearRect(0, 0, width, height);
        
        const centerY = height / 2;
        const time = Date.now() / 1000;
        
        // Flowing wave animation
        this.ctx.beginPath();
        this.ctx.strokeStyle = '#ff9f0a';
        this.ctx.lineWidth = 2;
        
        for (let x = 0; x < width; x++) {
            const wave = Math.sin(x * 0.08 - time * 4) * 6;
            const envelope = Math.sin(x / width * Math.PI);
            const y = centerY + wave * envelope;
            if (x === 0) this.ctx.moveTo(x, y);
            else this.ctx.lineTo(x, y);
        }
        this.ctx.stroke();
        
        // Add glow
        this.ctx.strokeStyle = 'rgba(255, 159, 10, 0.3)';
        this.ctx.lineWidth = 4;
        this.ctx.stroke();
    }
    
    async hideOverlay() {
        try {
            await this.invoke('hide_overlay');
        } catch (e) {
            console.error('Failed to hide overlay:', e);
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    waitForTauri(() => new OverlayApp());
});
