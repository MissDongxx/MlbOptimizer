# Codex Independent Validation

Validation date: 2026-07-30  
Branch: `codex/full-history-model-automation`  
Git baseline: `5f356365725b1def066b981fed3aa5558bb06522`

## External engineering handoff

- ChatGPT conversation: https://chatgpt.com/c/6a6b0284-17d8-83ee-87ba-9cec14817e7b
- Input workspace ZIP: 2,733,040 bytes
- Input SHA-256: `6093eb16d9bba4b55b0ad0e19993c508d8ec0b73f3dfcc1124d23f09eafa5f06`
- Delivered complete ZIP: 2,782,326 bytes
- Delivered ZIP SHA-256: `2a7e2ecd0b0f0451484028e0b82e999e6c7e6dea6499f1a2dcb722aaacb2c473`
- Delivered cumulative patch: 406,905 bytes
- Delivered patch SHA-256: `c63189895ba651ba0934a0b75db23d7b734a909c67ff34ee24cda65679947768`

The cumulative patch was first dry-run and applied to an isolated extraction of the
exact input ZIP. The isolated tree passed all 131 backend tests.

## Independent results

- Patch dry-run against the exact source package: PASS
- Isolated patch application: PASS
- Isolated backend suite: `131 passed in 51.86s`
- Working-tree backend suite after application: `131 passed in 33.68s`
- Locked dev dependency suite after dependency correction: `131 passed in 30.06s`
- Ruff on backtest and new historical/model tests: PASS
- Python compileall for backtest, models, and services: PASS
- Frontend TypeScript check: PASS
- Local production build: PASS
- Git whitespace check: PASS
- No deployment was performed.

The first independent full-suite attempt exposed an undeclared test dependency:
Starlette's test client required `httpx2`. `pytest` and `httpx2` were added to the
project's dev dependencies and the lock file was regenerated. Ruff then exposed four
unused imports in the delivered patch; these were removed before the final passing run.

The frontend dependency audit printed four high-severity advisories. They pre-existed
this backend-focused change and were not automatically fixed because a dependency
upgrade could expand scope.

## Scope and evidence conclusion

The automatic pipeline now archives immutable inputs, maintains a fail-closed slate
registry, completes full-pool actuals through cached StatsAPI data, qualifies only
event-time-safe real slates, runs deterministic baseline comparisons, and trains an
auditable candidate ridge model only from qualified records. Candidate output remains
additive and never changes production defaults.

The included offline execution is a fixture-path validation, not real historical
performance evidence. It correctly reconstructed 21/21 player outcomes (including one
evidenced DNP) and then rejected the slate because provider Game Set evidence was not
verified. Therefore model promotion is `REJECTED_NOT_EVALUATED` and
`production_action` is `NONE`.

There is still no sufficiently broad, verified, pre-lock real historical pool in the
repository. No claim is made that the optimizer or candidate model improves real
historical scoring. The pipeline is ready to accumulate and automatically evaluate
future genuine uploads as they become available.
