"""Offline multi-engine TTS benchmark.

For every engine: load it (timed), warm it up once, render each script
`--repeats` times through the *production* synthesis pipeline, and record
latency, real-time factor and peak VRAM. Then unload all TTS models, load
Whisper, transcribe each rendered file and score it against the text the
engine was asked to speak (WER/CER: an intelligibility proxy, not a
naturalness score).

Run from the repo root with the GPU venv:

    .\\env\\Scripts\\python -m benchmarks.run_benchmark --engines kokoro,xtts
    .\\env\\Scripts\\python -m benchmarks.run_benchmark --engines kokoro,xtts --upload   # also POST to the API

Writes benchmarks/results/<timestamp>-<host>.json and docs/BENCHMARK.md.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from benchmarks.metrics import ErrorCounts, score  # noqa: E402
from benchmarks.report import render_markdown  # noqa: E402
from voix_worker.audio.text_processing import prepare_chunks  # noqa: E402
from voix_worker.engines.base import Engine, VoiceSpec  # noqa: E402
from voix_worker.pipeline.synthesize import run_synthesis  # noqa: E402

DEFAULT_VOICES = {"kokoro": "af_heart", "xtts": "Ana Florence", "mock": "tone_a"}


def _torch():
    try:
        import torch

        return torch if torch.cuda.is_available() else None
    except ImportError:
        return None


def hardware_info() -> dict[str, Any]:
    os_name = f"{platform.system()} {platform.release()}"
    if platform.system() == "Windows" and int(platform.version().split(".")[-1]) >= 22000:
        os_name = "Windows 11"  # platform.release() still says "10" on Windows 11
    info: dict[str, Any] = {
        "os": os_name,
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
    }
    torch = _torch()
    if torch is not None:
        props = torch.cuda.get_device_properties(0)
        info.update(
            gpu=props.name,
            gpu_memory_gb=round(props.total_memory / 1024**3, 1),
            torch=torch.__version__,
            cuda=torch.version.cuda,
        )
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            info["driver"] = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def build_engine(name: str) -> Engine:
    if name == "mock":
        from voix_worker.engines.mock import MockEngine

        return MockEngine()
    if name == "kokoro":
        from voix_worker.engines.kokoro import KokoroEngine

        return KokoroEngine("hexgrad/Kokoro-82M", "auto")
    if name == "xtts":
        from voix_worker.engines.xtts import XTTSEngine

        return XTTSEngine("tts_models/multilingual/multi-dataset/xtts_v2", "auto")
    raise SystemExit(f"unknown engine {name!r}")


def spoken_text(text: str) -> str:
    """What the engine is actually asked to say, after the pipeline's normalisation."""
    return " ".join(c.text for c in prepare_chunks(text))


def bench_engine(
    name: str, voice_id: str, scripts: list[dict], repeats: int, workdir: Path
) -> dict[str, Any]:
    torch = _torch()
    if torch is not None:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        base_mb = torch.cuda.memory_allocated() / 2**20

    engine = build_engine(name)
    t0 = time.perf_counter()
    engine.load()
    load_ms = int((time.perf_counter() - t0) * 1000)
    voice = VoiceSpec(voice_id=f"bench-{voice_id}", engine_voice_id=voice_id)

    # One discarded render so first-call CUDA/kernel setup doesn't skew script 1.
    run_synthesis(
        engine, voice, {"text": "Warm up.", "output_format": "wav", "subtitles": False}, workdir / "warmup"
    )

    rows = []
    for script in scripts:
        runs = []
        for r in range(repeats):
            out = run_synthesis(
                engine,
                voice,
                {"text": script["text"], "output_format": "wav", "subtitles": False},
                workdir / name / f"{script['id']}-{r}",
            )
            m = out.result["metrics"]
            runs.append(
                {
                    "synthesis_ms": m["synthesis_ms"],
                    "processing_ms": m["processing_ms"],
                    "audio_seconds": out.result["duration_seconds"],
                    "path": str(out.audio_path),
                }
            )
        synth = [x["synthesis_ms"] for x in runs]
        audio_s = statistics.median(x["audio_seconds"] for x in runs)
        rows.append(
            {
                "id": script["id"],
                "kind": script["kind"],
                "chars": len(script["text"]),
                "chunks": len(prepare_chunks(script["text"])),
                "audio_seconds": round(audio_s, 3),
                "synthesis_ms": synth,
                "synthesis_ms_p50": int(statistics.median(synth)),
                "processing_ms_p50": int(statistics.median(x["processing_ms"] for x in runs)),
                "rtf": round(statistics.median(synth) / 1000 / audio_s, 4) if audio_s else None,
                "_audio_path": runs[0]["path"],
            }
        )
        print(
            f"  {name:6} {script['id']:13} {audio_s:6.2f}s audio  synth p50 {rows[-1]['synthesis_ms_p50']:6d} ms  RTF {rows[-1]['rtf']}"
        )

    peak_mb = None
    if torch is not None:
        peak_mb = round(torch.cuda.max_memory_allocated() / 2**20 - base_mb, 1)
    describe = engine.describe()
    engine.unload()
    del engine
    gc.collect()
    if torch is not None:
        torch.cuda.empty_cache()
    return {
        "voice": voice_id,
        "load_ms": load_ms,
        "peak_vram_mb": peak_mb,
        "describe": describe,
        "scripts": rows,
    }


