"""Build engine instances from config. Heavy imports stay inside each engine's
`load()`, so a mock-only worker never imports torch."""

from __future__ import annotations

from voix_worker.config import WorkerSettings
from voix_worker.engines.base import Engine


def build_engines(settings: WorkerSettings) -> dict[str, Engine]:
    engines: dict[str, Engine] = {}
    for name in settings.engines:
        if name == "mock":
            from voix_worker.engines.mock import MockEngine

            engines[name] = MockEngine()
        elif name == "xtts":
            from voix_worker.engines.xtts import XTTSEngine

            engines[name] = XTTSEngine(settings.xtts_model_name, settings.device, settings.use_fp16)
        elif name == "kokoro":
            from voix_worker.engines.kokoro import KokoroEngine

            engines[name] = KokoroEngine(settings.kokoro_repo_id, settings.device)
        else:
            raise ValueError(f"Unknown engine '{name}' (expected mock, xtts or kokoro)")
    return engines


def gpu_name() -> str | None:
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    props = torch.cuda.get_device_properties(0)
    return f"{props.name} ({props.total_memory / 1024**3:.0f} GB)"
