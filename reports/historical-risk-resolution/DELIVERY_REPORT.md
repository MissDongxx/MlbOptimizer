# MLB DFS historical risk-resolution delivery report

Date: 2026-07-30  
Baseline commit: `5f356365725b1def066b981fed3aa5558bb06522`  
Baseline ZIP bytes: `2,415,328`  
Baseline ZIP SHA-256: `2f963d8cb02d34d0d52eb1644d494b04c93a0812e11f90affffb9406102af44b`

## Executive conclusion

The implementation now fails closed on the previously unverified paths and supplies a reproducible current-slate acquisition route. It does **not** establish long-run optimizer performance and does **not** upgrade the validation classification.

Final classification remains:

```text
LIMITED_SINGLE_SLATE_VALIDATION
INSUFFICIENT DATA / NOT EVALUATED
```

No qualified real, non-uniform, regular-season DK or FD Classic historical salary pool was added. Public candidates located during research either lacked the original salary bytes, lacked an auditable pre-lock availability timestamp, required a user's own platform export, or could not be bound to an official DraftGroup/Game Set. The existing 2023-03-10 file remains all 4500, spring training, and Game Set-unverified. Constructing a replacement would have fabricated evidence, so the residual risk is retained explicitly.

## Delivered changes

### 1. Current/future salary capture and immutable archive

Added `backtest.historical.capture` and the `capture-current-slate` CLI command.

Hard properties:

- accepts the original DraftKings CSV bytes and exact source URL;
- reads capture time from the runtime clock, not a user-supplied historical timestamp;
- rejects a fresh archive at or after the first listed lock;
- declares `historical_backfill_supported=false`;
- stores byte count and SHA-256 for every archived input;
- refuses immutable-path collisions with different bytes;
- replays an existing matching immutable manifest without rewriting its timestamp;
- validates required DK columns, unique player IDs, positive salaries, Game Info parsing, team/game consistency, game count, and salary distribution;
- never promotes a claimed DraftGroup ID or captured provider metadata to verified status;
- classifies every capture as limited until independent provider Game Set verification.

### 2. Official MLB StatsAPI raw-response cache and full-pool actuals builder

Added:

- `backtest.historical.http_cache.ImmutableHttpCache`;
- `backtest.historical.mlb_statsapi.StatsApiFullPoolActualsBuilder`;
- `build-statsapi-actuals` CLI command.

The builder uses one declared game assignment per salary-pool player and exact MLBAM IDs. For each game it archives the exact response body from:

```text
https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live
```

The cache is keyed by SHA-256 of the URL and stores paired immutable body/metadata files. It verifies URL, key, byte count, body SHA-256, JSON validity, gamePk, final status, and identity consistency. Online acquisition has bounded retry and timeout parameters. `--offline` forbids network access and fails on any missing or damaged cache entry.

Actuals reconstruction:

- covers every feature/salary-pool MLBAM ID exactly once;
- reconstructs DK Classic hitter and pitcher points from final boxscore components;
- records per-player source game, source artifact, scoring components, and status;
- marks absent/no-appearance players explicitly as DNP with `0.0` points;
- rejects boxscore key/person-ID disagreement and duplicate identities;
- writes raw response files, identity audit, coverage audit, and output hashes.

The checked-in fixture demonstrates 21/21 coverage, 20 played, 1 explicit DNP, zero missing IDs, and zero extra IDs. It is labeled fixture and is not production validation.

### 3. Projection leakage isolation

The ambiguous DraftKings `AvgPointsPerGame` field is no longer used by the checked-in real daily-pool feature file. The contract rejects that projection source and semantically equivalent feature keys for real data.

The rolling projection implementation now uses an exclusive, timezone-aware first-pitch cutoff:

```text
historical_game.completed_at < slate_first_pitch
```

Rows completed exactly at first pitch or later are excluded. Real historical feature input without `completed_at` fails ingestion. Audits include the exclusive cutoff, IDs of games used, and blocked-row count.

Because no auditable pregame history was available for the 2023 daily pool, its feature file uses an explicitly isolated fixed role prior, not `AvgPointsPerGame`. This preserves parser/constraint testing but provides no claim of predictive quality.

### 4. Actuals completeness and selected-only containment

Full salary-pool actual coverage is now the default runner contract. Missing **or extra** actual player IDs fail the slate.

The legacy historical builder also now requires an explicit postgame row for every salary-pool player. It no longer converts a missing source row into an unexplained zero.

Selected-only actuals require all four controls:

1. limited daily-pool scope;
2. command-line opt-in;
3. exact risk acknowledgement;
4. matching seed and exact feature-file SHA-256.

Changing a seed fails before optimization. Changing any feature bytes fails before optimization. The old 2023 selected-only actuals are intentionally bound to the pre-isolation feature hash, so they cannot be reused with the corrected projection file.

### 5. Determinism

Deterministic paths include sorted players, games, artifact IDs, JSON keys, and fixed newline encoding. The same offline feature/cache inputs generated byte-identical output trees in two independent directories.

Offline fixture tree SHA-256:

```text
fa7566847c8fa5878d96a74b4dfb49ad5590127b441a455e8e9698ee4f2c8763
```

Fixture actuals SHA-256:

```text
189c321d2a17f27b233fcd99a9dd0174ddeb0dd8649709640f6b4f1c8ed14084
```

