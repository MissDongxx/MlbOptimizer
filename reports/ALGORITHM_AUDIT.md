# MLB DFS Optimizer Algorithm Audit

## Scope and baseline integrity

- Supplied archive: `MlbOptimizer-e0683a3-source(1).zip`
- Supplied/verified SHA-256: `3736365f4a3c3a2262c8af9e57cd54dd19a9a664c10a41b32352dd7e6704acdf`
- Declared baseline commit: `e0683a36af54c1c5c6259f300c51ee5f7abfdb19`
- Limitation: the archive contains no `.git` metadata, so the commit identity cannot be independently reconstructed from Git objects. The archive hash is independently verified.
- Files reviewed first: `README.md`, `MLB_Optimizer_PRD.md`, `TODO_DATA.md`, `backend/pyproject.toml`, `backend/models/schemas.py`, projection/slate/lineup services, optimizer, and tests.
- Dependency lock: `backend/uv.lock` pins `pydfs-lineup-optimizer` 3.6.1; `pyproject.toml` declares `>=3.6.1`.

## Rule baseline

The implementation uses these Classic roster rules:

| Site | Slots | Salary cap | Same-team rule enforced |
|---|---|---:|---|
| DraftKings | 2 P, C, 1B, 2B, 3B, SS, 3 OF | 50,000 | max 5 hitters from one team |
| FanDuel | P, C/1B, 2B, 3B, SS, 3 OF, UTIL | 35,000 | max 4 hitters from one team; max 5 total only when one is a pitcher |

Sources checked on 2026-07-29:

- DraftKings Rules: `https://www.draftkings.com/help/rules/2` and `/2/2`
- FanDuel Fantasy Baseball / team-limit support: `https://www.fanduel.com/fantasy-baseball` and `https://support.fanduel.com/s/article/How-many-players-can-I-select-from-one-team`
- pydfs repository/docs: `https://github.com/DimaKudosh/pydfs-lineup-optimizer` and `https://pydfs-lineup-optimizer.readthedocs.io/en/latest/rules.html`

The official FanDuel pages were not fetchable as full HTML in the audit environment, but official search/support metadata was consistent with the existing project test expectation of four hitters, and current support wording allows five from a team only when one is a pitcher. This assumption is isolated in `services/lineup_rules.py` and should be rechecked if FanDuel changes its rules.

## Findings and fix mapping

### Critical

| ID | Evidence in supplied baseline | Risk | Fix |
|---|---|---|---|
| C-01 | `backend/services/optimizer.py:184-192` recursively changed `pitcher_vs_batter_same_team` from `avoid` to `allow` when no filtered lineup remained. | Explicit user constraints were silently weakened. Returned lineups could be unacceptable while the API still succeeded. | Removed relaxation. `services/optimizer.py` returns `pitcher_batter_infeasible`; all outputs pass `validate_lineup_set`. |
| C-02 | Fallback loop at lines 47-61 broke on the first unsolved lineup and returned any earlier lineups as success at lines 78-82. pydfs post-filtering also had no exact-count assertion. | “Request N, receive fewer than N” contaminated exposure, method comparison, and user expectations. | Exact-count invariant in both solver and validator. Any shortage raises a structured error and returns no partial set. |
| C-03 | Baseline fallback `_build_best_lineup` had no DK/FD team-limit checks and no post-generation validator. Baseline test reproduced 5 FanDuel hitters from one team. | Illegal lineups could be returned. | Canonical validator plus in-search DK/FD team constraints. Slot labels and player eligibility are checked after generation. |
| C-04 | No historical backtest framework or frozen real slate data existed. Repository search found only a small current player-log cache, with no pre-lock snapshot plus actual DFS scoring pairs. | Product efficacy could not be established and any claimed lift would be unauditable. | Added strict feature/actual contracts, CLI, paired summaries, failure outputs, and a 30-real-slate gate. Current effect status is `NOT EVALUATED`. |

### High

