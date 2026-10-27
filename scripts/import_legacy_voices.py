"""Import voices cloned with the old single-user app (backend/voices/custom/*.wav)
into a VOIX account as private cloned voices.

Goes through the public API like any client, so each upload is consent-gated
and audit-logged, then prepared by a worker. Nothing on disk is modified.

    python scripts/import_legacy_voices.py --email you@example.com --i-have-consent
    (prompts for the password; or set VOIX_PASSWORD)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LEGACY_DIR = ROOT / "backend" / "voices"
STATEMENT = (
    "Legacy import from the pre-SaaS VOIX app: the account owner attests that every speaker "
    "in these recordings gave explicit permission for their voice to be cloned."
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--email", required=True)
    p.add_argument("--legacy-dir", type=Path, default=LEGACY_DIR)
    p.add_argument(
        "--i-have-consent",
        action="store_true",
        help="required: you confirm you have each speaker's permission to clone their voice",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.i_have_consent:
        p.error("refusing to import cloned voices without --i-have-consent")

    registry_file = args.legacy_dir / "voice_registry.json"
    names = {}
    if registry_file.exists():
        names = {v["voice_id"]: v["name"] for v in json.loads(registry_file.read_text(encoding="utf-8"))}
    clips = sorted((args.legacy_dir / "custom").glob("*.wav"))
    if not clips:
        print(f"No legacy clips found in {args.legacy_dir / 'custom'}")
        return 0

    for clip in clips:
        print(f"  {clip.name}  ->  {names.get(clip.stem, clip.stem)!r}  ({clip.stat().st_size / 1e6:.1f} MB)")
    if args.dry_run:
        return 0

    password = os.environ.get("VOIX_PASSWORD") or getpass.getpass(f"Password for {args.email}: ")
    with httpx.Client(base_url=args.api, timeout=120) as http:
        login = http.post("/v1/auth/login", json={"email": args.email, "password": password})
        if login.status_code != 200:
            print(f"Login failed: {login.text}", file=sys.stderr)
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        existing = {v["name"] for v in http.get("/v1/voices", headers=headers).json() if not v["is_system"]}

        for clip in clips:
            name = names.get(clip.stem, clip.stem)
            if name in existing:
                print(f"skip   {name!r} (already imported)")
                continue
            with clip.open("rb") as fh:
                resp = http.post(
                    "/v1/voices",
                    headers=headers,
                    data={"name": name, "consent": "true", "consent_statement": STATEMENT},
                    files={"file": (clip.name, fh, "audio/wav")},
                )
            if resp.status_code == 202:
                print(f"queued {name!r}: voice {resp.json()['voice']['id']} (a worker will prepare it)")
            else:
                print(f"FAILED {name!r}: {resp.status_code} {resp.text}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
