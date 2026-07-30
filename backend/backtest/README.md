# Deterministic MLB DFS Backtest

This package compares three lineup-generation methods on frozen pre-lock slate snapshots:

- `random`: seeded random-utility optimization. Each player receives a deterministic SHA-256-derived random priority for each lineup, and the exact solver selects the highest-priority legal roster. This is a clearly defined legal-random baseline, not rejection sampling and not a claim of uniform sampling over every feasible lineup.
- `legacy`: the unmodified optimizer implementation from the supplied source baseline, kept in `services/optimizer_legacy.py`. Its output is still passed through the new canonical validator. A slate fails if legacy returns fewer lineups or any illegal lineup.
- `optimized`: projection-first exact optimization with a predeclared 3.5% deterministic penalty per prior appearance and a seeded micro tie-break. No post-game field is used.

## Hard data boundary

Feature and scoring data are separate files. A slate uses:

- `<slate>.features.json`: frozen pre-lock player pool, salaries, positions, availability, batting order, projections, feature values, source timestamps, `snapshot_as_of`, `lock_time`, and optimizer settings.
- `<slate>.actuals.json`: controlled post-game import containing only player IDs, actual DFS points, scoring source/version, and acquisition/source timestamps.

The contracts reject:

- `snapshot_as_of > lock_time`;
- source timestamps later than the snapshot;
- naive timestamps without a timezone;
- feature keys containing post-game semantics such as `actual`, `final`, `result`, `outcome`, `winner`, `postgame`, or `boxscore`;
- duplicate player IDs;
- non-exact full-pool actual coverage, including missing or extra player IDs;
- non-finite actual points;
- feature/actual `slate_id`, `site`, or `data_kind` mismatches;
- actual scoring timestamps earlier than `slate_start`;
- unequal lineup counts or any lineup that fails canonical validation.

The optimizer runner never calls `pybaseball`, live provider endpoints, `.env`, cookies, or user data. The separate historical acquisition CLI may call the official MLB StatsAPI only when explicitly invoked; every response is content-addressed and can be replayed offline.

## Schemas and sample

- `schemas/slate-features.schema.json`
- `schemas/slate-actuals.schema.json`
- `fixtures/smoke/fixture-dk-2026-07-01-main.features.json`
- `fixtures/smoke/fixture-dk-2026-07-01-main.actuals.json`

The smoke fixture is deliberately labeled `data_kind: fixture`. It is only an end-to-end test and is excluded from acceptance calculations.

## CLI

Run from `backend/`:

```bash
PYTHONPATH=. python -m backtest.cli \
  --seed 20260729 \
  --site dk \
  --slate-dir backtest/fixtures/smoke \
  --lineups-per-method 2 \
  --output-dir ../../backtest-output \
  --noninferiority-margin 0.02 \
  --min-real-slates 30 \
  --bootstrap-samples 2000
```

Required arguments are `seed`, `site`, `slate-dir`, `lineups-per-method`, and `output-dir`.

## Output

For each valid slate:

- `<slate>.lineups.json` and `.csv`: method, players, slots, salary, projected points, actual points, and canonical legality result.
- `<slate>.summary.json`: per-method means, paired differences, source metadata, and input hashes.

For the complete run:

- `summary.json` and `.csv`;
- `failures.json` and `.csv` with explicit skipped/failed reasons.

JSON is written with sorted keys and stable newlines. CSV rows and fields are emitted in fixed order. Given identical input bytes, parameters, seed, Python/runtime behavior, and method implementations, output files are byte-reproducible. The test suite runs the same backtest twice and compares a whole-tree SHA-256.

## Acceptance gates

Only `data_kind: real` slates count. At least 30 valid real slates are required before any performance gate is evaluated.

- optimized mean actual points vs random: at least +10%;
- optimized beats random on at least 60% of slates;
- optimized vs legacy: non-inferiority margin defaults to 2%, meaning optimized mean actual points must be at least 98% of legacy.

The non-inferiority margin is declared before execution with `--noninferiority-margin`. The report also includes paired bootstrap 95% intervals and standard error. Threshold status and statistical uncertainty are reported separately.

## Importing real scoring data

This implementation uses a controlled-import contract rather than reconstructing scores from play-by-play. The importer must calculate or obtain site-specific final DFS points under a named scoring rules version, then persist:

- `site` (`dk` or `fd`);
- `scoring_source`;
- `scoring_rules_version`;
- `source_timestamp`;
- `acquired_at`;
- one finite `actual_points` value per frozen player.

A real-data delivery should also include a source/provenance note describing access rights and the exact export or scoring procedure. Do not relabel fixtures or synthetic data as `real`.

## Provenance-bound real data

`data_kind: real` is not trusted by itself. A real slate must be bound to a
`provenance-manifest.json` whose raw artifacts and derived feature, actuals, identity,
and QA files all match SHA-256 values. The runner also requires an exact provider
DraftGroup/Game Set identifier, at least two declared games, platform player IDs,
full game assignment, historical availability timestamps, and independent postgame
statistics plus a scoring-rules artifact.

The accepted timestamp semantics distinguish when an artifact was retrieved from when
its contents were historically available. A retrospective archive may be downloaded
after the games, but each pregame artifact must carry an auditable `effective_at` /
`available_at` no later than `snapshot_as_of`. Local file modification time and a
manually typed timestamp are not accepted timestamp bases.

Run a real dataset with an explicit manifest:

