"""Tests for the torch device selector."""

import sys
import types

import pytest

from app.services import device as device_module


def _install_fake_torch(monkeypatch, mps_available: bool, cuda_available: bool):
    fake_torch = types.ModuleType("torch")

    class _Backends:
        class mps:
            @staticmethod
            def is_available():
                return mps_available

    fake_torch.backends = _Backends()

    class _Cuda:
        @staticmethod
        def is_available():
            return cuda_available

    fake_torch.cuda = _Cuda()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)


class TestGetTorchDevice:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("TORCH_DEVICE", "cuda")
        assert device_module.get_torch_device() == "cuda"

    def test_mps_preferred(self, monkeypatch):
        monkeypatch.delenv("TORCH_DEVICE", raising=False)
        _install_fake_torch(monkeypatch, mps_available=True, cuda_available=True)
        assert device_module.get_torch_device() == "mps"

    def test_cuda_when_no_mps(self, monkeypatch):
        monkeypatch.delenv("TORCH_DEVICE", raising=False)
        _install_fake_torch(monkeypatch, mps_available=False, cuda_available=True)
        assert device_module.get_torch_device() == "cuda"

    def test_cpu_fallback(self, monkeypatch):
        monkeypatch.delenv("TORCH_DEVICE", raising=False)
        _install_fake_torch(monkeypatch, mps_available=False, cuda_available=False)
        assert device_module.get_torch_device() == "cpu"

    def test_no_torch_returns_cpu(self, monkeypatch):
        monkeypatch.delenv("TORCH_DEVICE", raising=False)

        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("no torch in this env")
            return real_import(name, *args, **kwargs)

        monkeypatch.setitem(sys.modules, "torch", None)
        # Also block re-import via sys.modules entry
        sys.modules.pop("torch", None)
        monkeypatch.setattr("builtins.__import__", fake_import)

        try:
            assert device_module.get_torch_device() == "cpu"
        finally:
            # restore
            monkeypatch.setattr("builtins.__import__", real_import)


class TestDescribeDevice:
    def test_descriptions(self, monkeypatch):
        monkeypatch.setenv("TORCH_DEVICE", "mps")
        assert "Metal" in device_module.describe_device()
        monkeypatch.setenv("TORCH_DEVICE", "cuda")
        assert device_module.describe_device() == "CUDA"
        monkeypatch.setenv("TORCH_DEVICE", "cpu")
        assert device_module.describe_device() == "CPU"