def transcribe_all(results: dict[str, Any], scripts: list[dict], asr_model: str) -> None:
    from transformers import pipeline

    torch = _torch()
    asr = pipeline(
        "automatic-speech-recognition",
        model=asr_model,
        device=0 if torch is not None else -1,
        torch_dtype=torch.float16 if torch is not None else None,
        chunk_length_s=30,
    )
    texts = {s["id"]: spoken_text(s["text"]) for s in scripts}
    for engine in results.values():
        total = ErrorCounts(0, 0, 0, 0)
        for row in engine["scripts"]:
            hyp = asr(row.pop("_audio_path"))["text"].strip()
            counts = score(texts[row["id"]], hyp)
            total = total + counts
            row.update(transcript=hyp, wer=round(counts.wer, 4), cer=round(counts.cer, 4))
        engine["asr_totals"] = total.__dict__
        engine["corpus_wer"] = round(total.wer, 4)
        engine["corpus_cer"] = round(total.cer, 4)


def summarize(engine: dict[str, Any]) -> dict[str, Any]:
    rows = engine["scripts"]
    rtfs = [r["rtf"] for r in rows if r["rtf"] is not None]
    total_audio = sum(r["audio_seconds"] for r in rows)
    total_synth = sum(r["synthesis_ms_p50"] for r in rows) / 1000
    return {
        "rtf_p50": round(statistics.median(rtfs), 4),
        "rtf_overall": round(total_synth / total_audio, 4) if total_audio else None,
        "x_realtime": round(total_audio / total_synth, 1) if total_synth else None,
        "latency_ms_short": next((r["synthesis_ms_p50"] for r in rows if r["id"] == "short"), None),
        "wer": engine.get("corpus_wer"),
        "cer": engine.get("corpus_cer"),
        "scripts": len(rows),
    }


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def upload(run: dict[str, Any], api_url: str, token: str) -> str:
    import httpx

    payload = {k: run[k] for k in ("host", "started_at", "hardware")} | {"results": run}
    resp = httpx.post(
        f"{api_url.rstrip('/')}/internal/benchmarks",
        json=payload,
        headers={"X-Worker-Token": token},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engines", default="kokoro,xtts")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--asr-model", default="openai/whisper-small.en")
    p.add_argument("--skip-asr", action="store_true")
    p.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    p.add_argument("--report", type=Path, default=ROOT / "docs" / "BENCHMARK.md")
    p.add_argument("--upload", action="store_true", help="POST results to API_URL/internal/benchmarks")
    p.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8000"))
    p.add_argument("--upload-file", type=Path, help="upload an existing results JSON and exit")
    p.add_argument(
        "--render-only", type=Path, help="re-render the markdown report from a results JSON and exit"
    )
    args = p.parse_args()

    token = os.environ.get("WORKER_TOKEN", "dev-insecure-worker-token")
    if args.render_only:
        run = json.loads(args.render_only.read_text(encoding="utf-8"))
        args.report.write_text(render_markdown(run, _rel(args.render_only)), encoding="utf-8")
        print(f"rendered {_rel(args.report)}")
        return 0
    if args.upload_file:
        run = json.loads(args.upload_file.read_text(encoding="utf-8"))
        print(f"uploaded run {upload(run, args.api_url, token)} to {args.api_url}")
        return 0

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    scripts = json.loads((ROOT / "benchmarks" / "scripts.json").read_text(encoding="utf-8"))["scripts"]
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    started = datetime.now(UTC)
    hw = hardware_info()
    print(
        f"Benchmarking {engines} on {hw.get('gpu', 'CPU')} - {len(scripts)} scripts x {args.repeats} repeats"
    )

    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="voix-bench-") as tmp:
        for name in engines:
            print(f"[{name}] loading + rendering")
            results[name] = bench_engine(name, DEFAULT_VOICES[name], scripts, args.repeats, Path(tmp))
        if not args.skip_asr:
            print(f"[asr] transcribing with {args.asr_model}")
            transcribe_all(results, scripts, args.asr_model)
        else:
            for engine in results.values():
                for row in engine["scripts"]:
                    row.pop("_audio_path", None)

    for engine in results.values():
        engine["summary"] = summarize(engine)

    run = {
        "host": socket.gethostname(),
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "hardware": hw,
        "settings": {
            "repeats": args.repeats,
            "asr_model": None if args.skip_asr else args.asr_model,
            "scripts_version": 1,
        },
        "engines": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"{started.strftime('%Y%m%dT%H%M%SZ')}-{run['host']}.json"
    out_file.write_text(json.dumps(run, indent=2), encoding="utf-8")
    args.report.write_text(render_markdown(run, _rel(out_file)), encoding="utf-8")
    print(f"wrote {_rel(out_file)} and {_rel(args.report)}")

    if args.upload:
        print(f"uploaded run {upload(run, args.api_url, token)} to {args.api_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
