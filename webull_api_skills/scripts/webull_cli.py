#!/usr/bin/env python3
"""Single entrypoint for production Webull operations (market/trade/auth)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_MAP = {
    "market": "webull_market_ops.py",
    "trade": "webull_trade_ops.py",
    "auth": "webull_auth_raw.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Webull unified CLI wrapper. Use one module and pass through module-specific args."
    )
    parser.add_argument("module", choices=list(SCRIPT_MAP.keys()), help="Module to execute")
    parser.add_argument("module_args", nargs=argparse.REMAINDER, help="Arguments forwarded to module")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_name = SCRIPT_MAP[args.module]
    script_path = Path(__file__).resolve().parent / script_name
    cmd = [sys.executable, str(script_path), *args.module_args]
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
