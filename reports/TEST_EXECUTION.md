# Test and Tool Execution Record

## Environment

- Audit date: 2026-07-29
- Sandbox Python: 3.13.5
- Project requirement: Python >=3.12
- Node: 22.16.0
- npm: 10.9.2
- Source archive SHA-256: verified as `3736365f4a3c3a2262c8af9e57cd54dd19a9a664c10a41b32352dd7e6704acdf`
- `.env`, secrets, cookies, private repositories, user data, deployment, database migration, Git commit/push/PR: not accessed or performed

The archive has no `.git` directory, so the declared commit `e0683a36af54c1c5c6259f300c51ee5f7abfdb19` could not be independently reconstructed from Git objects. Archive identity was verified by the supplied SHA-256.

## Dependency installation

`uv sync --frozen --extra dev` was attempted in an isolated virtual environment. It failed while downloading the locked `pillow 12.2.0` package because the sandbox could not resolve the PyPI host. The original output is preserved in `test-logs/DEPENDENCY_INSTALL.log`.

Consequences:

- `pydfs-lineup-optimizer` could not be imported or executed in this sandbox;
- `apscheduler` could not be imported;
- `ruff` was unavailable and could not be installed.

## Baseline tests before modification

Command, run from `backend/`:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Result: **51 run, 2 failures, 3 errors**.

- 2 import errors: missing `apscheduler` in `test_content` and `test_scheduler`;
- 1 old-optimizer error in the test that expected pitcher-vs-batter relaxation;
- 1 failure because pydfs was missing but the old test expected no fallback warning;
- 1 FanDuel legality failure: the old fallback selected five hitters from one team.

Log: `test-logs/BASELINE_UNITTEST.log`.

## Added and modified focused tests

Command, run from repository root:

```bash
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_optimizer \
  backend.tests.test_lineup_rules \
  backend.tests.test_backtest -v
```

Result: **36/36 PASS** in 19.736 seconds.

Coverage includes DK/FD roster shape and salary rules, exact requested count, lock, exclude, lock/exclude conflicts, minimum salary, stacks, site team-limit infeasibility, pitcher-vs-batter and missing-opponent strictness, max exposure, uniqueness, duplicate IDs in both requests and lineups, multi-position assignment, actual serialized slot validation, metadata tampering, deterministic seed behavior, random projection independence, future snapshot rejection, semantic post-game feature rejection, timezone/provenance checks, unequal method-count rejection, immutable 30-real-slate gate, summary mathematics, and byte-level reproducibility.

Log: `test-logs/FOCUSED_UNITTEST.log`.

## Full backend unittest after modification

Command, run from repository root:

```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -v
```

Result: **82 discovered, 80 passed, 2 import errors** in 19.964 seconds.

The only errors are unchanged environment blockers:

- `test_content`: `ModuleNotFoundError: No module named 'apscheduler'`;
- `test_scheduler`: `ModuleNotFoundError: No module named 'apscheduler'`.

No importable test failed. The runnable subset excluding those two dependency-blocked modules was also executed explicitly: **80/80 PASS** in 19.604 seconds.

Logs:

- `test-logs/FULL_UNITTEST.log`
- `test-logs/RUNNABLE_UNITTEST.log`

## Compile and import checks

- `python3 -m compileall` over all changed Python modules and tests: **PASS**.
- Direct imports of optimizer, preserved legacy optimizer, canonical validator, backtest contracts/runner/CLI/I/O/statistics, schemas, and optimizer router: **PASS**.
- Exact Python 3.12 execution: **NOT RUN**, because only Python 3.13.5 was available.

Logs:

- `test-logs/COMPILE_CHECKS.log`
- `test-logs/IMPORT_CHECKS.log`

## Ruff

`python3 -m ruff --version` returned `No module named ruff`. Installation was blocked by the same DNS failure. Status: **NOT RUN, ENVIRONMENT BLOCKED**.

Log: `test-logs/RUFF.log`.

## Frontend

No frontend source file was modified. Typecheck, lint, and production build are **NOT APPLICABLE** to this patch.

## End-to-end smoke and reproducibility

The separate fixture feature/actual files were run twice using identical parameters into independent output directories. The full output-tree hashes were:

```text
run_1_tree_sha256=5565b518f112022cee32c5e167776bf1ad3f83257960335b16f0e3223c4fa0e5
run_2_tree_sha256=5565b518f112022cee32c5e167776bf1ad3f83257960335b16f0e3223c4fa0e5
byte_reproducible=PASS
```

The fixture is labeled `data_kind: fixture`, is excluded from every real-data gate, and does not constitute a 30-slate historical validation.

Outputs and proof: `smoke-results/`.

## Unified diff validation

The generated unified diff was parsed against a fresh copy of the supplied baseline with:

```bash
patch -p1 --dry-run < MlbOptimizer-e0683a3-optimizer-audit.patch
```

Result: **PASS**. Log: `test-logs/PATCH_DRY_RUN.log`.
