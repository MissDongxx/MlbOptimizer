# Superseded validation record

> **Superseded on 2026-07-30.** This file and the sibling `backtest-output/` directory preserve an earlier limited run for audit history only. They are not current validation evidence. The `AvgPointsPerGame` projection has since been isolated, selected-only actuals are now seed- and feature-hash-bound, and the corrected runner rejects this dataset. See `../historical-risk-resolution/DELIVERY_REPORT.md`.

# DraftKings MLB 2023-03-10 single-slate limited validation

## Verdict

Historical result at the time: **PASS, LIMITED VALIDATION**, now invalidated by stricter contracts. One real public DraftKings-format historical daily player pool passed provenance, identity, legality, separated-actuals, and deterministic execution checks. It is not asserted to be an official DraftGroup/Main Game Set, and it is not sufficient for algorithm-performance inference.

## Source

- Repository: `https://github.com/KengoA/fantasy-ga`
- Commit: `a5645d7c2f955db62e776dc6c2a1889e7769aa72`
- Path: `examples/DraftKings/MLB/DKSalaries.csv`
- Pinned blob: `https://github.com/KengoA/fantasy-ga/blob/a5645d7c2f955db62e776dc6c2a1889e7769aa72/examples/DraftKings/MLB/DKSalaries.csv`
- Raw bytes: **33342**
- SHA-256: `2dd420d7d39097a61e9c6f02a585fcc40bf4fa31192ede8f84037109310da40e`
- Rows: **345 players plus one header, 346 physical lines**
- Commit timestamp: 2023-03-10 14:38:51 ET
- Earliest listed first pitch: 2023-03-10 15:03:00 ET
- Classification: `historical_daily_pool`, `provider_game_set_unverified`, `LIMITED_SINGLE_SLATE_VALIDATION`

## QA

- Required columns: 9/9 present.
- Unique DK IDs: 345/345.
- Teams: 8. Games: 4. Game Info parse: 345/345.
- Nulls and duplicate rows/IDs/names: none.
- Salary: min=max=mean=4500; 345/345 uniform.
- Roster-position coverage includes P, C, 1B, 2B, 3B, SS, and OF.
- A legal 10-player DK Classic lineup exists with two pitchers, all hitter slots, four games, and no hitter team above five.

Uniform salary is an anomaly, not proof of fabrication. It removes salary trade-offs, makes every legal lineup cost 45,000, and therefore makes method comparisons economically uninterpretable. The file remains a real commit-pinned DraftKings-format daily pool.

## Identity and temporal boundary

All 345 DK IDs map to 345 unique MLBAM IDs. Twenty-six ambiguous names use explicit team/date overrides; no row is silently dropped. Feature input contains only the pregame CSV fields. The postgame evidence file and actuals JSON are separate physical artifacts, and postgame semantic keys are rejected recursively by the feature contract.

`AvgPointsPerGame` is used as the pregame projection because it existed in the commit before first pitch. Negative values are retained in audit fields and clamped to zero for optimization. Its exact upstream semantic formula is not independently documented, so a warning is preserved.

## Actuals

Actuals cover the 18 unique players selected by the three deterministic methods. Final public ESPN/FOX/MLB box-score evidence is transcribed into a separate machine-readable postgame artifact and scored under the bundled DraftKings MLB Classic rule table. Direct MLB StatsAPI raw JSON acquisition failed in this runtime because of DNS, so this is not described as a raw StatsAPI archive. It is also not a full 345-player actuals reconstruction.

## Archived backtest result, not current evidence

- Valid real slates: **1**
- Failed/skipped: **0**
- Lineups per method: **1**
- random actual: **17.0**
- legacy actual: **22.0**
- optimized actual: **22.0**
- optimized vs random: **+29.4118%**, informational only
- optimized vs legacy: **0.0%**, informational only
- All three lineups legal: **PASS**
- Long-study +10%, 60% win-rate, and 2% non-inferiority gates: **NOT EVALUATED**

## Determinism

Two independent executions with identical bytes, seed, and parameters produced the same output tree SHA-256:

`298bb0b09c7902d0a99f3d3e0787a20001c5ac0d958e0dcbf5a21b0801d85a29`

## RotoGuru correction

No RotoGuru response artifact was acquired. The only attempted endpoint was `http(s)://rotoguru1.com/cgi-bin/byday.pl`; both attempts returned no response body in this runtime. Response size, hash, and row count are therefore not available. Earlier wording that implied a verified historical daily page was found is retracted.

## Residual risks

1. Official DraftGroup/Main Game Set identity is unverified.
2. All salaries being 4500 may reflect an unusual spring-training contest or template-like provider behavior; no evidence supports changing the file to fixture, but performance interpretation is disabled.
3. The repository is MIT-licensed, while upstream DraftKings-export data rights are not separately stated. Public access and audit use are verified; broader redistribution rights remain a legal-semantic risk.
4. Actuals cover selected players only and use mixed public final box-score sources.
5. One slate cannot support statistical performance claims.
