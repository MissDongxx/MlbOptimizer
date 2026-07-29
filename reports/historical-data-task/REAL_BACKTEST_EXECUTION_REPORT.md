# Real Historical Backtest Execution Report

Execution date: 2026-07-29  
Platform: DraftKings MLB Classic  
Seed: 20260729  
Predeclared non-inferiority margin: 2%  
Required real slates: 30

## Executive result

**Overall task status: FAIL.**

No legal, no-login, no-paywall source was found that provides 30 exact historical DraftKings MLB Classic DraftGroups with provable original pre-lock salary/position pools. Consequently, zero slates can be truthfully marked `data_kind=real`, and the requested real random/legacy/optimized evaluation cannot be calculated.

This is a data-availability failure, not a claimed algorithm failure or success. No projection tuning, date cherry-picking, random-baseline adjustment, or minimum-slate reduction was performed.

## Acceptance status

| Requirement | Status | Evidence/result |
|---|---|---|
| Input archive size and SHA-256 | PASS | 2,302,187 bytes; `bcb6d613670aa2a31bb32e5a410aa815d84d0bab982d1e0f56a0779f076e3844` |
| Audit candidate data sources | PASS | `DATA_SOURCE_AUDIT.md` and `source-audit.json` |
| Choose one platform/ruleset | PASS | DraftKings MLB Classic |
| Build at least 30 qualified real slates | FAIL | Qualified real slate count: 0 |
| Every real slate has frozen features and independent actuals | NOT EVALUATED | No slate passed source qualification |
| Run random/legacy/optimized on 30 real slates | NOT EVALUATED | No qualified real input set exists |
| Same slate/pool/count/seed for three methods | PASS for fixture regression; NOT EVALUATED for real | Runner enforces one shared request and exact count per method |
| Optimized mean at least 10% over random | NOT EVALUATED | No real metrics |
| Optimized wins at least 60% of slates | NOT EVALUATED | No real metrics |
| Optimized within 2% of legacy | NOT EVALUATED | No real metrics |
| Byte-identical repeat on real input | NOT EVALUATED | No qualified real input |
| Byte-identical builder and backtest fixture regression | PASS | Build tree hash and backtest tree hash match across two runs |
| Prevent manual `data_kind=real` relabeling | PASS | Contract plus provenance-manifest binding; regression tests pass |
| Source changes, tests, report, unified diff, ZIP | PASS | Delivery artifacts generated and hashed |
| Verify declared Git baseline commit | NOT EVALUATED | Uploaded archive has no `.git`; diff is against exact uploaded bytes |

## Real slate inventory

- Qualified real slates: **0**
- Failed source qualification candidates: source-level reasons are in `source-audit.json`
- Per-slate features/actuals pairs: none generated as real
- `min_real_slates`: unchanged at **30**

`real-slate-inventory.json` intentionally contains an empty `slates` array. Filling it with calendar-day reconstructions or relabeled fixtures would violate the task.

## Implemented source changes

1. **Strict real-data contracts**
   - exact DK Classic provider slate ID;
   - at least two declared games and exact ordered game IDs;
   - full player salary, positions, platform ID, team/opponent, and game assignment;
   - historical source availability time at or before `snapshot_as_of`;
   - postgame actual source after lock;
   - no postgame-semantic feature keys anywhere in a feature tree.

2. **Provenance manifest and hash binding**
   - raw artifact URL, local path, SHA-256, acquired/effective time, timestamp basis, temporal class, licence status;
   - exact hashes for feature, actuals, QA, and identity reports;
   - required source roles for platform slate, salary, pregame stats, postgame stats, rules, and identity reference;
   - path-escape protection and full raw artifact hash verification;
   - runner refuses real files without a valid manifest entry.

3. **Historical build CLI**
   - validates an original DK-format salary CSV;
   - matches Game Info to the declared provider Game Set;
   - maps platform IDs to MLBAM IDs without silent dropping;
   - computes fixed strictly prior-date rolling projections;
   - reconstructs actuals from independent game-stat rows under a named DK rules version;
   - emits features, actuals, identity report, QA report, raw-copy hashes, and manifest.

