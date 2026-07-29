# MLB DFS Optimizer Backtest Validation Report

## Evaluation status

**INSUFFICIENT DATA / NOT EVALUATED**

The supplied archive contains **0 valid real historical slates** with both an auditable pre-lock snapshot and separate actual DFS scoring. The required minimum is 30. No effectiveness threshold is evaluated from the included fixture.

## Dataset inventory

| Data kind | Valid slates | Used for acceptance |
|---|---:|---|
| Real | 0 | Yes, but minimum not met |
| Fixture | 1 | No |
| Synthetic | 0 | No |

The repository’s only pre-existing JSON data file was `backend/cache/player_logs_2026-07-29.json`; it is not a complete frozen DFS slate and has no separate actual-points file.

## Predeclared methods

- `random`: seeded random-utility legal optimizer, no projection or post-game field in the objective.
- `legacy`: exact supplied `optimizer.py` preserved as `optimizer_legacy.py`, then canonically validated.
- `optimized`: frozen projection plus deterministic 3.5% prior-appearance diversity penalty.

## Predeclared gates

| Gate | Threshold | Current status |
|---|---:|---|
| Valid real slates | >= 30 | NOT EVALUATED |
| Optimized mean actual vs random | >= +10% | NOT EVALUATED |
| Slate win rate vs random | >= 60% | NOT EVALUATED |
| Optimized vs legacy non-inferiority | >= -2% default, configurable before run | NOT EVALUATED |

“Threshold passed” and “statistical certainty” are separate. The runner reports paired bootstrap 95% intervals and standard errors but does not replace the predeclared point-estimate gates with a post-hoc rule.

## Smoke fixture result

The fixture proves only that the pipeline executes, validates all three methods, joins scoring after generation, writes outputs, and is byte-reproducible. It is deliberately labeled `fixture` and excluded from the gates.

Final generated smoke results are included under `reports/smoke-results/`. See `summary.json` for the exact fixture-only numbers and `REPRODUCIBILITY.txt` for the two-run tree hashes.

## Template for a future real-data run

Fill this section only after a qualifying run:

- Data acquisition/provenance note:
- Number of submitted feature files:
- Number of valid real slates:
- Number and reasons of failed/skipped slates:
- Frozen method version/hash:
- Seed and lineups per method:
- Non-inferiority margin declared before run:
- Optimized/random mean actual points and relative lift:
- Slate win rate:
- Optimized/legacy difference:
- Paired bootstrap intervals and standard errors:
- Gate result:
- Known data quality limitations:

Do not change the method or acceptance thresholds after inspecting actual scoring without versioning a new evaluation.
