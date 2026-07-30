# Superseded run instructions

> The command below is retained for provenance archaeology. Under the 2026-07-30 risk-resolution contracts it must fail closed because selected-only actuals are disabled by default and are bound to the old feature SHA-256. Use `../historical-risk-resolution/REPRODUCE.md` for current commands.

# Download and run

## Immutable source download

```bash
curl -L --fail \
  -o KengoA_fantasy-ga_a5645d7_DKSalaries.csv \
  https://raw.githubusercontent.com/KengoA/fantasy-ga/a5645d7c2f955db62e776dc6c2a1889e7769aa72/examples/DraftKings/MLB/DKSalaries.csv
printf "%s  %s\n" \
  2dd420d7d39097a61e9c6f02a585fcc40bf4fa31192ede8f84037109310da40e \
  KengoA_fantasy-ga_a5645d7_DKSalaries.csv | sha256sum -c -
```

## Verify provenance

```bash
cd backend
PYTHONPATH=. python -m backtest.historical.cli verify-manifest \
  --slate-dir backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool \
  --manifest backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool/provenance-manifest.json
```

## Run LIMITED VALIDATION

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

The production/full-study default remains `--min-real-slates 30`.
