#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEFAULT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ROOT=${1:-$DEFAULT_ROOT}
PATCH="$ROOT/artifacts/seo-validator-v2.patch"
HASHES="$ROOT/artifacts/seo-validator-v2-original.sha256"

cd "$ROOT"
git apply --check -R "$PATCH"
git apply -R "$PATCH"
shasum -a 256 -c "$HASHES"

if [ -e content-pipeline/scripts/content-pipeline.test.mjs ]; then
  echo "rollback failed: new validator test still exists" >&2
  exit 1
fi

echo "SEO validator v2 rollback verified in $ROOT"