| ID | Evidence in supplied baseline | Risk | Fix |
|---|---|---|---|
| H-01 | Fallback ignored `max_exposure`; pydfs exposure behavior was not independently validated against requested lineup count. | Player exposure could exceed the user ceiling or differ by solver path. | Strict floor-based exposure count and set-level validation applied to every method/path. |
| H-02 | `source_by_id[pydfs_id] = player` at lines 98-106 overwrote duplicate IDs. | Locks, exclusions, scoring joins, exposure, and serialization could refer to the wrong record. | Duplicate IDs are rejected before solving and in both historical files. |
| H-03 | Lock checks only counted pitchers and total locks; they did not solve multi-position lock assignment or reject lock+exclude/DNP/non-positive conflicts. | Infeasible or ambiguous locks failed late or behaved differently across paths. | Deterministic partial matching for locks; explicit `lock_conflict` and `lock_exposure_conflict` errors. |
| H-04 | pydfs opposing-player support requires game information, while the project constructed players without `game_info`. The baseline used oversampling plus post-filtering. | The pydfs path could not natively enforce P-v-B and could return too few lineups or trigger relaxation. | Default audited solver enforces opponent constraints directly. Optional pydfs candidate path is post-validated and falls back without relaxing constraints. When P-v-B avoidance is enabled, a selected pitcher must have explicit opponent metadata; unknown opponent data is treated as infeasible rather than silently ignored. |
| H-05 | No single validator checked lineup count, request/player identity, slot labels, slot eligibility, serialized totals, salaries, locks, team caps, stacks, P-v-B metadata/conflicts, exposure, or uniqueness together. | Different generators could implement different definitions of “legal.” | Added `services/lineup_rules.py`; random, legacy, optimized, pydfs candidates, API output, and backtest all use it. |
| H-06 | Legacy/current behavior was overwritten rather than preserved as a callable comparison target. | Backtests could not fairly compare before and after on identical inputs. | Exact supplied optimizer copied to `services/optimizer_legacy.py`; its output is never trusted without canonical validation. |

### Medium

| ID | Evidence in supplied baseline | Risk | Fix |
|---|---|---|---|
| M-01 | No seed in request/response and no explicit deterministic ordering contract. | Results and test evidence could vary between runs. | Added backward-compatible `seed`, method metadata, stable SHA-256 priorities, stable ordering, and byte-tree reproducibility test. |
| M-02 | Position legality was inferred from selected players but output slot labels were not independently checked. | A lineup could contain an assignable player set while serializing an invalid slot assignment. | Validator checks exact slot multiset and each player’s reported slot eligibility, including multi-position players. |
| M-03 | Error strings collapsed salary, lock, stack, positions, P-v-B, exposure, and uniqueness into generic infeasibility. | Users and automated systems could not remedy failures reliably. | Structured error codes/details, while preserving the old string `detail` field for API compatibility. |
| M-04 | No guard separated feature data from actual scoring, and no source-time boundary existed. | Future-information leakage could produce impressive but invalid backtests. | Separate strict JSON contracts, recursive post-game-key rejection, timestamp checks, and join-after-generation only. |
| M-05 | Baseline fallback capped each slot search to the first 28 rotated candidates and optimized projected points only. | Large pools could exclude feasible/high-quality combinations and method behavior depended on arbitrary truncation. | New exact branch-and-bound searches the eligible pool with deterministic pruning and an explicit audited node-cap failure. |

## Optimized strategy

The new strategy deliberately stays small:

1. maximize frozen pre-lock projected points;
2. subtract `3.5% × projected_points × prior_appearance_count` to encourage portfolio diversity;
3. add a SHA-256-derived `1e-6` tie-break from `(seed, method, lineup_number, player_id)`;
4. solve all hard constraints exactly;
5. fail the whole request if N valid lineups cannot be produced.

The 3.5% value is declared in code before historical evaluation. It was not selected using post-game results. It should remain frozen for the first real 30-slate evaluation or be versioned as a new method.

## Random baseline definition

The random baseline is not rejection sampling. For each lineup it assigns deterministic independent-looking SHA-256 priorities to eligible players, then uses the same exact constrained solver to maximize the sum of those random priorities. This produces a reproducible, clearly defined legal-random baseline. It is not claimed to be mathematically uniform over the entire feasible-lineup set.

## Structured no-solution categories

- `empty_player_pool`
- `duplicate_player_id`
- `missing_salary`
- `minimum_salary_above_cap`
- `position_pool_insufficient`
- `lock_conflict`
- `lock_exposure_conflict`
- `team_limit_infeasible`
- `salary_infeasible`
- `stack_infeasible`
- `pitcher_batter_infeasible`
- `exposure_or_uniqueness_infeasible`
- `solver_capacity`
- `generated_lineup_invalid`

## Residual risks

1. The built-in solver is exact within a 1,500,000-node cap. Large/weakly constrained pools may return `solver_capacity`; it never returns a partial result.
2. The optional pydfs adapter could not be executed in this sandbox because the dependency was unavailable and package installation was blocked by DNS. Its results are nevertheless canonical-postvalidated; production should run the included tests with the locked environment.
3. The preserved legacy method may fail or produce illegal/short output on some slates. That is recorded as a slate failure rather than repaired, because altering it would destroy the baseline.
4. Real scoring provenance and access rights must be supplied with a future dataset. The current repository contains no qualifying 30-slate corpus.
