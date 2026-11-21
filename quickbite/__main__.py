"""Run generation, ingestion, and verification from the repository root."""

import argparse
import json
import logging
from pathlib import Path
import sys
from time import perf_counter

from .config import PROFILES, configuration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    generate = commands.add_parser("generate", help="Write CSVs and a checksummed manifest")
    generate.add_argument("--profile", choices=PROFILES, default="smoke")
    generate.add_argument("--seed", type=int)
    generate.add_argument("--config", type=Path, help="JSON file overriding profile parameters")
    generate.add_argument("--output", type=Path, required=True)
    ingest = commands.add_parser("ingest", help="Load and publish a verified batch")
    ingest.add_argument("--input", type=Path, required=True)
    commands.add_parser("verify", help="Verify and show the active ClickHouse snapshot")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    start = perf_counter()
    try:
        if args.action == "generate":
            from .generator import generate as generate_dataset
            result = generate_dataset(configuration(args.profile, args.config, args.seed), args.output)
        else:
            from .ingestion import ingest as load_dataset, verify
            result = load_dataset(args.input) if args.action == "ingest" else verify()
    except Exception as error:
        print(f"QuickBite {args.action} failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"seconds": round(perf_counter() - start, 3), **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
