# Offline Cycle Example

The `executed-output` directory is a preserved evidence snapshot from the delivery run. Its JSON files intentionally contain the absolute paths of the controlled build workspace and should not be reused as a live registry.

To replay from clean state after extracting the source ZIP:

```bash
cd backend
rm -rf ../reports/history-model-upgrade/offline-example/runtime
python -m backtest.pipeline.cli run-cycle \
  --config ../reports/history-model-upgrade/offline-example/config.json
python -m backtest.pipeline.cli verify-registry \
  --config ../reports/history-model-upgrade/offline-example/config.json
```

The example uses repository fixture bytes and the checked-in StatsAPI cache. Expected outcome:

- full-pool actuals are rebuilt offline for 21 players
- one DNP is recorded as zero with evidence
- registry integrity passes
- qualification rejects the slate because it is fixture data and lacks verified provider Game Set evidence
- backtest and model performance remain NOT_EVALUATED

This example validates workflow behavior only. It is not real historical performance evidence.
