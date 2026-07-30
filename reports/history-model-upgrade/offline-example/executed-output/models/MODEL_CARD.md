# Candidate MLB DFS Projection Model Card

- Status: **REJECTED_NOT_EVALUATED**
- Production action: **NONE**
- Production default replaced: **false**
- Dataset SHA-256: `NO_QUALIFIED_DATASET`

## Intended use

Offline, auditable candidate projection generation and lineup backtest comparison only.
It is not an instruction to deploy, promote, or replace the current production projection.

## Data and leakage controls

Only registry-qualified real slates may enter the dataset. Splits use whole chronological slate dates,
and every feature availability timestamp must be strictly earlier than the corresponding first pitch.
AvgPointsPerGame and postgame/final/boxscore/outcome fields are prohibited as model features.

## Decision

insufficient chronological slates: 0 < 25

## Known limitations

A candidate that passes the offline gates still requires independent review. Projection metrics do not
guarantee lineup-level improvement, and lineup backtests must retain random, legacy, and current optimized baselines.
