# Delivery Summary and Acceptance Matrix

## Baseline identity

- Supplied archive: `MlbOptimizer-e0683a3-source(1).zip`
- Verified archive SHA-256: `3736365f4a3c3a2262c8af9e57cd54dd19a9a664c10a41b32352dd7e6704acdf`
- Declared commit: `e0683a36af54c1c5c6259f300c51ee5f7abfdb19`
- Commit verification: unavailable because the ZIP contains no `.git` object database; the archive hash was verified exactly.

## Outcome

The supplied repository contains no qualifying corpus of at least 30 real historical slates with frozen pre-lock snapshots and separate actual DFS points. Effectiveness is therefore **INSUFFICIENT DATA / NOT EVALUATED**. No fixture result is used as product evidence.

## Acceptance matrix

| ID | Status | Evidence |
|---|---|---|
| A. Legal lineups and strict constraints | PASS | Canonical validator gates optimized, random, preserved legacy, optional pydfs candidates, API output, and backtest. Exact N or structured failure. Focused constraint tests pass. |
| B. No future-information leakage | PASS | Separate strict feature/actual contracts reject post-lock snapshots, post-game feature semantics, missing/naive source timestamps, duplicate IDs, missing actual scores, and cross-file identity mismatches. Scoring joins only after generation. |
| C. Fair paired methods | PASS | `random`, `legacy`, and `optimized` must each generate the same configured count on the same slate; otherwise that slate fails and is recorded. |
| D. Minimum 30 real slates before gates | PASS | `data_kind: real` only; `min_real_slates` cannot be configured below 30. Fixture/synthetic slates never enter acceptance statistics. |
| E. Performance thresholds | NOT EVALUATED | Valid real slates found: 0. The +10%, 60% win-rate, and legacy non-inferiority gates are not calculated as pass/fail. |
| F. Reproducibility | PASS | Same fixture command run twice produced identical complete output-tree SHA-256 `5565b518f112022cee32c5e167776bf1ad3f83257960335b16f0e3223c4fa0e5`. |
| G. Source, tests, reports, patch, hashes | PASS | Changed/new source, schemas, fixtures, per-slate and summary outputs, audit/report/test logs, unified diff, and SHA-256 manifest are included in the delivery bundle. |

## Test status

- Added/modified focused tests: **36/36 PASS**.
- All importable backend tests: **80/80 PASS**.
- Full discovery: **82 tests, 80 pass, 2 import errors**, both caused by unavailable `apscheduler`.
- Compile/import checks: **PASS**.
- Ruff: **NOT RUN, ENVIRONMENT BLOCKED** because `ruff` was absent and PyPI DNS resolution failed.
- pydfs runtime adapter: **NOT RUN, ENVIRONMENT BLOCKED** for the same dependency-install failure. Its candidates are nevertheless rejected unless the canonical validator accepts the complete set; the production API and backtest use the deterministic strict built-in solver by default.
- Frontend checks: **NOT APPLICABLE**, because no frontend file changed.

## Primary files

- `reports/ALGORITHM_AUDIT.md`: baseline evidence, severity, risk, and fix mapping.
- `reports/BACKTEST_VALIDATION_REPORT.md`: data inventory, predeclared gates, and future real-run report template.
- `reports/TEST_EXECUTION.md`: commands, exact results, raw-error references, and reproducibility proof.
- `backend/backtest/README.md`: schemas, CLI, outputs, gates, and scoring-import contract.
