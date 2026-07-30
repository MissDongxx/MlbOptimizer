from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.historical.builder import HistoricalBuilderError, HistoricalSlateBuilder
from backtest.historical.capture import SlateCaptureError, capture_current_dk_slate
from backtest.historical.http_cache import ImmutableHttpCache
from backtest.historical.mlb_statsapi import (
    StatsApiActualsError,
    StatsApiFullPoolActualsBuilder,
)
from backtest.provenance import ProvenanceError, ProvenanceIndex



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, capture, and verify provenance-bound MLB DFS research inputs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-slate", help="Build one slate from an audited bundle")
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)

    verify = subparsers.add_parser("verify-manifest", help="Verify raw and derived hashes")
    verify.add_argument("--slate-dir", type=Path, required=True)
    verify.add_argument("--manifest", type=Path)

    capture = subparsers.add_parser(
        "capture-current-slate",
        help="Archive an observed current/future DraftKings salary export before first lock",
    )
    capture.add_argument("--salary-csv", type=Path, required=True)
    capture.add_argument("--output-dir", type=Path, required=True)
    capture.add_argument("--source-url", required=True)
    capture.add_argument("--draft-group-id")
    capture.add_argument("--provider-metadata", type=Path)
    capture.add_argument("--provider-metadata-url")

    actuals = subparsers.add_parser(
        "build-statsapi-actuals",
        help="Build full-pool DK actuals from final official MLB StatsAPI feed/live responses",
    )
    actuals.add_argument("--features", type=Path, required=True)
    actuals.add_argument("--output-dir", type=Path, required=True)
    actuals.add_argument("--cache-dir", type=Path, required=True)
    actuals.add_argument("--offline", action="store_true")
    actuals.add_argument("--retries", type=int, default=3)
    actuals.add_argument("--timeout", type=float, default=20.0)
    actuals.add_argument(
        "--scoring-rules-artifact-id",
        default="dk-mlb-classic-rules-code-v1",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build-slate":
            result = HistoricalSlateBuilder(args.bundle, args.output_dir).build()
        elif args.command == "verify-manifest":
            index = ProvenanceIndex.load(args.slate_dir, args.manifest)
            result = {
                "dataset_id": index.manifest.dataset_id,
                "manifest_sha256": index.manifest_sha256,
                "artifact_count": len(index.manifest.artifacts),
                "qualified_real_slates": len(index.manifest.slates),
                "status": "PASS",
            }
        elif args.command == "capture-current-slate":
            result = capture_current_dk_slate(
                salary_csv=args.salary_csv,
                output_dir=args.output_dir,
                source_url=args.source_url,
                draft_group_id=args.draft_group_id,
                provider_metadata=args.provider_metadata,
                provider_metadata_url=args.provider_metadata_url,
            )
        else:
            cache = ImmutableHttpCache(args.cache_dir)
            result = StatsApiFullPoolActualsBuilder(
                feature_path=args.features,
                output_dir=args.output_dir,
                cache=cache,
                offline=args.offline,
                retries=args.retries,
                timeout=args.timeout,
                scoring_rules_artifact_id=args.scoring_rules_artifact_id,
            ).build()
    except (
        HistoricalBuilderError,
        ProvenanceError,
        SlateCaptureError,
        StatsApiActualsError,
        ValueError,
    ) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
