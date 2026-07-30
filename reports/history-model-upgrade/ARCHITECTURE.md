# MLB DFS 历史验证与候选模型自动化架构

## 1. 安全边界

本实现把工作流切成严格串联的两段。Phase B 只能读取 Phase A registry 中状态为 `qualified` 或 `backtested` 的真实 slate。fixture、synthetic、等薪池、赛后抓取冒充赛前、未验证 Game Set、缺失全池 actuals、身份歧义、DNP 无证据或任何 hash 不一致，都会被挡在模型数据集之外。

系统只在配置的 pipeline root 下写入工件。它不修改生产配置，不替换默认 projection，不创建线上 cron/systemd/GitHub Actions，不部署模型，不迁移数据库，也不访问用户数据。

## 2. 数据流

```text
salary CSV + sidecar              complete feature upload
        |                                  |
        v                                  v
current-slate capture          direct-upload discovery
        |                                  |
        +---------- immutable archive -----+
                           |
                           v
                  registry state machine
                           |
                 artifact hash verification
                           |
             StatsAPI cache and actuals builder
                           |
                    strict qualification
                           |
                qualified or rejected slate
                           |
             random / legacy / optimized backtest
                           |
                      backtested state
                           |
              event-time-safe training dataset
                           |
       hitter ridge + pitcher ridge candidate training
                           |
       fixed chronological holdout + walk-forward checks
                           |
     candidate artifact + model card + promotion report
                           |
             optional candidate_model backtest method
```

## 3. Registry 与状态机

允许的状态转移：

- `captured -> awaiting-results`
- `captured -> rejected`
- `awaiting-results -> qualified`
- `awaiting-results -> rejected`
- `qualified -> backtested`
- `qualified -> rejected`
- 相同状态的重复调用为 no-op
- `rejected` 是终态；`backtested` 仅允许在后续 integrity 损坏时转为 `rejected`

Registry 通过临时文件加 `os.replace` 原子写入。单个 pipeline root 的 `run-cycle` 使用非阻塞文件锁，重叠运行会失败关闭，不会同时覆盖 registry、dataset 或 model 工件。

相同 artifact ID 的 `sha256`、字节数、路径或 URL 发生变化会被拒绝。重复发现相同输入不会更新 registry 的 `updated_at`，因此 registry 字节保持稳定。

## 4. Provider Game Set 证据升级

CSV capture 默认只能得到 `provider_game_set_verified=false`。后续不得通过布尔值直接翻转。系统要求归档 `provider-game-set-evidence.json`，并核验：

- schema_version 为 1.0
- provider 非空
- http(s) source_url 与 registry artifact URL 相同
- provider_slate_id 或 draft_group_id 与 feature/registry 身份一致
- captured_at 为带时区时间，且与归档元数据一致
- evidence capture 早于首场 lock
- evidence artifact 角色为 `provider_game_set_evidence`

证据通过后，registry 写入 `provider_verification.verified_at` 和 evidence artifact IDs。重复相同升级为幂等，换证据或身份冲突会失败。

## 5. Phase A 资格门禁

`qualify_registry_entry` 执行以下 fail-closed 检查：

1. 所有注册 artifact 的 bytes 与 SHA-256 完整。
2. feature 和 actuals 严格 schema 可解析。
3. 两者均为 `data_kind=real`。
4. DraftKings Classic roster，slate/site 身份一致。
5. 工资非等薪。
6. provider Game Set 在 feature 与 registry 双侧通过，并有赛前证据工件。
7. feature snapshot 严格早于 lock。
8. feature sources 引用的 raw SHA-256 全部已归档。
9. 至少两场比赛，所有球员映射到比赛。
10. 所有 feature source 的 available_at 早于相关比赛 first pitch。
11. actuals 与 feature player pool 精确一一覆盖，无 missing/extra。
12. final boxscore、raw postgame feeds、DNP=0 和 DNP evidence 完整。
13. identity audit 的 ambiguous_count 与 unresolved_count 都为 0。
14. 至少存在一套合法 2P+C+1B+2B+3B+SS+3OF 阵容。

任何失败都写入 qualification checks 和 rejection_reasons，slate 不计入样本。

## 6. 自动 actuals 与离线重放

`ImmutableHttpCache` 以请求 key 保存原始 response bytes 和 metadata。在线模式支持超时与重试，成功响应不可变归档。离线模式只读 cache，缺 cache 硬失败，不会伪造结果。

`StatsApiFullPoolActualsBuilder` 针对 feature pool 的所有 MLBAM ID 生成 actuals。已出赛球员按 DraftKings scoring 计算，未出赛球员写入 0 分并附 DNP evidence。每个 game feed 必须 final，并写出 identity mapping audit、build audit 和 raw feeds。

## 7. 自动回测

Backtest runner 在提供 registry 时，只接受 registry 中 `qualified/backtested` 且 staged feature/actuals hash 与 qualification hash 完全一致的真实 slate。

每个方法使用相同 seed、相同输入和相同 lineup 数：

- `random`
- `legacy`
- `optimized`
- `candidate_model`，仅在显式提供候选模型时追加

输出包括每个 slate 的 lineup 明细、合法性、actual score、失败表、汇总、样本数、成对相对差、标准误和 paired bootstrap 95% CI。真实 slate 数未达配置门槛时，`evaluation_status` 为 `INSUFFICIENT DATA / NOT EVALUATED`，不作性能结论。

## 8. 模型数据集

Dataset builder 只读 qualified/backtested real entries。每个球员行使用：

- slate 与 game 时间
- feature_available_at
- legacy projection，仅作为对照列，不作为候选 feature
- salary、batting order、lineup status、position one-hot
- feature_values 中通过禁止字段过滤的数值特征
- final actual points 作为 target

硬规则为 `feature_available_at < player game first pitch`。UTC slate date 是不可拆分分组，同一天数据不能跨 train/test。AvgPointsPerGame、actual、final、boxscore、outcome、postgame 字段和 available_at 后缀字段不能进入 feature schema。

## 9. 候选模型与 promotion gate

模型使用 NumPy 实现的确定性 standardized ridge，hitter 与 pitcher 分开训练。保存：

- feature schema
- alpha、seed、code version
- dataset SHA-256
- 每个 slate 的 feature/actuals SHA-256
- training cutoff date
- holdout start/end
- 标准化均值、尺度、截距、系数
- model SHA-256

评估使用完全留出的按日期测试集，不使用随机切分。预留测试集之前的数据另做 expanding walk-forward validation。Promotion report 比较 candidate 与 legacy 的 MAE、RMSE、相关性和 calibration，并检查最小样本、event-time、日期隔离、确定性和预声明阈值。

结果只能是：

- `PROMOTION_ELIGIBLE_CANDIDATE`
- `REJECTED_CANDIDATE`
- `REJECTED_NOT_EVALUATED`

即使通过，也只表示可交给独立审查的候选工件，`production_action` 始终为 `NONE`。
