"""Generate real traffic against a running VOIX stack (API + worker).

Creates a few demo users and submits real TTS jobs through the public API, so
the analytics views have genuine data: real queue waits, real render times,
real cancellations, and real failures (a script that is only punctuation has
nothing to speak, which the worker rejects permanently).

    api\\.venv\\Scripts\\python scripts\\loadgen.py --users 4 --jobs 40 --xtts-share 0.15

Nothing here is simulated: every number in the analytics page comes from these
jobs running on the worker.
"""

from __future__ import annotations

import argparse
import json
import random
import secrets
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
_BENCH = json.loads((ROOT / "benchmarks" / "scripts.json").read_text(encoding="utf-8"))
SCRIPTS = [s["text"] for s in _BENCH["scripts"]]
EXTRA = [
    "Thanks for watching. If this helped, you know what to do.",
    "Chapter two. The road north was longer than anyone had promised.",
    "Your order has shipped and should arrive later this week.",
    "Breathe in slowly, hold for a moment, and let it go.",
]
UNSPEAKABLE = "... !!! ???"  # passes API validation, but nothing is left to synthesise


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--users", type=int, default=4)
    p.add_argument("--jobs", type=int, default=40)
    p.add_argument("--xtts-share", type=float, default=0.15, help="fraction of jobs on XTTS (slow)")
    p.add_argument("--cancel-share", type=float, default=0.05)
    p.add_argument("--bad-share", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    rng = random.Random(args.seed)

    http = httpx.Client(base_url=args.api, timeout=60)
    run_tag = secrets.token_hex(3)
    users = []
    for i in range(args.users):
        email = f"loadgen-{run_tag}-{i}@example.com"
        r = http.post("/v1/auth/register", json={"email": email, "password": secrets.token_urlsafe(16)})
        r.raise_for_status()
        users.append({"email": email, "h": {"Authorization": f"Bearer {r.json()['access_token']}"}})
    voices = http.get("/v1/voices", headers=users[0]["h"]).json()
    kokoro = [v["id"] for v in voices if v["engine"] == "kokoro" and v["is_system"]]
    xtts = [v["id"] for v in voices if v["engine"] == "xtts" and v["is_system"]]
    print(f"{len(users)} users, {len(kokoro)} kokoro + {len(xtts)} xtts voices; submitting {args.jobs} jobs")

    submitted = []
    for _ in range(args.jobs):
        user = rng.choice(users)
        roll = rng.random()
        text = UNSPEAKABLE if roll < args.bad_share else rng.choice(SCRIPTS + EXTRA)
        pool = xtts if (xtts and rng.random() < args.xtts_share) else kokoro
        body = {
            "voice_id": rng.choice(pool),
            "text": text,
            "speed": rng.choice([0.9, 1.0, 1.0, 1.1, 1.25]),
            "output_format": rng.choice(["mp3", "mp3", "wav"]),
        }
        r = http.post("/v1/jobs/tts", json=body, headers=user["h"])
        if r.status_code == 429:  # respect the per-user rate limit like a real client
            wait = int(r.headers.get("Retry-After", "5"))
            print(f"  rate limited; sleeping {wait}s")
            time.sleep(wait)
            r = http.post("/v1/jobs/tts", json=body, headers=user["h"])
        r.raise_for_status()
        job = r.json()
        submitted.append((user, job["id"]))
        if rng.random() < args.cancel_share:
            http.post(f"/v1/jobs/{job['id']}/cancel", headers=user["h"])
        time.sleep(rng.uniform(0.2, 2.0))  # arrivals spread out, so queue waits vary

    print("waiting for the worker to drain the queue…")
    pending = list(submitted)
    statuses: dict[str, int] = {}
    while pending:
        time.sleep(3)
        still = []
        for user, job_id in pending:
            status = http.get(f"/v1/jobs/{job_id}", headers=user["h"]).json()["status"]
            if status in ("queued", "running"):
                still.append((user, job_id))
            else:
                statuses[status] = statuses.get(status, 0) + 1
        pending = still
        print(f"  {len(pending)} still queued/running")
    print("done:", statuses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
