# Reproduction commands

Run from `backend/` unless stated otherwise.

## 1. Test the risk-resolution code and all runnable backend tests

```bash
PYTHONPATH=. pytest -q \
  --ignore=tests/test_content.py \
  --ignore=tests/test_scheduler.py
```

The two ignored modules import APScheduler during collection. Do not ignore them in an environment where the locked dependencies can be installed:

```bash
uv sync --frozen
PYTHONPATH=. pytest -q
```

## 2. Compile Python sources

```bash
PYTHONPATH=. python -m compileall -q \
  backtest tests models services routers main.py
```

## 3. Verify the limited 2023 provenance manifest

```bash
PYTHONPATH=. python -m backtest.historical.cli verify-manifest \
  --slate-dir backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool
```

## 4. Reproduce the offline full-pool actuals fixture

```bash
rm -rf /tmp/mlb-statsapi-offline-replay
PYTHONPATH=. python -m backtest.historical.cli build-statsapi-actuals \
  --features backtest/fixtures/statsapi-full-pool.features.json \
  --cache-dir backtest/fixtures/statsapi-cache \
  --output-dir /tmp/mlb-statsapi-offline-replay \
  --offline
```

Expected coverage:

```text
feature_player_count=21
records_count=21
played_count=20
dnp_count=1
missing_ids=[]
extra_ids=[]
status=PASS_FULL_POOL
```

The checked-in expected replay is under:

```text
reports/historical-risk-resolution/offline-fixture-replay/
```

## 5. Capture a current/future DraftKings MLB Classic salary export

Use a CSV downloaded while the slate is still open. The command records the runtime clock and does not accept a manually typed historical capture time.

```bash
PYTHONPATH=. python -m backtest.historical.cli capture-current-slate \
  --salary-csv /absolute/path/to/DKSalaries.csv \
  --source-url 'https://www.draftkings.com/lineup/upload' \
  --draft-group-id '<observed-draft-group-id-if-available>' \
  --output-dir /absolute/path/to/archive/YYYY-MM-DD-dk-mlb
```

Optional provider response bytes can be archived too:

```bash
  --provider-metadata /absolute/path/to/provider-response.json \
  --provider-metadata-url '<exact-observed-provider-url>'
```

This still remains `provider_game_set_verified=false` until an independent reviewer proves the response is the official DraftGroup/Game Set for the salary export.

## 6. Fetch and cache final MLB StatsAPI feeds, then replay offline

Online acquisition:

```bash
PYTHONPATH=. python -m backtest.historical.cli build-statsapi-actuals \
  --features /archive/slate.features.json \
  --cache-dir /archive/http-cache \
  --output-dir /archive/actuals
```

Offline replay:

```bash
PYTHONPATH=. python -m backtest.historical.cli build-statsapi-actuals \
  --features /archive/slate.features.json \
  --cache-dir /archive/http-cache \
  --output-dir /archive/actuals-replay \
  --offline
```

## 7. Demonstrate that the old selected-only sample fails closed

Default mode fails because selected-only actuals are disabled:

```bash
PYTHONPATH=. python -m backtest.cli \
  --seed 20260729 \
  --site dk \
  --slate-dir backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool \
  --provenance-manifest backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool/provenance-manifest.json \
  --lineups-per-method 1 \
  --output-dir /tmp/limited-default \
  --min-real-slates 1 \
  --bootstrap-samples 20
```

Even with both explicit confirmations, it fails because the selected actuals are bound to the old feature SHA-256 and the ambiguous projection field has now been isolated:

```bash
PYTHONPATH=. python -m backtest.cli \
  --seed 20260729 \
  --site dk \
  --slate-dir backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool \
  --provenance-manifest backtest/data/real-validation/dk-mlb-2023-03-10-historical-daily-pool/provenance-manifest.json \
  --lineups-per-method 1 \
  --output-dir /tmp/limited-explicit \
  --min-real-slates 1 \
  --bootstrap-samples 20 \
  --allow-limited-selected-actuals \
  --acknowledge-selected-only-risk SELECTED_ONLY_ACTUALS_NOT_GENERALIZABLE
```