4. **DraftKings scoring implementation**
   - hitter single/double/triple/home run, run, RBI, walk/HBP, stolen base;
   - pitcher outs, strikeouts, win, earned runs, hits/walks/HBP allowed;
   - complete game, complete-game shutout, no-hitter bonuses;
   - outs recorded are integer outs, never baseball decimal innings.

5. **Determinism and gates**
   - random, legacy, and optimized share the same request, player pool, count, and seed;
   - all returned lineups pass canonical individual and set validation;
   - fewer than 30 real slates makes the minimum-real-slate gate `FAIL`; performance gates remain `NOT EVALUATED`;
   - output JSON/CSV order is stable.

## Fixture-only execution

A new clearly labeled synthetic builder fixture was used solely to execute the complete ingestion and backtest machinery. It cannot create a real manifest and cannot count toward acceptance.

- Valid fixture slates: 1
- Valid real slates: 0
- Failed fixture slates: 0
- Lineups per method: 2
- Random mean actual points: 127.675
- Legacy mean actual points: 143.95
- Optimized mean actual points: 143.95
- Optimized versus random: +12.7472%
- Optimized versus legacy: 0.0%

These numbers are engineering regression results only. They are not evidence of historical predictive performance.

## Reproducibility hashes

- Historical builder run 1 tree SHA-256: `543520784d36691f20039386e9161296229f7f6ce2ea92ccd62864cdf6b3c1bc`
- Historical builder run 2 tree SHA-256: `543520784d36691f20039386e9161296229f7f6ce2ea92ccd62864cdf6b3c1bc`
- Builder byte-identical: **PASS**
- Backtest run 1 tree SHA-256: `14b5829c3afac5a9cab0a313e09b871ca20e1144bddef70d921d39b6383f3424`
- Backtest run 2 tree SHA-256: `14b5829c3afac5a9cab0a313e09b871ca20e1144bddef70d921d39b6383f3424`
- Backtest byte-identical: **PASS**

The exact per-file hashes are in `REPRODUCIBILITY.json`.

## Tests

- Relevant backtest and historical-data tests: **19 passed**
- Python compilation of modified backtest modules: **PASS**
- Full backend test discovery: **NOT EVALUATED to completion** in the supplied environment. An unrelated application import test requires `apscheduler`, which is declared in `backend/pyproject.toml` but not installed in the runtime. Broad discovery also exceeded the execution limit. No dependency was silently installed or application configuration changed.

## Download/build commands

From `backend/`:

```bash
PYTHONPATH=. python -m backtest.historical.cli build-slate \
  --bundle backtest/fixtures/historical-builder/bundle.json \
  --output-dir /tmp/historical-builder-output

PYTHONPATH=. python -m backtest.cli \
  --seed 20260729 \
  --site dk \
  --slate-dir /tmp/historical-builder-output \
  --lineups-per-method 2 \
  --output-dir /tmp/historical-builder-backtest \
  --noninferiority-margin 0.02 \
  --min-real-slates 30 \
  --bootstrap-samples 2000
```

For a qualified real dataset, add:

```bash
--provenance-manifest /path/to/slates/provenance-manifest.json
```

## Unverified or unresolved risks

- RotoGuru historical salary records could not be proven to correspond to exact DraftKings DraftGroups/Main slates or to have reliable pre-lock publication timestamps.
- Third-party historical-data redistribution rights were not assumed from public visibility.
- DraftKings current API behavior is not a historical archive and its unofficial documentation explicitly warns that it is transient and unsupported.
- The exact historical rules-change boundary was not independently established because no qualified slate period was available; the code therefore requires a named versioned rules artifact.
- A provenance manifest prevents accidental/manual relabeling inside this pipeline, but it cannot cryptographically prove that an external publisher's semantic assertion is truthful. Source audit and independent evidence remain mandatory.
