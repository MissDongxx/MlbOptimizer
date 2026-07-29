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
- missing actual points for any frozen player;
- non-finite actual points;
- feature/actual `slate_id`, `site`, or `data_kind` mismatches;
- actual scoring timestamps earlier than `slate_start`;
- unequal lineup counts or any lineup that fails canonical validation.

The backtest package never calls `pybaseball`, live provider endpoints, `.env`, cookies, or user data.

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

## Historical build CLI

The builder consumes an audited bundle containing an original DraftKings salary CSV,
exact provider Game Set metadata, a stable MLB identity reference, strictly prior-date
historical game statistics, independent final game statistics, and the applicable
DraftKings scoring rules artifact.

```bash
PYTHONPATH=. python -m backtest.historical.cli build-slate \
  --bundle /path/to/bundle.json \
  --output-dir /path/to/qualified-dk-slates

PYTHONPATH=. python -m backtest.historical.cli verify-manifest \
  --slate-dir /path/to/qualified-dk-slates
```

The small `fixtures/historical-builder` bundle is synthetic and permanently labeled
`fixture`. It tests ingestion, identity mapping, cutoff logic, official-rule scoring,
QA, and all three optimizer methods. It never creates a provenance manifest and cannot
count toward the 30-real-slate gate.

Additional schemas:

- `schemas/historical-build-bundle.schema.json`
- `schemas/provenance-manifest.schema.json`

## Single-slate historical daily-pool validation

The checked-in `dk-mlb-2023-03-10-historical-daily-pool` dataset is a deliberately
limited validation. Its commit-pinned DraftKings-format CSV is a real public historical
daily player pool, but no official DraftGroup/Main Game Set identity is claimed. It is
therefore labeled:

- `scope=historical_daily_pool`;
- `provider_game_set_verified=false`;
- `validation_scope=LIMITED_SINGLE_SLATE_VALIDATION`;
- `uniform_salary_warning` because all 345 salaries are 4500.

The full-study default remains 30 real slates. A one-slate pipeline check must opt in:

```bash
PYTHONPATH=. python -m backtest.cli \
  --seed 20260729 \
  --site dk \
  --slate-dir backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool \
  --provenance-manifest backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool/provenance-manifest.json \
  --lineups-per-method 1 \
  --output-dir /tmp/dk-single-slate-run \
  --noninferiority-margin 0.02 \
  --min-real-slates 1 \
  --bootstrap-samples 2000
```

In this mode the minimum-count gate may pass, but the +10%, slate-win-rate, and legacy
non-inferiority gates stay `NOT EVALUATED`. The actual scores are informational only.
