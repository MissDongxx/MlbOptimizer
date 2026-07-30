from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.pipeline.config import PipelineConfig
from backtest.pipeline.cycle import run_cycle
from backtest.pipeline.registry import Registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the non-interactive MLB DFS historical validation and candidate-model cycle."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    cycle = subparsers.add_parser("run-cycle", help="Capture/import, qualify, backtest, and train candidate")
    cycle.add_argument("--config", type=Path, required=True)
    verify = subparsers.add_parser("verify-registry", help="Verify all registered immutable bytes")
    verify.add_argument("--config", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PipelineConfig.from_json(args.config)
    if args.command == "run-cycle":
        result = run_cycle(config)
    else:
        failures = Registry(config.registry_path).verify_all_artifacts()
        result = {
            "status": "PASS" if not failures else "FAIL",
            "registry": str(config.registry_path),
            "failures": failures,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] not in {"FAIL", "FAILED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
