"""python -m voix_api.analytics [build|drop|show MODEL]"""

from __future__ import annotations

import sys

from voix_api import analytics
from voix_api.config import get_settings
from voix_api.db import init_engine


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "build"
    engine = init_engine(get_settings().database_url)
    if cmd == "build":
        print("built:", " -> ".join(analytics.build(engine)))
    elif cmd == "drop":
        with engine.begin() as conn:
            analytics.drop(conn)
        print("dropped analytics views")
    elif cmd == "show" and len(argv) > 1:
        print(analytics.render(analytics.load_models()[argv[1]], engine.dialect.name))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
