# Single-slate Codex independent validation

Date: 2026-07-29

## Verdict

PASS as a limited pipeline validation only. This does not establish long-run optimizer performance.

## Source verification

- Source: `KengoA/fantasy-ga`
- Commit: `a5645d7c2f955db62e776dc6c2a1889e7769aa72`
- File: `examples/DraftKings/MLB/DKSalaries.csv`
- Independently downloaded size: 33,342 bytes
- Independently downloaded SHA-256: `2dd420d7d39097a61e9c6f02a585fcc40bf4fa31192ede8f84037109310da40e`
- The independently downloaded file is byte-identical to the checked-in raw artifact.
- Classification: `historical_daily_pool`; the official DraftGroup/Main Game Set is not verified.

## Delivery verification

- ZIP size: 325,076 bytes
- ZIP SHA-256: `d3615cbd6eadb6d88f665f97d90914e1917d91062da827ebafb0fe32d6d8c331`
- Patch size: 736,214 bytes
- Patch SHA-256: `05149c98246e704e9df0eab385b618fdb054af18fcedea482d0e6a5da8ded361`
- Cumulative patch dry-run and isolated application: PASS
- Manifest verification: PASS (`artifact_count=6`, `qualified_real_slates=1`)

## Independent tests

- Focused backtest/historical tests: 19/19 PASS
- Single-slate contract test: 1/1 PASS
- Full backend discovery: 94 tests discovered; 93 PASS, 1 import error
- Existing environment issue: `test_content` cannot import Starlette `TestClient` because the local environment lacks `httpx2`.
- Two independent real-data executions with the same seed and parameters: byte-identical output trees.
- `git diff --check`: PASS

## Real-data run

- Slate: `dk-mlb-2023-03-10-historical-daily-pool`
- Pool: 345 players, 8 teams, 4 games
- Lineups per method: 1
- Random actual points: 17
- Legacy actual points: 22
- Optimized actual points: 22
- All three lineups: legal
- Optimized versus random: +29.4118%, informational only
- Optimized versus legacy: 0%, informational only

## Material limitations

1. All 345 salaries are 4,500, so salary optimization behavior is not meaningfully tested.
2. This is a spring-training daily pool, not a verified official Main Game Set.
3. `AvgPointsPerGame` existed before lock but its upstream formula is undocumented.
4. Actuals cover only the 18 players selected by the fixed-seed run. The runner explicitly fails if a selected player lacks an actual and disallows this coverage mode outside limited validation.
5. Postgame evidence was transcribed from mixed public final box scores because raw MLB StatsAPI acquisition failed in the external runtime.
6. One slate cannot support the original +10%, 60% win-rate, non-inferiority, confidence-interval, or statistical-significance claims.

## Repository state

Changes are local only. No files were staged or committed, and nothing was pushed, deployed, or migrated.
