"""Entry point: `python -m voix_worker [--once] [--engines kokoro,xtts]`."""

from __future__ import annotations

import argparse
import logging

from voix_worker import __version__
from voix_worker.client import WorkerClient
from voix_worker.config import WorkerSettings
from voix_worker.engines.registry import build_engines, gpu_name
from voix_worker.runner import Worker, build_lanes, run_lanes


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="voix_worker", description="VOIX GPU worker (pulls jobs from the API)"
    )
    parser.add_argument("--engines", help="comma-separated engines, overrides ENGINES")
    parser.add_argument("--once", action="store_true", help="process at most one job, then exit")
    parser.add_argument(
        "--preload", action="store_true", help="load models at startup instead of on first job"
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)-5s %(name)s: %(message)s"
    )
    overrides = {"engines": args.engines} if args.engines else {}
    settings = WorkerSettings(**overrides)

    engines = build_engines(settings)
    if args.preload:
        for engine in engines.values():
            engine.load()

    gpu = gpu_name() if set(engines) - {"mock"} else None

    def make_client(name: str, engine_names: list[str]) -> WorkerClient:
        return WorkerClient.create(
            settings.api_url,
            settings.worker_token.get_secret_value(),
            settings.request_timeout_seconds + settings.poll_wait_seconds,
            worker_name=name,
            engines=engine_names,
            gpu=gpu,
            version=__version__,
            max_retries=settings.max_retries,
        )

    if args.once:
        worker = Worker(make_client(settings.worker_name, list(engines)), engines, settings)
        worker.install_signal_handlers()
        worker.client.register()
        worker.run_once(wait_seconds=settings.poll_wait_seconds)
        return
    run_lanes(build_lanes(make_client, engines, settings, settings.worker_name))


if __name__ == "__main__":
    main()
