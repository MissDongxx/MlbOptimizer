# 测试矩阵

最终全量结果：`131 passed in 20.27s`。原始日志见 `TEST_EXECUTION.full-final.txt`，收集清单见 `TEST_COLLECTION.txt`。

| 验收点 | 自动化覆盖 |
|---|---|
| 状态机与幂等 | state machine、重复 registration、重复 attach、相同状态 transition、provider verification 重放 |
| corrupt hash | registry artifact hash/size mismatch |
| late capture | exact lock、post-lock capture、future snapshot |
| uniform salary | qualification reject |
| unverified Game Set | qualification reject，显式证据升级 |
| missing/extra actuals | qualification 与 runner 双层 reject |
| DNP | StatsAPI full-pool DNP=0；无 evidence reject |
| identity ambiguity | historical builder、StatsAPI boxscore、qualification audit reject |
| retry/offline | HTTP retry 后缓存；离线相同 bytes；cache miss hard fail |
| event-time leakage | dataset/model reject available_at >= first pitch |
| same-day future exclusion | projection cutoff 排除 cutoff date 与未来；whole-date split 不跨同日 |
| chronological split | fixed date holdout，train max < test min |
| 训练不足 | REJECTED_NOT_EVALUATED |
| promotion pass/fail | 可通过候选与 rejected candidate 双向测试 |
| serialization/hash | model 与 report 跨目录确定性 hash |
| candidate backtest | qualified registry + candidate model 端到端；四方法并存 |
| optimizer constraints | salary cap、roster、position、lock、exclude、min salary、stack、无解原因、合法性校验 |
| selected-only 风险 | 双重显式确认、seed/hash 绑定 |
| scheduler regression | overlap lock、未来 schedule refresh |

说明：测试中的 fixture 仅证明代码路径、门禁和确定性，不计入真实历史性能样本。
