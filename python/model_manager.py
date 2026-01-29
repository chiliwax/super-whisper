#!/usr/bin/env python3
"""Model manager for SuperWhisper - check and download models."""

import json
import sys
import os

# Model name to HuggingFace repo mapping
MODEL_REPOS = {
    "nemo-parakeet-tdt-0.6b-v3": "istupakov/parakeet-tdt-0.6b-v3-onnx",
    "whisper-base": "istupakov/whisper-base-onnx",
    "onnx-community/whisper-large-v3-turbo": "onnx-community/whisper-large-v3-turbo",
}

def get_hf_cache_path(model_name):
    """Get the HuggingFace cache path for a model."""
    repo = MODEL_REPOS.get(model_name, model_name)
    # HF cache format: models--{org}--{model}
    safe_name = f"models--{repo.replace('/', '--')}"
    cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
    return os.path.join(cache_dir, safe_name)

def get_dir_size(path):
    """Get total size of a directory, following symlinks."""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=True):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                # Follow symlinks to get real file size
                total_size += os.path.getsize(os.path.realpath(fp))
            except:
                pass
    return total_size

def check_model(model_name):
    """Check if a model is downloaded."""
    try:
        cache_path = get_hf_cache_path(model_name)
        
        # Check if the model directory exists and has content
        if os.path.exists(cache_path):
            # Check for snapshots directory (indicates downloaded model)
            snapshots_dir = os.path.join(cache_path, "snapshots")
            if os.path.exists(snapshots_dir):
                # Check if there's at least one snapshot with files
                for snapshot in os.listdir(snapshots_dir):
                    snapshot_path = os.path.join(snapshots_dir, snapshot)
                    if os.path.isdir(snapshot_path):
                        # Check for model files (including in subdirectories)
                        has_model = False
                        for root, dirs, files in os.walk(snapshot_path):
                            if any(f.endswith('.onnx') or f.endswith('.bin') or f == 'config.json' for f in files):
                                has_model = True
                                break
                        
                        if has_model:
                            # Get total size (following symlinks)
                            total_size = get_dir_size(snapshot_path)
                            
                            if total_size > 1024 * 1024 * 1024:
                                size_str = f"{total_size / (1024 * 1024 * 1024):.1f}GB"
                            else:
                                size_str = f"{total_size / (1024 * 1024):.0f}MB"
                            
                            return {
                                "downloaded": True, 
                                "path": snapshot_path,
                                "size": size_str
                            }
        
        return {"downloaded": False}
    except Exception as e:
        return {"downloaded": False, "error": str(e)}

def download_model(model_name):
    """Download a model."""
    try:
        import onnx_asr
        
        print(json.dumps({"status": "downloading", "model": model_name}), flush=True)
        
        # This will download the model if not present
        model = onnx_asr.load_model(model_name, providers=["CPUExecutionProvider"])
        
        # Verify it's now downloaded
        status = check_model(model_name)
        
        print(json.dumps({"status": "done", "model": model_name, **status}), flush=True)
        return {"success": True, **status}
    except Exception as e:
        error_msg = str(e)
        print(json.dumps({"status": "error", "error": error_msg}), flush=True)
        return {"success": False, "error": error_msg}

def list_models():
    """List available models with their download status."""
    models = []
    for name, repo in MODEL_REPOS.items():
        status = check_model(name)
        models.append({
            "name": name,
            "repo": repo,
            "downloaded": status.get("downloaded", False),
            "size": status.get("size"),
        })
    return models

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=str, help="Check if model is downloaded")
    parser.add_argument("--download", type=str, help="Download a model")
    parser.add_argument("--list", action="store_true", help="List available models")
    
    args = parser.parse_args()
    
    if args.check:
        result = check_model(args.check)
        print(json.dumps(result))
    elif args.download:
        result = download_model(args.download)
        if not result.get("success"):
            sys.exit(1)
    elif args.list:
        models = list_models()
        print(json.dumps(models))
    else:
        # Default: list models
        models = list_models()
        print(json.dumps(models, indent=2))

if __name__ == "__main__":
    main()
