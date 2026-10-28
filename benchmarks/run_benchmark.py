"""Benchmark the TTS engines on this machine.

For each engine: load it (timed), warm it up once, then render each script in
`scripts.json` several times through the app's real pipeline (`generate_speech`)
and record speed and peak GPU memory. Afterwards every render is transcribed with
Whisper and compared with the script (word/character error rate), as a check
that the speech is understandable.

Run from the repo root with the GPU venv:

    .\\env\\Scripts\\python -m benchmarks.run_benchmark --engines kokoro,xtts

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.models.schemas import AudioFormat, GenerateRequest  # noqa: E402
from app.services import engines as engines_module  # noqa: E402
from app.services.synthesis_service import generate_speech  # noqa: E402
from app.utils.text_processing import prepare_chunks  # noqa: E402

from benchmarks.metrics import ErrorCounts, score  # noqa: E402
from benchmarks.report import render_markdown  # noqa: E402

VOICES = {"kokoro": "af_heart", "xtts": "xtts_ana"}


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
    info: dict[str, Any] = {"os": os_name, "cpu": platform.processor(), "python": platform.python_version()}
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
                capture_output=True, text=True, timeout=10,
            )  # fmt: skip
            info["driver"] = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def render(text: str, voice_id: str) -> tuple[dict[str, Any], Path]:
    """One render through the app pipeline. Returns timings and the wav path."""
    resp = generate_speech(
        GenerateRequest(text=text, voice_id=voice_id, output_format=AudioFormat.WAV, generate_subtitles=False)
    )
    synthesis_ms = int(resp.real_time_factor * resp.duration_seconds * 1000)
    wav = get_settings().OUTPUTS_DIR / f"{resp.job_id}.wav"
    return {"synthesis_ms": synthesis_ms, "audio_seconds": resp.duration_seconds}, wav


def bench_engine(name: str, scripts: list[dict], repeats: int) -> dict[str, Any]:
    torch = _torch()
    if torch is not None:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        base_mb = torch.cuda.memory_allocated() / 2**20

    engine = engines_module.get_engine(name)
    t0 = time.perf_counter()
    engine.load()
    load_ms = int((time.perf_counter() - t0) * 1000)
    render("Warm up.", VOICES[name])  # discarded: first-call GPU setup

    rows = []
    for script in scripts:
        runs = [render(script["text"], VOICES[name]) for _ in range(repeats)]
        synth = [r[0]["synthesis_ms"] for r in runs]
        audio_s = statistics.median(r[0]["audio_seconds"] for r in runs)
        rows.append(
            {
                "id": script["id"],
                "kind": script["kind"],
                "chars": len(script["text"]),
                "chunks": len(prepare_chunks(script["text"])),
                "audio_seconds": round(audio_s, 3),
                "synthesis_ms": synth,
                "synthesis_ms_p50": int(statistics.median(synth)),
                "rtf": round(statistics.median(synth) / 1000 / audio_s, 4) if audio_s else None,
                "_audio_path": str(runs[0][1]),
            }
        )
        took = rows[-1]["synthesis_ms_p50"]
        print(f"  {name:6} {script['id']:13} {audio_s:6.2f}s audio  synthesis {took:6d} ms")

    peak_mb = round(torch.cuda.max_memory_allocated() / 2**20 - base_mb, 1) if torch is not None else None
    engine.unload()
    engines_module._engines.pop(name, None)
    gc.collect()
    if torch is not None:
        torch.cuda.empty_cache()
    return {"voice": VOICES[name], "load_ms": load_ms, "peak_vram_mb": peak_mb, "scripts": rows}


def transcribe_all(results: dict[str, Any], scripts: list[dict], asr_model: str) -> None:
    """Whisper round-trip: transcribe each render and score it against its script."""
    from transformers import pipeline

    torch = _torch()
    asr = pipeline(
        "automatic-speech-recognition",
        model=asr_model,
        device=0 if torch is not None else -1,
        torch_dtype=torch.float16 if torch is not None else None,
        chunk_length_s=30,
    )
    expected = {s["id"]: " ".join(c.text for c in prepare_chunks(s["text"])) for s in scripts}
    for engine in results.values():
        total = ErrorCounts(0, 0, 0, 0)
        for row in engine["scripts"]:
            heard = asr(row.pop("_audio_path"))["text"].strip()
            counts = score(expected[row["id"]], heard)
            total = total + counts
            row.update(transcript=heard, wer=round(counts.wer, 4), cer=round(counts.cer, 4))
        engine["corpus_wer"] = round(total.wer, 4)
        engine["corpus_cer"] = round(total.cer, 4)


def summarize(engine: dict[str, Any]) -> dict[str, Any]:
    rows = engine["scripts"]
    total_audio = sum(r["audio_seconds"] for r in rows)
    total_synth = sum(r["synthesis_ms_p50"] for r in rows) / 1000
    return {
        "rtf_p50": round(statistics.median(r["rtf"] for r in rows if r["rtf"] is not None), 4),
        "x_realtime": round(total_audio / total_synth, 1) if total_synth else None,
        "latency_ms_short": next((r["synthesis_ms_p50"] for r in rows if r["id"] == "short"), None),
        "wer": engine.get("corpus_wer"),
        "cer": engine.get("corpus_cer"),
        "scripts": len(rows),
    }


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:  # outside the repo
        return path.as_posix()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engines", default="kokoro,xtts")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--asr-model", default="openai/whisper-small.en")
    p.add_argument("--skip-asr", action="store_true")
    p.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    p.add_argument("--report", type=Path, default=ROOT / "docs" / "BENCHMARK.md")
    p.add_argument("--render-only", type=Path, help="re-make the markdown report from a saved results JSON")
    args = p.parse_args()

    if args.render_only:
        run = json.loads(args.render_only.read_text(encoding="utf-8"))
        args.report.write_text(render_markdown(run, _rel(args.render_only)), encoding="utf-8")
        print(f"rendered {args.report}")
        return 0

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    scripts = json.loads((ROOT / "benchmarks" / "scripts.json").read_text(encoding="utf-8"))["scripts"]
    names = [e.strip() for e in args.engines.split(",") if e.strip()]
    started = datetime.now(timezone.utc)
    hw = hardware_info()
    print(f"Benchmarking {names} on {hw.get('gpu', 'CPU')}: {len(scripts)} scripts x {args.repeats} repeats")

    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="voix-bench-") as tmp:
        settings.OUTPUTS_DIR = Path(tmp)  # keep benchmark renders out of the app's outputs folder
        results = {name: bench_engine(name, scripts, args.repeats) for name in names}
        if args.skip_asr:
            for engine in results.values():
                for row in engine["scripts"]:
                    row.pop("_audio_path", None)
        else:
            print(f"[asr] transcribing with {args.asr_model}")
            transcribe_all(results, scripts, args.asr_model)

    for engine in results.values():
        engine["summary"] = summarize(engine)

    run = {
        "host": socket.gethostname(),
        "started_at": started.isoformat(),
        "hardware": hw,
        "settings": {"repeats": args.repeats, "asr_model": None if args.skip_asr else args.asr_model},
        "engines": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"{started.strftime('%Y%m%dT%H%M%SZ')}-{run['host']}.json"
    out_file.write_text(json.dumps(run, indent=2), encoding="utf-8")
    args.report.write_text(render_markdown(run, _rel(out_file)), encoding="utf-8")
    print(f"wrote {_rel(out_file)} and {_rel(args.report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
