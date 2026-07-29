from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.historical.builder import HistoricalBuilderError, HistoricalSlateBuilder
from backtest.provenance import ProvenanceError, ProvenanceIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and verify provenance-bound historical DK MLB Classic slates."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-slate", help="Build one slate from an audited bundle")
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)

    verify = subparsers.add_parser("verify-manifest", help="Verify raw and derived hashes")
    verify.add_argument("--slate-dir", type=Path, required=True)
    verify.add_argument("--manifest", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build-slate":
            result = HistoricalSlateBuilder(args.bundle, args.output_dir).build()
        else:
            index = ProvenanceIndex.load(args.slate_dir, args.manifest)
            result = {
                "dataset_id": index.manifest.dataset_id,
                "manifest_sha256": index.manifest_sha256,
                "artifact_count": len(index.manifest.artifacts),
                "qualified_real_slates": len(index.manifest.slates),
                "status": "PASS",
            }
    except (HistoricalBuilderError, ProvenanceError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
