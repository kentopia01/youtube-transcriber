#!/usr/bin/env python3
"""Pre-download MLX Whisper models so the first transcription doesn't hang.

Usage:
  python scripts/download_models.py
"""
import os
import sys


def download_mlx_models():
    """Download whisper models via huggingface_hub."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Installing huggingface_hub...")
        os.system(f"{sys.executable} -m pip install huggingface_hub -q")
        from huggingface_hub import snapshot_download

    models = [
        "mlx-community/whisper-large-v3-turbo",
        "mlx-community/whisper-tiny",
    ]

    for model in models:
        print(f"⬇️  Downloading {model}...")
        try:
            path = snapshot_download(model)
            print(f"   ✅ Cached at: {path}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

    print("\n✅ All models pre-downloaded.")


def download_embedding_model():
    """Download the nomic embedding model via sentence-transformers."""
    print("Downloading nomic-ai/nomic-embed-text-v1.5...")
    try:
        from sentence_transformers import SentenceTransformer
        SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
        print("   Cached successfully")
    except Exception as e:
        print(f"   Failed: {e}")


def download_pyannote_model():
    """Download pyannote diarization model if HF_TOKEN is set."""
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("⏭️  Skipping pyannote model (HF_TOKEN not set)")
        return

    print("⬇️  Downloading pyannote/speaker-diarization-community-1...")
    try:
        from pyannote.audio import Pipeline
        Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=hf_token
        )
        print("   ✅ pyannote model cached")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        print("   Make sure you've accepted the model agreement at:")
        print("   https://huggingface.co/pyannote/speaker-diarization-community-1")


if __name__ == "__main__":
    download_mlx_models()
    download_embedding_model()
    download_pyannote_model()
