"""Torch device selection.

Centralises Apple Metal (MPS) / CUDA / CPU detection so every inference
service uses the same accelerator when available. Lazily imports torch so
this module is safe to import in environments that don't have torch.
"""

from __future__ import annotations

import os


def get_torch_device() -> str:
    """Return the best available torch device string.

    Preference order: mps → cuda → cpu. Can be forced via the
    ``TORCH_DEVICE`` env var (useful for debugging).
    """
    forced = os.environ.get("TORCH_DEVICE")
    if forced:
        return forced

    try:
        import torch
    except ImportError:
        return "cpu"

    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def describe_device() -> str:
    """Return a short human-readable label for the chosen device."""
    device = get_torch_device()
    return {"mps": "Apple Metal (MPS)", "cuda": "CUDA", "cpu": "CPU"}.get(device, device)
