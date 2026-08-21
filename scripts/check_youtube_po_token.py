#!/usr/bin/env python3
"""Report optional authenticated YouTube PO-token provider readiness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.youtube_po_token import inspect_po_token_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check YouTube PO-token provider readiness")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = inspect_po_token_readiness()
    if args.json:
        print(json.dumps(status.as_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"youtube_po_token={status.reason} "
            f"auth_enabled={status.authenticated_access_enabled} "
            f"auth_ready={status.authentication_ready} "
            f"client={status.client}"
        )
    return 0 if (not status.authenticated_access_enabled or status.authentication_ready) else 1


if __name__ == "__main__":
    raise SystemExit(main())
