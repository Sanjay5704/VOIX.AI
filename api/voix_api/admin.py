"""Operator commands.

python -m voix_api.admin promote you@example.com     # grant analytics access
python -m voix_api.admin demote  you@example.com
python -m voix_api.admin set-plan you@example.com pro
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from voix_api.config import get_settings
from voix_api.db import init_engine, session_factory
from voix_api.models import User


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voix_api.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("promote", "demote"):
        sub.add_parser(name).add_argument("email")
    plan = sub.add_parser("set-plan")
    plan.add_argument("email")
    plan.add_argument("plan")
    args = parser.parse_args(argv)

    settings = get_settings()
    init_engine(settings.database_url)
    with session_factory()() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            print(f"No user with email {args.email}", file=sys.stderr)
            return 1
        if args.cmd == "set-plan":
            if args.plan not in settings.plan_quotas:
                print(f"Unknown plan; choose from {sorted(settings.plan_quotas)}", file=sys.stderr)
                return 1
            user.plan = args.plan
        else:
            user.is_admin = args.cmd == "promote"
        db.commit()
        print(f"{user.email}: plan={user.plan} admin={user.is_admin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