```bash
PYTHONPATH=. python -m backtest.cli \
  --seed 20260729 \
  --site dk \
  --slate-dir /path/to/qualified-dk-slates \
  --provenance-manifest /path/to/qualified-dk-slates/provenance-manifest.json \
  --lineups-per-method 20 \
  --output-dir /path/to/results \
  --noninferiority-margin 0.02 \
  --min-real-slates 30 \
  --bootstrap-samples 2000
```

## Historical acquisition and build CLI

Run these commands from `backend/`.

### Capture a current/future DraftKings salary export

The capture command uses the runtime clock at archive time. It does not accept a user-supplied historical timestamp, refuses a fresh capture at or after the first listed game lock, and records that historical backfill is unsupported. A repeated invocation against an existing matching manifest replays the immutable archive rather than rewriting its timestamp.

```bash
PYTHONPATH=. python -m backtest.historical.cli capture-current-slate \
  --salary-csv /path/to/DKSalaries.csv \
  --source-url 'https://www.draftkings.com/lineup/upload' \
  --draft-group-id '<observed-id-if-available>' \
  --output-dir /path/to/archive/2026-07-30-dk-mlb
```

Optional raw provider metadata may be archived with `--provider-metadata` and `--provider-metadata-url`. Capturing those bytes does not by itself verify an official DraftGroup/Game Set. The manifest therefore remains `provider_game_set_verified=false` until an independent audit establishes that binding.

### Reconstruct full-pool actuals from official MLB StatsAPI feeds

The online run downloads each declared final game feed into an immutable URL-keyed cache and writes exact raw response bytes into the output archive:

```bash
PYTHONPATH=. python -m backtest.historical.cli build-statsapi-actuals \
  --features /path/to/slate.features.json \
  --cache-dir /path/to/immutable-statsapi-cache \
  --output-dir /path/to/slate-actuals
```

After the first successful acquisition, the same build is reproducible without DNS or network access:

```bash
PYTHONPATH=. python -m backtest.historical.cli build-statsapi-actuals \
  --features /path/to/slate.features.json \
  --cache-dir /path/to/immutable-statsapi-cache \
  --output-dir /path/to/offline-replay \
  --offline
```

An offline cache miss, body/meta mismatch, URL mismatch, byte-count mismatch, hash mismatch, non-final game, game ID mismatch, or boxscore identity ambiguity is a hard failure. Players in the salary pool who have no game appearance receive an explicit DNP status and `0.0` points; they are not silently omitted.

A checked-in offline fixture is available at:

- `backtest/fixtures/statsapi-full-pool.features.json`
- `backtest/fixtures/statsapi-cache/`

### Build from a fully audited historical bundle

The legacy historical builder consumes an audited bundle containing a DraftKings salary CSV, exact provider Game Set metadata, stable MLB identities, strict pre-first-pitch historical game statistics, independent final game statistics, and scoring rules. It now requires explicit postgame evidence for every salary-pool player rather than converting missing rows into zero points.

```bash
PYTHONPATH=. python -m backtest.historical.cli build-slate \
  --bundle /path/to/bundle.json \
  --output-dir /path/to/qualified-dk-slates

PYTHONPATH=. python -m backtest.historical.cli verify-manifest \
  --slate-dir /path/to/qualified-dk-slates
```

The small `fixtures/historical-builder` bundle is synthetic and permanently labeled `fixture`. It tests ingestion, identity mapping, cutoff logic, scoring, QA, and all three optimizer methods. It cannot count toward real-slate gates.

Additional schemas:

- `schemas/historical-build-bundle.schema.json`
- `schemas/provenance-manifest.schema.json`

## Strict projection cutoff

Real feature snapshots reject DraftKings `AvgPointsPerGame` and equivalent ambiguous field names. The historical projection implementation uses only games whose final `completed_at` is strictly earlier than the player's slate first pitch. Rows completed exactly at the cutoff or later are excluded and listed in the projection audit. Real historical rows without a timezone-aware `completed_at` fail ingestion.

## Selected-only actuals are disabled by default

Full salary-pool actual coverage is the default contract. `selected_lineup_players` is restricted to `LIMITED_SINGLE_SLATE_VALIDATION` and requires all of the following:

1. the CLI flag `--allow-limited-selected-actuals`;
2. the exact acknowledgement `--acknowledge-selected-only-risk SELECTED_ONLY_ACTUALS_NOT_GENERALIZABLE`;
3. a matching selection seed in the actuals file;
4. the exact SHA-256 of the feature file used when those players were selected.

Changing the seed or any feature bytes causes a hard failure before evaluation.

## Checked-in 2023-03-10 daily-pool limitation

The checked-in `dk-mlb-2023-03-10-historical-daily-pool` remains a deliberately limited public historical daily pool:

- `scope=historical_daily_pool`;
- `provider_game_set_verified=false`;
- `validation_scope=LIMITED_SINGLE_SLATE_VALIDATION`;
- every salary is 4500;
- the ambiguous `AvgPointsPerGame` field is excluded from optimization;
- its old selected-only actuals are bound to the prior feature hash and no longer match the isolated projection file.

Consequently the dataset now fails closed rather than producing an informational performance score. It remains useful only for parser, provenance, and negative-contract checks. It does not satisfy a regular-season, non-uniform salary validation and cannot upgrade the project beyond `LIMITED_SINGLE_SLATE_VALIDATION`.
