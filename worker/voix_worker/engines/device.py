"""GPU/CPU device auto-detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    device: str  # "cuda" or "cpu"
    gpu_available: bool
    gpu_name: str | None = None
    gpu_memory_gb: float | None = None
    use_fp16: bool = False


def detect_device(preference: str = "auto", use_fp16: bool = False) -> DeviceInfo:
    """
    Auto-detect the best available compute device, honoring the
    DEVICE override ('auto' | 'cuda' | 'cpu').
    """
    preference = preference.lower()

    try:
        import torch
    except ImportError:
        logger.warning("PyTorch not importable; forcing CPU mode")
        return DeviceInfo(device="cpu", gpu_available=False)

    cuda_available = torch.cuda.is_available()

    if preference == "cpu":
        logger.info("DEVICE=cpu -> forcing CPU execution")
        return DeviceInfo(device="cpu", gpu_available=cuda_available)

    if preference == "cuda" and not cuda_available:
        logger.warning("DEVICE=cuda but no CUDA device detected; falling back to CPU")
        return DeviceInfo(device="cpu", gpu_available=False)

    if not cuda_available:
        logger.info("No CUDA-capable GPU detected; using CPU mode")
        return DeviceInfo(device="cpu", gpu_available=False)

    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    use_fp16 = use_fp16 and gpu_mem_gb >= 4.0

    logger.info(
        "CUDA device detected: %s (%.1f GB VRAM) -> using GPU, fp16=%s",
        gpu_name,
        gpu_mem_gb,
        use_fp16,
    )

    return DeviceInfo(
        device="cuda",
        gpu_available=True,
        gpu_name=gpu_name,
        gpu_memory_gb=round(gpu_mem_gb, 1),
        use_fp16=use_fp16,
    )