A fresh current-slate capture necessarily observes the runtime clock as an external input. Once created, the archive is immutable and later invocations replay the original manifest instead of generating a new timestamp.

## Existing optimizer/API boundaries

No production configuration, database, deployment, user data, or API contract was intentionally changed. The legacy optimizer remains present. Existing tests continue to cover:

- DK and FD roster sizes and position slots;
- canonical legality validation;
- salary cap and minimum salary;
- lock handling and infeasible locks;
- exclusion and lock/exclude conflicts;
- stack count and site team limits;
- pitcher-versus-batter rules;
- structured no-solution reasons;
- deterministic optimized and random modes;
- legacy baseline execution.

## Test execution

### Passed

```text
PYTHONPATH=. pytest -q --ignore=tests/test_content.py --ignore=tests/test_scheduler.py
```

Result: `106 passed in 19.66s`. The command transcript is recorded in `TEST_EXECUTION.txt`.

```text
PYTHONPATH=. python -m compileall -q backtest tests models services routers main.py
```

Result: pass.

The limited 2023 provenance manifest verifies after all derived-file hash updates.

The dedicated risk tests cover:

- current capture before lock;
- exact-lock and post-lock rejection;
- immutable replay;
- non-uniform salary recognition;
- provider Game Set downgrade;
- cache retry and offline replay;
- offline cache miss hard failure;
- full-pool coverage;
- explicit DNP=0;
- missing and extra full-pool actual failures;
- historical builder missing-evidence failure;
- identity ambiguity failure;
- strict cutoff leakage prevention;
- AvgPointsPerGame rejection;
- selected-only double confirmation;
- seed binding;
- feature-hash binding;
- byte-level deterministic replay.

### Environment-blocked gates

The complete unignored pytest collection could not run because `apscheduler` is absent. The project lock/dependency environment was checked rather than silently bypassed:

- `uv sync --frozen` failed on DNS while downloading locked dependencies;
- direct `pip install apscheduler...` failed because the configured internal index had no APScheduler distribution;
- editable pip install additionally exposed the repository's pre-existing setuptools flat-layout package-discovery error;
- `npm ci` failed because the configured internal registry returned 404 for a locked package;
- frontend typecheck/build therefore did not run;
- Ruff was declared but unavailable because dependency installation was blocked.

The original command output is preserved in `ENVIRONMENT_BLOCKERS.txt`. These are reported as **not run / environment blocked**, not pass.

## Data-source and provider audit

### Existing 2023-03-10 public file

- repository: `https://github.com/KengoA/fantasy-ga`
- commit: `a5645d7c2f955db62e776dc6c2a1889e7769aa72`
- blob: `https://github.com/KengoA/fantasy-ga/blob/a5645d7c2f955db62e776dc6c2a1889e7769aa72/examples/DraftKings/MLB/DKSalaries.csv`
- raw: `https://raw.githubusercontent.com/KengoA/fantasy-ga/a5645d7c2f955db62e776dc6c2a1889e7769aa72/examples/DraftKings/MLB/DKSalaries.csv`
- commit timestamp: `2023-03-11T04:38:51+09:00` / `2023-03-10T14:38:51-05:00`
- bytes: `33,342`
- SHA-256: `2dd420d7d39097a61e9c6f02a585fcc40bf4fa31192ede8f84037109310da40e`
- rows: 345 players, 8 teams, 4 games
- salaries: 345 values, all 4500
- Game Set: unverified
- projection field: excluded
- actuals: selected-only legacy evidence, intentionally unusable with corrected feature hash

The commit timestamp predates the first listed lock by about 24 minutes, but a repository commit does not prove that the CSV is an official main-slate export or establish the provider DraftGroup. The all-equal salary distribution eliminates meaningful salary-price optimization. The file therefore remains limited evidence only.

### Official/provider references used by the workflow

- MLB StatsAPI root: `https://statsapi.mlb.com/api/`
- MLB game feed endpoint: `https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live`
- DraftKings MLB rules: `https://www.draftkings.com/help/rules/2`

A DraftKings salary CSV observed by the user can be archived, but authenticated platform access and exact DraftGroup metadata are not invented by this code.

## Result table

No qualifying real non-uniform regular-season slate was obtained, so no optimizer performance result table is reported.

| Dataset | Real salary evidence | Full-pool actuals | Game Set verified | Projection cutoff | Evaluation |
|---|---:|---:|---:|---:|---|
| 2023-03-10 public daily pool | Real format, all 4500 | No, old selected-only evidence | No | Ambiguous field excluded | Hard fail, limited only |
| StatsAPI offline fixture | Fixture only | 21/21, including DNP | Fixture only | Fixture contract | Pipeline test only |
| Future captured slate | Workflow delivered | Builder delivered | Defaults to no | Rolling builder delivered | Not yet captured |

## Residual risks and required next evidence

The validation level must remain limited until all of the following exist for enough slates:

1. original non-uniform regular-season DK or FD Classic salary exports captured before lock;
2. immutable capture time evidence;
3. exact official DraftGroup/Game Set binding or an explicit downgraded category;
4. first-party final game feeds cached for every declared game;
5. exact salary-pool identity coverage and explicit DNP handling;
6. auditable pregame rolling features with strict timestamps;
7. multiple slates sufficient for the predeclared long-run thresholds.

No claim in this delivery should be read as production validation, model edge, profitability, or satisfaction of the 30-slate performance gate.
