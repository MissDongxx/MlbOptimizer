from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.runner import BacktestConfig, BacktestDataError, run_backtest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic, leakage-safe MLB DFS lineup backtests."
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--site", choices=("dk", "fd"), required=True)
    parser.add_argument("--slate-dir", type=Path, required=True)
    parser.add_argument("--lineups-per-method", type=int, required=True, choices=range(1, 21))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--noninferiority-margin", type=float, default=0.02)
    parser.add_argument("--min-real-slates", type=int, default=30)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--provenance-manifest", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 0 <= args.noninferiority_margin < 1:
        raise SystemExit("--noninferiority-margin must be in [0, 1)")
    if args.min_real_slates < 1:
        raise SystemExit("--min-real-slates must be at least 1")
    if args.bootstrap_samples < 1:
        raise SystemExit("--bootstrap-samples must be at least 1")
    config = BacktestConfig(
        seed=args.seed,
        site=args.site,
        slate_dir=args.slate_dir,
        lineups_per_method=args.lineups_per_method,
        output_dir=args.output_dir,
        noninferiority_margin=args.noninferiority_margin,
        min_real_slates=args.min_real_slates,
        bootstrap_samples=args.bootstrap_samples,
        provenance_manifest=args.provenance_manifest,
    )
    try:
        summary = run_backtest(config)
    except BacktestDataError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
