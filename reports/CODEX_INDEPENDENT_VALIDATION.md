# Codex Independent Validation

Date: 2026-07-29  
Baseline: `dev` at `e0683a36af54c1c5c6259f300c51ee5f7abfdb19`

## Source handoff

- Sanitized source ZIP: `MlbOptimizer-e0683a3-source.zip`
- Size: 2,246,150 bytes
- SHA-256: `3736365f4a3c3a2262c8af9e57cd54dd19a9a664c10a41b32352dd7e6704acdf`
- The archive was produced from `git archive HEAD`; `.git`, real environment files, private keys,
  caches, dependencies, build outputs, browser state, and runtime state were not included.
- A tracked-source secret-pattern scan returned no matches before upload.

## External-engineer delivery verification

- ChatGPT conversation:
  `https://chatgpt.com/c/6a69bbf4-3dd0-83ee-a3b2-d63b5e2440dc`
- Unified diff size: 325,605 bytes
- Unified diff SHA-256:
  `60ef074ba19e1f6738ea1081cf1adb99debb035438d241ff93155f4ac7e03fa2`
- `patch -p1 --dry-run` passed against an isolated `git archive` extraction of the baseline.
- The claimed delivery ZIP was not independently available: both the original ZIP button and the
  corrected/re-attached ZIP button downloaded the same unified diff above. The diff nevertheless
  contained all modified/new source, fixtures, reports, results, and test logs and applied cleanly.

## Independent test results

- Focused optimizer, validator, and backtest tests: **36/36 passed**.
- Full backend discovery: **84 discovered; 83 passed; 1 import error**.
  - The import error is the pre-existing `test_content` environment issue:
    Starlette's `TestClient` requires the `httpx2` package, which is not installed in the current
    backend virtual environment.
- Python `compileall` for backtest, models, routers, services, and tests: **passed**.
- FastAPI `main` module import and optimizer executor shutdown: **passed** outside the restricted
  sandbox (the sandbox itself blocks `ProcessPoolExecutor` system-limit inspection).
- Frontend TypeScript check: **passed**.
- Frontend production build: **passed** outside the restricted sandbox.
  - One pre-existing Turbopack NFT trace warning was emitted from `next.config.mjs` / blog sitemap
    imports.
- Frontend lint command: **blocked by repository configuration**.
  - `npm --prefix frontend run lint` invokes `next lint`, which Next.js 16 interprets as a project
    directory and fails with `Invalid project directory .../frontend/lint`.
- Ruff: **not run** because Ruff is not installed in the existing virtual environment.
- `git diff --check`: **passed**.
- A secret-pattern scan over all new/modified source, tests, fixtures, and reports returned no
  matches.

The built-in deterministic solver was also benchmarked against the existing mock DK pool:

```text
1 lineup:   0.124 s
5 lineups:  0.937 s
20 lineups: 3.543 s
```

For comparison, the optional pydfs candidate path took 66.86 seconds for five lineups on the same
pool, while the default strict built-in path took 0.842 seconds. This supports keeping the new
built-in path as the current default, but it is not a production-scale live-slate load test.

## Reproducibility and smoke backtest

The fixture backtest CLI was run twice with identical inputs:

```text
seed=20260729
site=dk
lineups_per_method=2
min_real_slates=30
bootstrap_samples=2000
```

The two output directories were byte-identical under recursive `diff`. The fixture was correctly
reported as:

```text
INSUFFICIENT DATA / NOT EVALUATED
```

It is a pipeline smoke test only and is not evidence that the optimized method beats either
baseline on real historical contests.

## Acceptance status

- Legal lineup generation and strict user constraints: **PASS for implemented automated coverage**.
- No silent relaxation and exact requested lineup count: **PASS for implemented automated coverage**.
- Frozen pre-lock/independent post-game data contracts: **PASS for implemented automated coverage**.
- Random/legacy/optimized equal-count comparison: **PASS for the fixture pipeline**.
- Deterministic repeated outputs: **PASS for the fixture pipeline**.
- At least 30 qualifying real historical slates: **NOT EVALUATED (0 available)**.
- Optimized average actual score at least 10% above random: **NOT EVALUATED**.
- Optimized beats random on at least 60% of real slates: **NOT EVALUATED**.
- Optimized non-inferior to legacy on real slates: **NOT EVALUATED**.

No commit, push, pull request, deployment, database migration, production configuration change, or
real-user-data operation was performed.

## Independent platform-rule check

- DraftKings' current Classic overview confirms the general $50,000 salary cap:
  <https://help.draftkings.com/hc/en-us/articles/24807418578707-Game-Style-Classic-Overview-US>
- DraftKings' MLB Classic explainer lists 10 roster slots
  (`P, P, C, 1B/DH, 2B, 3B, SS, OF, OF, OF`) and up to five players from one team:
  <https://dknetwork.draftkings.com/2020/05/29/beginner-mlb-dfs-game-types/>
- FanDuel's MLB guide confirms the $35,000 cap and nine slots
  (`P, C/1B, 2B, SS, 3B, OF, OF, OF, UTIL`):
  <https://www.fanduel.com/mlb-guide/>
- FanDuel's current rules allow up to five players from one team only when one is a pitcher, which
  is equivalent to the implementation's maximum of four hitters plus an optional same-team pitcher:
  <https://www.fanduel.com/rules/>
