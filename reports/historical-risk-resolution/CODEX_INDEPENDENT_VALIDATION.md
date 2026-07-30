# Codex Independent Validation

Date: 2026-07-29 (Asia/Shanghai)

## Baseline and external artifacts

- Git baseline: `5f356365725b1def066b981fed3aa5558bb06522`
- Input archive: `MlbOptimizer-5f35636-risk-resolution.zip`
- Input archive bytes: `2,415,328`
- Input archive SHA-256: `2f963d8cb02d34d0d52eb1644d494b04c93a0812e11f90affffb9406102af44b`
- External patch bytes: `530,946`
- External patch SHA-256: `70b266e923879512352f0771bab8103ee28dc798d98342b40bbff20cb331d86d`
- External complete ZIP bytes: `2,452,486`
- External complete ZIP SHA-256: `2193abcf5549747af74fc7ebee33868c6f62ff171c5d164d4849adef60ee72a8`

The locally downloaded patch and ZIP matched the byte counts and hashes reported
by the external engineer. The patch applied cleanly with `patch -p1` to a fresh
`git archive` of the baseline commit.

## Independent test results

The following focused suite was run first in the isolated patched copy and then
again after applying the patch to the working tree:

```text
tests/test_lineup_rules.py
tests/test_optimizer.py
tests/test_backtest.py
tests/test_historical_backtest.py
tests/test_historical_risk_resolution.py
tests/test_single_slate_validation.py
```

- Isolated patched copy: `62 passed in 47.20s`
- Working tree: `62 passed in 26.76s`

The suite covers lineup legality and constraints, no-solution behavior, the old
algorithm baseline, deterministic backtesting, current-slate capture boundaries,
immutable/offline HTTP replay, full-pool actual coverage, explicit DNP=0 evidence,
identity ambiguity rejection, strict first-pitch feature cutoff, selected-only
acknowledgement, seed binding, and feature-file hash binding.

The unfiltered backend suite did not complete in the independently created uv
environment. Collection stopped in `tests/test_content.py` because the resolved
Starlette package required an unavailable `httpx2` package. This is an
environment/dependency-resolution blocker, not a passing test result.

## Acceptance status and remaining risk

The risk-resolution implementation is accepted as a local safety and
reproducibility improvement. It does **not** establish historical optimizer
performance. No historical DK/FD salary slate was found that simultaneously has
non-uniform salaries, provable pre-lock availability, regular-season scope, and a
verifiable official Game Set/DraftGroup. The 2023-03-10 sample remains
`LIMITED_SINGLE_SLATE_VALIDATION`; its prior 17/22/22 score comparison is
superseded and must not be cited as performance evidence.

The current-slate capture workflow provides a path to accumulate qualified data
prospectively. Until such captures are finalized with full-pool postgame actuals,
the performance status remains `INSUFFICIENT DATA / NOT EVALUATED`.
