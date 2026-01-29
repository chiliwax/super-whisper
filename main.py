import onnx_asr
from onnx_asr.loader import load_vad
import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
from pynput import keyboard
import tempfile
import subprocess
import sys
import threading

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
DEVICE_ID = None  # Will be set by user or default
USE_VAD = False   # Enable VAD for segmentation

# macOS system sounds for feedback
SOUND_START = "/System/Library/Sounds/Pop.aiff"      # Recording started
SOUND_STOP = "/System/Library/Sounds/Blow.aiff"      # Recording stopped
SOUND_DONE = "/System/Library/Sounds/Glass.aiff"     # Transcription complete
SOUND_ERROR = "/System/Library/Sounds/Basso.aiff"    # Error occurred

# State
recording = False
transcribing = False  # Prevent overlapping transcriptions
audio_data = []
model = None
vad_model = None

def play_sound(sound_path):
    """Play a system sound asynchronously."""
    subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_recording():
    global recording, transcribing, audio_data
    if recording:
        return
    if transcribing:
        print("⏳ Please wait, still transcribing...")
        return
    recording = True
    audio_data = []
    play_sound(SOUND_START)
    print("🎙️  Recording... (release Right ⌘ to stop)")
    
    def callback(indata, frames, time, status):
        if recording:
            audio_data.append(indata.copy())
    
    # Start recording in a stream
    global stream
    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, device=DEVICE_ID, callback=callback)
    stream.start()

def do_transcription(audio_int16):
    """Run transcription in background thread."""
    global transcribing, model, vad_model, USE_VAD
    
    try:
        # Check audio level
        audio_level = np.abs(audio_int16).mean()
        duration = len(audio_int16) / SAMPLE_RATE
        print(f"   Audio: {duration:.1f}s, level: {audio_level:.0f}")
        
        if audio_level < 100:
            play_sound(SOUND_ERROR)
            print("⚠️  Audio too quiet - check your microphone!")
            return
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav.write(f.name, SAMPLE_RATE, audio_int16)
            
            if USE_VAD and vad_model is not None:
                # Use VAD to segment and transcribe
                result = do_vad_transcription(f.name, audio_int16)
            else:
                # Standard transcription without VAD
                result = model.recognize(f.name)
            
            if result and result.strip():
                play_sound(SOUND_DONE)
                print(f"\n📝 Transcription:\n{result}\n")
            else:
                play_sound(SOUND_ERROR)
                print("⚠️  No speech detected in audio.")
    finally:
        transcribing = False

def do_vad_transcription(filepath, audio_int16):
    """Transcribe using VAD segmentation for better accuracy on long audio."""
    global model, vad_model
    
    # Convert to float32 for VAD (normalized -1 to 1)
    audio_float = audio_int16.astype(np.float32) / 32767.0
    
    # Prepare batch format for VAD
    waveforms = audio_float.reshape(1, -1)  # Shape: (1, samples)
    waveforms_len = np.array([len(audio_float)], dtype=np.int64)
    
    # Get speech segments with VAD
    segments_iter = vad_model.segment_batch(
        waveforms, 
        waveforms_len, 
        sample_rate=SAMPLE_RATE
    )
    
    # Collect all speech segments
    all_texts = []
    for segment_list in segments_iter:
        segments = list(segment_list)
        if not segments:
            continue
            
        print(f"   VAD found {len(segments)} speech segment(s)")
        
        for i, (start, end) in enumerate(segments):
            # Extract segment audio
            segment_audio = audio_int16[start:end]
            if len(segment_audio) < SAMPLE_RATE * 0.1:  # Skip very short segments (< 0.1s)
                continue
            
            # Save segment to temp file and transcribe
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as seg_f:
                wav.write(seg_f.name, SAMPLE_RATE, segment_audio)
                result = model.recognize(seg_f.name)
                if result and result.strip():
                    all_texts.append(result.strip())
    
    return " ".join(all_texts)

