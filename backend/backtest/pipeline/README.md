# Historical Validation and Candidate Model Pipeline

This package implements a non-interactive, offline-replayable pipeline with a strict serial boundary:

1. Phase A discovers or captures a slate, archives immutable evidence, completes final full-pool actuals, applies qualification gates, and runs deterministic random, legacy, and current-optimized backtests.
2. Phase B reads only registry entries in `qualified` or `backtested`, builds an event-time-safe dataset, trains separate hitter and pitcher deterministic ridge candidates, evaluates a fixed chronological holdout plus expanding walk-forward folds, and writes a candidate model and promotion report.

The pipeline never edits production projection defaults, deploys a model, creates a scheduler, or migrates a database.

## Commands

```bash
cd backend
python -m backtest.pipeline.cli run-cycle --config backtest/pipeline.example.json
python -m backtest.pipeline.cli verify-registry --config backtest/pipeline.example.json
```

See `reports/history-model-upgrade/RUNBOOK.md` for inbox contracts, evidence requirements, offline replay, and scheduler examples.