def stop_recording_and_transcribe():
    global recording, transcribing, audio_data, stream
    if not recording:
        return
    if transcribing:
        print("⏳ Still transcribing previous recording...")
        return
    
    recording = False
    stream.stop()
    stream.close()
    play_sound(SOUND_STOP)
    print("⏹️  Stopped recording. Transcribing...")
    
    if not audio_data:
        play_sound(SOUND_ERROR)
        print("No audio recorded.")
        return
    
    # Combine audio chunks
    audio = np.concatenate(audio_data, axis=0)
    # Convert float32 to int16 PCM format (required by onnx_asr)
    audio_int16 = (audio * 32767).astype(np.int16)
    
    # Run transcription in background thread so keyboard listener stays responsive
    transcribing = True
    thread = threading.Thread(target=do_transcription, args=(audio_int16,), daemon=True)
    thread.start()

# Use Right Command key (⌘) to record - hold to start, release to stop
# This avoids character artifacts in the terminal

def on_press(key):
    # Right Command key starts recording
    if key == keyboard.Key.cmd_r:
        start_recording()

def on_release(key):
    # Right Command key released - stop and transcribe
    if key == keyboard.Key.cmd_r:
        if recording:
            stop_recording_and_transcribe()

def list_microphones():
    """List all available input devices."""
    print("\n🎤 Available microphones:\n")
    devices = sd.query_devices()
    input_devices = []
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            is_default = " (default)" if i == sd.default.device[0] else ""
            print(f"  [{i}] {dev['name']}{is_default}")
            input_devices.append(i)
    print()
    return input_devices

def select_microphone():
    """Interactive microphone selection."""
    global DEVICE_ID
    input_devices = list_microphones()
    
    if not input_devices:
        print("❌ No input devices found!")
        sys.exit(1)
    
    try:
        choice = input("Enter microphone number (or press Enter for default): ").strip()
        if choice == "":
            DEVICE_ID = None
            default_dev = sd.query_devices(sd.default.device[0])
            print(f"✅ Using default: {default_dev['name']}\n")
        else:
            DEVICE_ID = int(choice)
            if DEVICE_ID not in input_devices:
                print(f"❌ Invalid device number: {DEVICE_ID}")
                sys.exit(1)
            dev = sd.query_devices(DEVICE_ID)
            print(f"✅ Using: {dev['name']}\n")
    except ValueError:
        print("❌ Invalid input")
        sys.exit(1)

def main():
    global model, vad_model, DEVICE_ID, USE_VAD
    
    # Parse all arguments
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-l", "--list"):
            list_microphones()
            sys.exit(0)
        elif arg in ("-d", "--device"):
            if i + 1 < len(args):
                DEVICE_ID = int(args[i + 1])
                dev = sd.query_devices(DEVICE_ID)
                print(f"🎤 Using microphone: {dev['name']}")
                i += 1
            else:
                print("❌ Please specify device number: python main.py -d <number>")
                sys.exit(1)
        elif arg in ("-h", "--help"):
            print("Usage: python main.py [options]")
            print("  -l, --list      List available microphones")
            print("  -d, --device N  Use microphone number N")
            print("  -s, --select    Interactive microphone selection")
            print("  --vad           Enable VAD (Voice Activity Detection) for segmentation")
            print("  -h, --help      Show this help")
            sys.exit(0)
        elif arg in ("-s", "--select"):
            select_microphone()
        elif arg == "--vad":
            USE_VAD = True
        i += 1
    
    # Show current microphone
    if DEVICE_ID is None:
        default_dev = sd.query_devices(sd.default.device[0])
        print(f"🎤 Using default microphone: {default_dev['name']}")
    
    # Load VAD model if enabled
    if USE_VAD:
        print("Loading Silero VAD model...")
        vad_model = load_vad("silero", providers=["CPUExecutionProvider"])
        print("✅ VAD enabled (audio will be segmented)")
    
    print("Loading Parakeet TDT v3 model...")
    model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", providers=["CPUExecutionProvider"])
    print("✅ Model loaded!")
    
    vad_status = " [VAD ON]" if USE_VAD else ""
    print(f"\n🎤 Hold Right ⌘ (Command) to record, release to transcribe.{vad_status}")
    print("   Press Ctrl+C to quit.\n")
    
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()

if __name__ == "__main__":
    main()